# radar-echo-classifier

End-to-end ML pipeline for meteorological radar echo classification (rain vs clutter). Stack: Python, PostgreSQL, Grafana, n8n, FastAPI, Jupyter.

---

## Current Status

| # | Item | Status |
|---|------|--------|
| ✅ | Full Docker stack (Postgres, Grafana, n8n, ES, Kibana, FastAPI scorer) | Done |
| ✅ | NEXRAD Level-III ingestion — 808k gates, 4 sites, HCA labels | Done |
| ✅ | LightGBM model — `PolarimetricEngineer → SimpleImputer → LGBMClassifier` | Done |
| ✅ | FastAPI scorer — `/predict`, `/score_latest`, `/score_nexrad`, `/log_run` | Done |
| ✅ | Grafana dashboard auto-provisioned from repo | Done |
| ✅ | n8n workflow auto-imported on stack startup (idempotent) | Done |
| 🔧 | `/score_latest` deduplication — re-scores same gates on every call | Next |
| 🔧 | Automated tests — `PolarimetricEngineer`, `/predict`, `/score_nexrad` | Backlog |
| 🔧 | n8n cron trigger + real alert channel | Backlog |
| 🔧 | Offline packaging — `docker save` + pip wheels for air-gapped deploy | Backlog (J14) |

---

## Overview

Weather radars return echoes from both precipitation and non-meteorological sources (ground clutter, insects, anomalous propagation, etc.). This project builds a full ML pipeline to classify each radar **gate** as **rain** or **clutter** using dual-polarization variables, and wraps it in a production stack: live ingestion, automated scoring, alerting, and dashboarding.

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│                          DATA SOURCE                                 │
│                                                                      │
│   NEXRAD Level-III (Unidata THREDDS)                                 │
│   Products: N0B / N0X / N0C / N0K / N0H (HCA)                       │
│   Training sites: KBRO, KTLX, KAMX, KPBZ                            │
└──────────────────────────┬───────────────────────────────────────────┘
                           │  pyart — parse NIDS binaries
                           ▼
┌──────────────────────────────────────────────────────────────────────┐
│                        PostgreSQL :5432                              │
│                                                                      │
│   radar_echoes          radar_predictions      radar_scoring_runs    │
│   (raw gates            (proba + prediction     (run summary:        │
│    + HCA labels)         per gate)               site, clutter_rate) │
└────────────┬─────────────────────────────────────────────────────────┘
             │
             ▼
┌──────────────────────────────────────────────────────────────────────┐
│                     FastAPI scorer :8000                             │
│                                                                      │
│  /health         — service status                                    │
│  /predict        — score a single gate (JSON body)                   │
│  /score_latest   — score latest N gates from radar_echoes            │
│  /score_nexrad   — live THREDDS fetch + in-memory scoring            │
│  /log_run        — write a run summary to radar_scoring_runs         │
│                                                                      │
│  Pipeline loaded from model/clf.pkl:                                 │
│  PolarimetricEngineer → SimpleImputer → LightGBM                     │
└────────────┬─────────────────────────────────────────────────────────┘
             │
             ▼
┌──────────────────────────────────────────────────────────────────────┐
│                          n8n :5678                                   │
│                                                                      │
│  Manual Trigger                                                      │
│  → Parameters (site, scan_index)                                     │
│  → POST /score_nexrad  ──┬──→ POST /log_run  (→ radar_scoring_runs)  │
│                          └──→ Clutter detected?                      │
│                                yes → Alert → Grafana Annotation      │
│                                no  → OK                              │
└────────────┬─────────────────────────────────────────────────────────┘
             │
             ▼
