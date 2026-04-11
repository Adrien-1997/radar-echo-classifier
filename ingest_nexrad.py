"""
NEXRAD Level-II ingestion script.

Downloads one scan from the public AWS S3 bucket (noaa-nexrad-level2),
parses polarimetric variables with Py-ART, and inserts rows into radar_echoes.

Usage:
    python ingest_nexrad.py --site KBRO --date 2023-05-01
    python ingest_nexrad.py --file data/KBRO20230501_120000_V06   # local file

Label rule (heuristic, no ground truth):
    clutter = 1  if rhohv < 0.85 OR (zh_dbz > 45 AND zdr_db < 0)
    rain    = 0  otherwise
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
THREDDS_CAT  = "https://thredds.ucar.edu/thredds/catalog/nexrad/level2"
THREDDS_FILE = "https://thredds.ucar.edu/thredds/fileServer/nexrad/level2"


# ---------------------------------------------------------------------------
# Unidata THREDDS helpers (raw ar2v files, pyart-compatible, last ~3 days)
# ---------------------------------------------------------------------------

def list_scans(site: str, date: str) -> list[str]:
    """List available scan filenames for a given site and date (YYYY-MM-DD)."""
    ymd = date.replace("-", "")
    url = f"{THREDDS_CAT}/{site}/{ymd}/catalog.html"
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    filenames = list(dict.fromkeys(
        re.findall(rf"Level2_{site}_{ymd}_\d{{4}}\.ar2v", resp.text)
    ))
    return sorted(filenames)


def download_scan(filename: str, site: str, date: str, dest: Path) -> Path:
    """Download a scan from Unidata THREDDS. Returns local path."""
    local_path = dest / filename
    if local_path.exists():
        log.info("Already downloaded: %s", local_path)
        return local_path
    ymd = date.replace("-", "")
    url = f"{THREDDS_FILE}/{site}/{ymd}/{filename}"
    log.info("Downloading %s ...", url)
    with requests.get(url, stream=True, timeout=60) as r:
        r.raise_for_status()
        with open(local_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=1 << 20):
                f.write(chunk)
    log.info("Saved to %s (%.1f MB)", local_path, local_path.stat().st_size / 1e6)
    return local_path


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

FIELD_MAP = {
    "reflectivity":              "zh_dbz",
    "differential_reflectivity": "zdr_db",
    "specific_differential_phase": "kdp_deg_km",
    "cross_correlation_ratio":   "rhohv",
    "differential_phase":        "phidp_deg",
}


def parse_scan(path: Path) -> pd.DataFrame:
    """Parse a NEXRAD Level-II ar2v file into a flat DataFrame."""
    log.info("Parsing %s ...", path)
    return _parse_nexrad_file(path)


def _parse_nexrad_file(path: Path) -> pd.DataFrame:
    """Parse a single NEXRAD Level-II V06 file into a flat DataFrame."""
    radar = pyart.io.read_nexrad_archive(str(path))

    n_rays, n_gates = radar.fields["reflectivity"]["data"].shape
    log.info("  sweeps=%d  rays=%d  gates=%d", radar.nsweeps, n_rays, n_gates)

    # Build per-gate arrays
    data = {}

    for field, col in FIELD_MAP.items():
        if field in radar.fields:
            arr = radar.fields[field]["data"]
            if hasattr(arr, "filled"):
                arr = arr.filled(np.nan)
            data[col] = arr.ravel()
        else:
            log.warning("Field %s not found in scan — filling with NaN", field)
            data[col] = np.full(n_rays * n_gates, np.nan)

    # Azimuth and elevation: broadcast from (n_rays,) to (n_rays, n_gates)
    az = np.broadcast_to(radar.azimuth["data"][:, None],   (n_rays, n_gates)).ravel()
    el = np.broadcast_to(radar.elevation["data"][:, None], (n_rays, n_gates)).ravel()
    rng = np.broadcast_to(radar.range["data"][None, :] / 1000.0, (n_rays, n_gates)).ravel()

    data["azimuth"]    = az
    data["elevation"]  = el
    data["range_km"]   = rng

    # Timestamp: scan start time, broadcast to all gates
    base_time = _parse_radar_time(radar)
    ray_times = np.broadcast_to(base_time, (n_rays, n_gates)).ravel()
    data["timestamp"] = ray_times

    df = pd.DataFrame(data)

    # Drop gates missing the two fields required for labeling
    df = df.dropna(subset=["zh_dbz", "rhohv"]).reset_index(drop=True)

    # Heuristic label
    df["label"] = (
        (df["rhohv"] < 0.85) |
        ((df["zh_dbz"] > 45) & (df["zdr_db"] < 0))
    ).astype(int)

    log.info("  %d valid gates after NaN drop  (%d clutter, %d rain)",
             len(df), df["label"].sum(), (df["label"] == 0).sum())
    return df


def _parse_radar_time(radar) -> datetime:
    """Extract scan start time from radar.time metadata."""
    units = radar.time["units"]          # e.g. "seconds since 2023-05-01T12:00:00Z"
    origin_str = units.split("since ")[-1].replace("T", " ").replace("Z", "")
    origin = datetime.fromisoformat(origin_str).replace(tzinfo=timezone.utc)
    return origin


# ---------------------------------------------------------------------------
# DB insertion
# ---------------------------------------------------------------------------

COLUMNS = ["timestamp", "azimuth", "elevation", "range_km",
           "zh_dbz", "zdr_db", "kdp_deg_km", "rhohv", "phidp_deg", "label"]


def insert_to_db(df: pd.DataFrame) -> None:
    """Bulk-insert using PostgreSQL COPY — ~50x faster than row-by-row INSERT."""
    engine = sqlalchemy.create_engine(DB_URL)
    subset = df[COLUMNS].copy()

    buf = io.StringIO()
    subset.to_csv(buf, index=False, header=False, na_rep="\\N")
    buf.seek(0)

    with engine.begin() as conn:
        raw = conn.connection
        with raw.cursor() as cur:
            cur.copy_expert(
                f"COPY radar_echoes ({', '.join(COLUMNS)}) FROM STDIN WITH (FORMAT CSV, NULL '\\N')",
                buf,
            )
    log.info("Inserted %d rows into radar_echoes", len(subset))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Ingest one NEXRAD scan into PostgreSQL")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--site", help="Radar site code, e.g. KBRO")
    group.add_argument("--file", help="Path to a local NEXRAD Level-II file")
    parser.add_argument("--date", default=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                        help="Date YYYY-MM-DD (used with --site, default: today)")
    parser.add_argument("--scan-index", type=int, default=0,
                        help="Which scan to pick from the day (0 = first, -1 = last)")
    args = parser.parse_args()

    data_dir = Path("data")
    data_dir.mkdir(exist_ok=True)

    if args.file:
        local_path = Path(args.file)
    else:
        filenames = list_scans(args.site, args.date)
        if not filenames:
            log.error("No scans found for %s on %s", args.site, args.date)
            return
        filename = filenames[args.scan_index]
        log.info("Selected scan: %s", filename)
        local_path = download_scan(filename, args.site, args.date, data_dir)

    df = parse_scan(local_path)
    insert_to_db(df)


if __name__ == "__main__":
    main()
