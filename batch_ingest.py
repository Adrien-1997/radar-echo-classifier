"""
Batch NEXRAD ingestion — multiple sites and dates in one pass.

Reuses all logic from ingest_nexrad.py. Skips already-downloaded files.
Each (site, date, scan_index) tuple produces one ingest run.
"""

import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

from ingest_nexrad import download_scan, insert_to_db, list_scans, parse_scan

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

# Sites chosen for geographic / meteorological variety:
#   KBRO  — Brownsville TX    (Gulf Coast, tropical)
#   KTLX  — Oklahoma City OK  (Tornado Alley, convective)
#   KAMX  — Miami FL          (subtropical, heavy rain)
#   KPBZ  — Pittsburgh PA     (Northeast, stratiform)
TARGETS = [
    # (site, date, scan_index)   note: KBRO/2026-04-11/0 already ingested
    ("KBRO",  "2026-04-10", 0),
    ("KBRO",  "2026-04-12", 0),
    ("KTLX",  "2026-04-10", 0),
    ("KTLX",  "2026-04-11", 0),
    ("KTLX",  "2026-04-12", 0),
    ("KAMX",  "2026-04-10", 0),
    ("KAMX",  "2026-04-11", 0),
    ("KAMX",  "2026-04-12", 0),
    ("KPBZ",  "2026-04-10", 0),
    ("KPBZ",  "2026-04-11", 0),
]

data_dir = Path("data")
data_dir.mkdir(exist_ok=True)

ok, failed = 0, []

for site, date, idx in TARGETS:
    tag = f"{site}/{date}[{idx}]"
    try:
        filenames = list_scans(site, date)
        if not filenames:
            log.warning("%s — no scans found, skipping", tag)
            continue
        if idx >= len(filenames):
            log.warning("%s — index %d out of range (%d scans), skipping", tag, idx, len(filenames))
            continue
        filename = filenames[idx]
        log.info("=== %s  →  %s ===", tag, filename)
        local_path = download_scan(filename, site, date, data_dir)
        df = parse_scan(local_path)
        insert_to_db(df)
        ok += 1
    except Exception as exc:
        log.error("%s FAILED: %s", tag, exc)
        failed.append((tag, exc))

log.info("Done — %d succeeded, %d failed", ok, len(failed))
for tag, exc in failed:
    log.error("  FAILED: %s — %s", tag, exc)

sys.exit(1 if failed else 0)