┌──────────────────────────────────────────────────────────────────────┐
│                        Grafana :3000                                 │
│                                                                      │
│  Dashboard "Radar Clutter Monitor"                                   │
│  ├─ Clutter rate over time (time series, red threshold at 40%)       │
│  ├─ Last clutter rate / last site / runs 24h / alerts today (stats)  │
│  ├─ Recent runs (table)                                              │
│  └─ Red annotation markers on alert scans                            │
│                                                                      │
│  Auto-provisioned from grafana/provisioning/                         │
└──────────────────────────────────────────────────────────────────────┘
```

---

## Stack

| Component | Role |
|-----------|------|
| **PostgreSQL 15** | Raw gate storage, predictions, run summaries |
| **FastAPI scorer** | REST scoring API — loads `model/clf.pkl` |
| **n8n** | Orchestration: live NEXRAD fetch → score → log → Grafana alert — workflow auto-imported on startup |
| **Grafana** | Real-time dashboard — fed by `radar_scoring_runs` |
| **Jupyter Lab** | EDA (`01_eda.ipynb`) and training (`02_train.ipynb`) — outside Docker |

---

## Exposed Ports

| Port | Service |
|------|---------|
| 3000 | Grafana (admin / admin) |
| 5432 | PostgreSQL |
| 5678 | n8n (admin / admin) |
| 8000 | FastAPI scorer (`/docs` for Swagger UI) |

---

## Project Structure

```
radar-echo-classifier/
├── notebooks/
│   ├── 01_eda.ipynb              # EDA — distributions, null analysis, spatial patterns
│   └── 02_train.ipynb            # LightGBM training, SHAP, exports model/clf.pkl
├── scorer/
│   ├── main.py                   # FastAPI app — /predict /score_nexrad /log_run
│   ├── feature_engineering.py    # PolarimetricEngineer (shared notebook ↔ scorer)
│   ├── nexrad_ingest.py          # NEXRAD Level-III fetch + parse (no DB)
│   ├── requirements.txt
│   └── Dockerfile
├── n8n/
│   ├── workflow_score_latest.json  # n8n workflow — auto-imported on stack startup
│   └── README.md
├── grafana/
│   ├── dashboards/
│   │   └── clutter_monitor.json    # Auto-provisioned dashboard
│   └── provisioning/
│       ├── datasources/postgres.yaml
│       └── dashboards/provider.yaml
├── sql/
│   └── init_schema.sql           # Full schema (radar_echoes, radar_predictions, radar_scoring_runs)
├── model/                        # Drop clf.pkl here (gitignored)
├── figures/                      # SHAP plots from 02_train.ipynb
├── data/                         # Local NIDS files (gitignored)
├── ingest_nexrad_l3.py           # Level-III ingestion → PostgreSQL (training data)
├── batch_ingest.py               # Multi-site/date batch ingestion (12 scans, 4 sites)
├── generate_data.py              # Synthetic data generator (dev only)
├── docker-compose.yml
├── requirements.txt
└── environment.yml
```

---

## Polarimetric Features

| Variable | Description | Used by model |
|----------|-------------|---------------|
| `zh_dbz` | Horizontal reflectivity (dBZ) | Yes |
| `zdr_db` | Differential reflectivity (dB) | Yes |
| `rhohv` | Cross-correlation coefficient | Yes |
| `azimuth` | Beam azimuth (°) → encoded as sin/cos | Yes |
| `range_km` | Range from radar (km) → log1p | Yes |
| `kdp_deg_km` | Specific differential phase (°/km) | No (ingested, not used) |
| `phidp_deg` | Differential phase (°) | No (NULL in Level-III) |
| `elevation` | Beam elevation (°) | No |

**Label source:** NEXRAD Level-III HCA (N0H) — ground-truth labels from the radar's own signal processor.
- `clutter = 1` : HCA codes 10 (Biological), 20 (AP / Ground Clutter), 130 (Tornado Debris)
- `rain    = 0` : HCA codes 30–100 (all meteorological classes)
- `dropped`    : HCA code 140 (Unknown) and fill values

---

## Training Data

| Site | Location | Dates | Scans |
|------|----------|-------|-------|
| KBRO | Brownsville TX (Gulf Coast) | 15–17 Apr 2026 | 3 |
| KTLX | Oklahoma City OK (Tornado Alley) | 15–17 Apr 2026 | 3 |
| KAMX | Miami FL (subtropical) | 15–17 Apr 2026 | 3 |
| KPBZ | Pittsburgh PA (Northeast) | 15–17 Apr 2026 | 3 |

**Total:** 12 scans — 808,247 valid gates — 71.6% clutter / 28.4% rain
**Split:** 9 scans train / 3 scans test (temporal split by scan, not by gate)

---

## Quick Start

### 1. Clone

```bash
git clone https://github.com/Adrien-1997/radar-echo-classifier.git
cd radar-echo-classifier
```

### 2. Start the stack

```bash
docker compose up -d
```

### 3. Initialise the database

```bash
docker compose exec postgres psql -U radar -d radar_db < sql/init_schema.sql
```

### 4. Open the tools

| URL | Credentials |
|-----|-------------|
| http://localhost:3000 | Grafana (admin / admin) |
| http://localhost:5678 | n8n (admin / admin) |
| http://localhost:8000/docs | FastAPI Swagger UI |

> **n8n workflow** — `n8n/workflow_score_latest.json` is automatically imported when the container
> starts (the entrypoint runs `n8n import:workflow` before launching the server). The workflow has
> a stable `"id"` so re-deploying is idempotent: n8n updates the existing workflow instead of
> creating a duplicate. If the import fails for any reason, n8n still starts and you can fall back
> to the manual import: **Workflows → Import from file**.

### 5. Run a live scoring

```bash
curl -X POST http://localhost:8000/score_nexrad \
  -H "Content-Type: application/json" \
  -d '{"site": "KBRO", "scan_index": -1}'
```

### 6. Inject a test run into Grafana

```bash
curl -X POST http://localhost:8000/log_run \
  -H "Content-Type: application/json" \
  -d '{"site": "KBRO", "n_scored": 2910, "n_clutter": 350, "clutter_rate": 0.12}'
```

### 7. Connect to PostgreSQL directly

```bash
docker compose exec postgres psql -U radar -d radar_db
```

---

## Local Python Environment (without Docker)

```bash
conda env create -f environment.yml
conda activate radar-pipeline
```

---

## License

MIT — see [LICENSE](LICENSE).
