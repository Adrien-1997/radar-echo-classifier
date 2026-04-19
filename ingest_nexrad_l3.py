"""
NEXRAD Level-III ingestion script.

Downloads 5 Level-III products from Unidata THREDDS for a given site/time,
parses them with Py-ART, and bulk-inserts into radar_echoes with HCA-derived labels.

Products fetched per scan (lowest elevation only):
  N0B  — Base Reflectivity (super-res, 720×1840, resampled to N0H grid) → zh_dbz
  N0X  — Differential Reflectivity (360×1200) → zdr_db
  N0C  — Correlation Coefficient   (360×1200) → rhohv
  N0K  — Specific Diff. Phase      (360×1200) → kdp_deg_km
  N0H  — Hydrometeor Classification (360×1200) → label (binary)

phidp_deg is not available in Level-III; the column is left NULL.

HCA label mapping (NEXRAD codes are multiples of 10):
  clutter = 1 : 10 (Biological), 20 (AP / Ground Clutter)
  rain    = 0 : 30–100 (meteorological classes)
  dropped     : 140 (Unknown) and fill values

Usage:
    python ingest_nexrad_l3.py --site KBRO --date 2026-04-17
    python ingest_nexrad_l3.py --site KBRO --date 2026-04-17 --scan-index -1
"""

import argparse
import io
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pyart
import requests
import sqlalchemy

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

DB_URL = "postgresql://radar:radar@localhost:5432/radar_db"
THREDDS_CAT  = "https://thredds.ucar.edu/thredds/catalog/nexrad/level3"
THREDDS_FILE = "https://thredds.ucar.edu/thredds/fileServer/nexrad/level3"

# Products to fetch: product_code → DB column (None = used only for label)
# N0B is super-res reflectivity (720×1840) and is resampled to the N0H grid (360×1200).
PRODUCTS = {
    "N0B": "zh_dbz",
    "N0X": "zdr_db",
    "N0C": "rhohv",
    "N0K": "kdp_deg_km",
    "N0H": None,        # HCA — used for label derivation, not a feature column
}

# pyart CF/Radial field names for each Level-III product
PYART_FIELDS = {
    "N0B": "reflectivity",
    "N0X": "differential_reflectivity",
    "N0C": "cross_correlation_ratio",
    "N0K": "specific_differential_phase",
    "N0H": "radar_echo_classification",
}

# NEXRAD HCA codes are multiples of 10. None = drop gate.
HCA_LABEL = {
    10.0: 1,    # Biological           → clutter
    20.0: 1,    # AP / Ground Clutter  → clutter
    30.0: 0,    # Ice Crystals         → rain
    40.0: 0,    # Dry Snow             → rain
    50.0: 0,    # Wet Snow             → rain
    60.0: 0,    # Light/Moderate Rain  → rain
    70.0: 0,    # Heavy Rain           → rain
    80.0: 0,    # Big Drops            → rain
    90.0: 0,    # Graupel              → rain
    100.0: 0,   # Hail                 → rain
    130.0: 1,   # Tornado Debris       → clutter
    140.0: None, # Unknown             → drop
}

DB_COLUMNS = ["timestamp", "azimuth", "elevation", "range_km",
              "zh_dbz", "zdr_db", "kdp_deg_km", "rhohv", "phidp_deg", "label"]


# ---------------------------------------------------------------------------
# THREDDS helpers
# ---------------------------------------------------------------------------

def _site3(site: str) -> str:
    """THREDDS Level-III uses 3-letter codes (drop leading K from ICAO 4-letter codes)."""
    return site[1:] if len(site) == 4 and site.startswith("K") else site


def list_scans_l3(product: str, site: str, date: str) -> list[str]:
    """List available Level-III filenames for a product/site/date (YYYY-MM-DD)."""
    s3 = _site3(site)
    ymd = date.replace("-", "")
    url = f"{THREDDS_CAT}/{product}/{s3}/{ymd}/catalog.html"
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    filenames = list(dict.fromkeys(
        re.findall(rf"Level3_{s3}_{product}_{ymd}_\d{{4}}\.nids", resp.text)
    ))
    return sorted(filenames)


