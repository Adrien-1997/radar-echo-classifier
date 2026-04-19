"""
Batch NEXRAD Level-III ingestion — multiple sites and dates in one pass.

Reuses ingest_nexrad_l3.ingest_l3(). Skips already-downloaded files.
Dates chosen for geographic / meteorological variety:
  KBRO  — Brownsville TX    (Gulf Coast, tropical)
  KTLX  — Oklahoma City OK  (Tornado Alley, convective)
  KAMX  — Miami FL          (subtropical, heavy rain)
  KPBZ  — Pittsburgh PA     (Northeast, stratiform)

Usage:
    python batch_ingest.py
"""

import logging
import sys

from ingest_nexrad_l3 import ingest_l3

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

# (site, date, scan_index)
TARGETS = [
    ("KBRO", "2026-04-17", 0),
    ("KBRO", "2026-04-16", 0),
    ("KBRO", "2026-04-15", 0),
    ("KTLX", "2026-04-17", 0),
    ("KTLX", "2026-04-16", 0),
    ("KTLX", "2026-04-15", 0),
    ("KAMX", "2026-04-17", 0),
    ("KAMX", "2026-04-16", 0),
    ("KAMX", "2026-04-15", 0),
    ("KPBZ", "2026-04-17", 0),
    ("KPBZ", "2026-04-16", 0),
    ("KPBZ", "2026-04-15", 0),
]

ok, failed = 0, []

for site, date, idx in TARGETS:
    tag = f"{site}/{date}[{idx}]"
    try:
        log.info("=== %s ===", tag)
        ingest_l3(site, date, idx)
        ok += 1
    except Exception as exc:
        log.error("%s FAILED: %s", tag, exc)
        failed.append((tag, exc))

log.info("Done — %d succeeded, %d failed", ok, len(failed))
for tag, exc in failed:
    log.error("  FAILED: %s — %s", tag, exc)

sys.exit(1 if failed else 0)
