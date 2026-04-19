"""NEXRAD Level-III fetch + parse helpers (no DB). Used by /score_nexrad."""

import logging
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pyart
import requests

log = logging.getLogger(__name__)

THREDDS_CAT  = "https://thredds.ucar.edu/thredds/catalog/nexrad/level3"
THREDDS_FILE = "https://thredds.ucar.edu/thredds/fileServer/nexrad/level3"

PRODUCTS = {
    "N0B": "zh_dbz",
    "N0X": "zdr_db",
    "N0C": "rhohv",
    "N0K": "kdp_deg_km",
    "N0H": None,  # HCA — label derivation only
}

PYART_FIELDS = {
    "N0B": "reflectivity",
    "N0X": "differential_reflectivity",
    "N0C": "cross_correlation_ratio",
    "N0K": "specific_differential_phase",
    "N0H": "radar_echo_classification",
}


def _site3(site: str) -> str:
    """THREDDS Level-III uses 3-letter codes (drop leading K from ICAO 4-letter codes)."""
    return site[1:] if len(site) == 4 and site.startswith("K") else site


def list_scans_l3(product: str, site: str, date: str) -> list[str]:
    s3 = _site3(site)
    ymd = date.replace("-", "")
    url = f"{THREDDS_CAT}/{product}/{s3}/{ymd}/catalog.html"
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    filenames = list(dict.fromkeys(
        re.findall(rf"Level3_{s3}_{product}_{ymd}_\d{{4}}\.nids", resp.text)
    ))
    return sorted(filenames)


def _fetch_file(product: str, filename: str, site: str, date: str, dest: Path) -> Path:
    local_path = dest / filename
    if local_path.exists():
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
    return local_path


def _read_l3_field(path: Path, field: str):
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


def _resample_to_grid(data: np.ndarray, src_range_m: np.ndarray, dst_range_m: np.ndarray) -> np.ndarray:
    arr = np.where(np.isnan(data), np.nan, data.astype(float))
    if arr.shape[0] == 720:
        arr = np.nanmean(arr.reshape(360, 2, arr.shape[1]), axis=1)
    n_dst = len(dst_range_m)
    result = np.full((360, n_dst), np.nan)
    for j in range(n_dst):
        idx = np.where(np.abs(src_range_m - dst_range_m[j]) <= 500)[0]
        if len(idx):
            result[:, j] = np.nanmean(arr[:, idx], axis=1)
    return result


def fetch_and_parse(site: str, date: str, scan_index: int = -1) -> pd.DataFrame:
    """Download NEXRAD L3 products and return a flat DataFrame of gate features.

    Downloads into a temporary directory that is removed on return.
    Only gates with valid zh_dbz and rhohv are kept (NaN rows dropped).
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        dest = Path(tmpdir)
        paths: dict[str, Path] = {}

        for product in PRODUCTS:
            try:
                filenames = list_scans_l3(product, site, date)
            except requests.HTTPError as exc:
                if product == "N0H":
                    raise RuntimeError(f"HCA (N0H) not found for {site} on {date}: {exc}") from exc
                log.warning("%s catalog unavailable — column will be NULL", product)
                continue

            if not filenames:
                if product == "N0H":
                    raise RuntimeError(f"No N0H files found for {site} on {date}")
                log.warning("No %s files for %s on %s — column will be NULL", product, site, date)
                continue

            idx = scan_index if abs(scan_index) < len(filenames) else -1
            paths[product] = _fetch_file(product, filenames[idx], site, date, dest)

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
        })

        for product, col in [("N0B", "zh_dbz"), ("N0X", "zdr_db"),
                              ("N0C", "rhohv"),  ("N0K", "kdp_deg_km")]:
            if product not in paths:
                df[col] = np.nan
                continue
            try:
                arr, _, _, src_rng, _ = _read_l3_field(paths[product], PYART_FIELDS[product])
                if arr.shape != hca_arr.shape:
                    log.info("%s shape %s ≠ N0H — resampling", product, arr.shape)
                    arr = _resample_to_grid(arr, src_rng * 1000, rng * 1000)
                df[col] = arr.ravel()
            except Exception as exc:
                log.warning("Could not parse %s (%s) — filling with NaN", product, exc)
                df[col] = np.nan

        df = df.dropna(subset=["zh_dbz", "rhohv"]).reset_index(drop=True)
        log.info("Fetched %d valid gates from %s on %s (scan_index=%d)", len(df), site, date, scan_index)
        return df