def download_l3(product: str, filename: str, site: str, date: str, dest: Path) -> Path:
    """Download one Level-III file from THREDDS. Returns local path."""
    local_path = dest / filename
    if local_path.exists():
        log.info("Already downloaded: %s", local_path)
        return local_path
    s3 = _site3(site)
    ymd = date.replace("-", "")
    url = f"{THREDDS_FILE}/{product}/{s3}/{ymd}/{filename}"
    log.info("Downloading %s ...", url)
    with requests.get(url, stream=True, timeout=60) as r:
        r.raise_for_status()
        with open(local_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=1 << 20):
                f.write(chunk)
    log.info("Saved %s (%.2f MB)", local_path, local_path.stat().st_size / 1e6)
    return local_path


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def _resample_to_grid(data: np.ndarray, src_range_m: np.ndarray, dst_range_m: np.ndarray) -> np.ndarray:
    """
    Resample a super-res Level-III array (720 rays × n_gates) to standard N0H grid (360 rays × dst_gates).
    Ray axis: average consecutive pairs (720 → 360).
    Gate axis: for each dst gate, average src gates within ±500m.
    Gates beyond src range coverage are left as NaN.
    """
    arr = np.where(np.isnan(data), np.nan, data.astype(float))

    if arr.shape[0] == 720:
        arr = np.nanmean(arr.reshape(360, 2, arr.shape[1]), axis=1)  # (360, n_src_gates)
    # else: already 360 rows, no ray resampling needed

    n_dst = len(dst_range_m)
    result = np.full((360, n_dst), np.nan)
    for j in range(n_dst):
        idx = np.where(np.abs(src_range_m - dst_range_m[j]) <= 500)[0]
        if len(idx):
            result[:, j] = np.nanmean(arr[:, idx], axis=1)
    return result


def _read_l3_field(path: Path, field: str) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, datetime]:
    """
    Read one Level-III NIDS file.
    Returns (data[n_rays, n_gates], azimuth[n_rays], elevation[n_rays], range_km[n_gates], timestamp).
    """
    radar = pyart.io.read_nexrad_level3(str(path))

    arr = radar.fields[field]["data"]
    if hasattr(arr, "filled"):
        arr = arr.filled(np.nan)

    az  = radar.azimuth["data"]
    el  = radar.elevation["data"]
    rng = radar.range["data"] / 1000.0

    units = radar.time["units"]
    origin_str = units.split("since ")[-1].replace("T", " ").replace("Z", "")
    ts = datetime.fromisoformat(origin_str).replace(tzinfo=timezone.utc)

    return arr, az, el, rng, ts


def parse_l3_scan(paths: dict[str, Path]) -> pd.DataFrame:
    """
    Parse a set of Level-III product files (one per product) into a flat DataFrame.
    paths: {product_code: local_path}
    HCA (N0H) must be present; polarimetric products are optional (filled with NaN if missing).
    """
    # HCA defines the grid geometry
    hca_arr, az, el, rng, ts = _read_l3_field(paths["N0H"], PYART_FIELDS["N0H"])
    n_rays, n_gates = hca_arr.shape
    log.info("  rays=%d  gates=%d  elevation=%.1f°", n_rays, n_gates, float(np.nanmean(el)))

    az_grid  = np.broadcast_to(az[:, None],  (n_rays, n_gates)).ravel()
    el_grid  = np.broadcast_to(el[:, None],  (n_rays, n_gates)).ravel()
    rng_grid = np.broadcast_to(rng[None, :], (n_rays, n_gates)).ravel()

    df = pd.DataFrame({
        "timestamp": np.broadcast_to(ts, (n_rays, n_gates)).ravel(),
        "azimuth":   az_grid,
        "elevation": el_grid,
        "range_km":  rng_grid,
        "_hca":      hca_arr.ravel().astype(float),
    })

    # Polarimetric products
    for product, col in [("N0B", "zh_dbz"), ("N0X", "zdr_db"),
                         ("N0C", "rhohv"),  ("N0K", "kdp_deg_km")]:
        if product not in paths:
            log.warning("%s not available — %s will be NULL", product, col)
            df[col] = np.nan
            continue
        try:
            arr, _, _, src_rng, _ = _read_l3_field(paths[product], PYART_FIELDS[product])
            if arr.shape != hca_arr.shape:
                log.info("%s shape %s ≠ N0H shape %s — resampling to N0H grid", product, arr.shape, hca_arr.shape)
                arr = _resample_to_grid(arr, src_rng * 1000, rng * 1000)  # km → m
            df[col] = arr.ravel()
        except Exception as exc:
            log.warning("Could not parse %s (%s) — filling with NaN", product, exc)
            df[col] = np.nan

    df["phidp_deg"] = np.nan  # Not distributed as a Level-III product

    # HCA → binary label (drop unclassified/unknown)
    df["label"] = df["_hca"].map(HCA_LABEL)
    n_total = len(df)
    df = df.dropna(subset=["label", "zh_dbz", "rhohv"]).reset_index(drop=True)
    df["label"] = df["label"].astype(int)
    df = df.drop(columns=["_hca"])

    n_clutter = int(df["label"].sum())
    n_rain    = int((df["label"] == 0).sum())
    n_dropped = n_total - len(df)
    log.info("  %d → %d valid gates  (clutter=%d  rain=%d  dropped=%d)",
             n_total, len(df), n_clutter, n_rain, n_dropped)
    return df


# ---------------------------------------------------------------------------
# DB insertion
# ---------------------------------------------------------------------------

def insert_to_db(df: pd.DataFrame) -> None:
    """Bulk-insert via PostgreSQL COPY — ~50× faster than row-by-row INSERT."""
    engine = sqlalchemy.create_engine(DB_URL)
    subset = df[DB_COLUMNS].copy()
    buf = io.StringIO()
    subset.to_csv(buf, index=False, header=False, na_rep="\\N")
    buf.seek(0)
    with engine.begin() as conn:
        raw = conn.connection
        with raw.cursor() as cur:
            cur.copy_expert(
                f"COPY radar_echoes ({', '.join(DB_COLUMNS)}) FROM STDIN WITH (FORMAT CSV, NULL '\\N')",
                buf,
            )
    log.info("Inserted %d rows into radar_echoes", len(subset))


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def ingest_l3(site: str, date: str, scan_index: int = 0) -> None:
    """Download and ingest one Level-III scan (all products) for a given site/date."""
    data_dir = Path("data") / "level3"
    data_dir.mkdir(parents=True, exist_ok=True)

    paths: dict[str, Path] = {}

    for product in PRODUCTS:
        try:
            filenames = list_scans_l3(product, site, date)
        except requests.HTTPError as exc:
            if product == "N0H":
                raise RuntimeError(f"HCA product N0H not found for {site} on {date}: {exc}") from exc
            log.warning("%s catalog unavailable (%s) — column will be NULL", product, exc)
            continue

        if not filenames:
            if product == "N0H":
                raise RuntimeError(f"No HCA (N0H) files found for {site} on {date}")
            log.warning("No %s files for %s on %s — column will be NULL", product, site, date)
            continue

        if abs(scan_index) >= len(filenames):
            log.warning("%s: index %d out of range (%d files) — using last", product, scan_index, len(filenames))
            idx = -1
        else:
            idx = scan_index

        filename = filenames[idx]
        paths[product] = download_l3(product, filename, site, date, data_dir)

    df = parse_l3_scan(paths)
    insert_to_db(df)


def main():
    parser = argparse.ArgumentParser(description="Ingest NEXRAD Level-III scan into PostgreSQL")
    parser.add_argument("--site",  required=True,
                        help="4-letter radar site code, e.g. KBRO")
    parser.add_argument("--date",  default=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                        help="Date YYYY-MM-DD (default: today UTC)")
    parser.add_argument("--scan-index", type=int, default=0,
                        help="Index within the day (0=first, -1=last)")
    args = parser.parse_args()
    ingest_l3(args.site, args.date, args.scan_index)


if __name__ == "__main__":
    main()
