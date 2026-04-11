# radar-echo-classifier

End-to-end ML pipeline for meteorological radar echo classification (rain vs clutter). Stack: Python, PostgreSQL, Dataiku, Grafana, Kibana, Elasticsearch, n8n, FastAPI, Jupyter.

This is a data science side project that explores how to build a production-grade classification pipeline on polarimetric weather radar data, from raw echo ingestion to automated alerting.

---

## Overview

Weather radars return echoes from both precipitation and non-meteorological sources (ground clutter, insects, aircraft, etc.). This project builds a full ML pipeline to classify each radar gate as **rain** or **clutter** using dual-polarization variables, and wraps it in a modern data platform stack.

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│                          DATA SOURCES                                │
│                                                                      │
│   NEXRAD files (S3 / local)           Synthetic generator            │
│   pyart / wradlib parser              generate_data.py               │
└──────────────────────────┬───────────────────────────────────────────┘
                           │  raw polarimetric echoes
                           ▼
┌──────────────────────────────────────────────────────────────────────┐
│                        PostgreSQL :5432                              │
│                                                                      │
│   radar_echoes       radar_features       radar_predictions          │
│   (raw features      (engineered          (clutter_proba,            │
│    + label)           ratios, flags)       prediction, run_id)       │
└────────────┬──────────────────────────────────────────┬──────────────┘
             │                                          │
             │  query features                          │  write predictions
             ▼                                          │
┌────────────────────────┐                              │
│      n8n :5678         │                              │
│                        │                              │
│  cron trigger          │                              │
│  → query PG            │                              │
│  → POST /predict  ─────┼──────────────────────────────┤
│  → alert if            │                              │
│    clutter_rate > 40%  │                              │
└────────────────────────┘                              │
             │                                          │
             │  POST /predict                           │
             ▼                                          │
┌────────────────────────┐                              │
│   FastAPI scorer :8000 │                              │
│                        │                              │
│  /health               │  clutter_proba               │
│  /predict  ────────────┼──────────────────────────────┘
│                        │
│  loads model.pkl       │
│  (LightGBM)            │
└────────────────────────┘
┌──────────────────────────────────────────────────────────────────────┐
│  OBSERVABILITY                                                       │
│                                                                      │
│  Grafana :3000                                                       │
│  └─ reads PostgreSQL directly                                        │
│     clutter rate, rolling AUC, heatmap, latency, alert rule          │
│                                                                      │
│  Elasticsearch :9200                                                 │
│  └─ receives pipeline run logs                                       │
│                                                                      │
│  Kibana :5601                                                        │
│  └─ UI over Elasticsearch (dev only)                                 │
└──────────────────────────────────────────────────────────────────────┘
┌──────────────────────────────────────────────────────────────────────┐
│  DEV TOOLING                                                         │
│                                                                      │
│  Jupyter Lab :8888                                                   │
│  └─ 01_eda.ipynb                                                     │
│  └─ 02_shap.ipynb                                                    │
│  └─ outputs model.pkl                                                │
│                                                                      │
│  Dataiku :10000 (external)                                           │
│  └─ visual ML lab, pipeline recipes                                  │
│  └─ exports model.pkl to scorer/                                     │
└──────────────────────────────────────────────────────────────────────┘
```

---

## Stack

| Component | Role |
|-----------|------|
| **PostgreSQL 15** | Store raw radar echoes, engineered features, and model predictions |
| **Elasticsearch 8** | Index predictions and logs for full-text search and analytics |
| **Kibana 8** | Explore and visualize Elasticsearch indices |
| **Grafana** | Real-time dashboards: clutter rate, rolling AUC, latency — see [grafana/dashboards/README.md](grafana/dashboards/README.md) |
| **n8n** | Workflow automation: cron scoring, alerting when clutter rate > 40% — see [n8n/README.md](n8n/README.md) |
| **Jupyter Lab** | EDA, feature engineering, model training, SHAP explainability — runs directly from venv, not Docker |
| **FastAPI scorer** | REST API to serve model predictions (`/predict`) |
| **Dataiku** | Orchestrate the full pipeline visually (external, port 10000) |

---

## Exposed Ports

| Port | Service |
|------|---------|
| 3000 | Grafana |
| 5432 | PostgreSQL |
| 5601 | Kibana |
| 5678 | n8n |
| 8000 | FastAPI scorer |
| 8888 | Jupyter Lab (venv, not Docker) |
| 9200 | Elasticsearch |
| 10000 | Dataiku (external, not in Docker Compose) |

---

## Project Structure

```
radar-echo-classifier/
├── notebooks/           # Jupyter notebooks (EDA, SHAP, training)
├── sql/                 # Schema DDL and query helpers
├── scorer/              # FastAPI microservice (Dockerfile + app)
├── n8n/                 # n8n workflow documentation
├── grafana/dashboards/  # Grafana dashboard specs and docs
├── docs/                # Additional documentation
├── data/                # Local data files (gitignored)
├── generate_data.py     # Synthetic polarimetric data generator
├── setup.sh             # Bootstrap script (DB init + data load)
├── docker-compose.yml   # Full stack definition
├── requirements.txt     # Python dependencies
└── environment.yml      # Conda environment
```

---

## Polarimetric Features

| Variable | Description |
|----------|-------------|
| `zh_dbz` | Horizontal reflectivity (dBZ) |
| `zdr_db` | Differential reflectivity (dB) |
| `kdp_deg_km` | Specific differential phase (°/km) |
| `rhohv` | Cross-correlation coefficient |
| `phidp_deg` | Differential phase (°) |
| `azimuth` | Beam azimuth (°) |
| `elevation` | Beam elevation (°) |
| `range_km` | Range from radar (km) |

**Label rule (synthetic):** `clutter = 1` if `rhohv < 0.85` OR (`zh_dbz > 45` AND `zdr_db < 0`), else `rain = 0`.

---

## Status

- [x] Repo scaffolded
- [x] Python venv (WSL)
- [x] Docker Desktop + WSL integration (data moved to D drive)
- [x] docker-compose finalized — Jupyter removed (runs from venv directly)
- [x] PostgreSQL running and healthy (`localhost:5432`)
- [x] Full docker-compose stack up (Postgres, Grafana, n8n, Elasticsearch, Kibana, scorer)
- [x] DB schema applied (`sql/init_schema.sql`)
- [x] NEXRAD ingestion script (`ingest_nexrad.py`) — downloads from Unidata THREDDS, parses with Py-ART, bulk-inserts via COPY
- [x] First real radar scan ingested — 563k gates, KBRO 2026-04-11
- [ ] More scans ingested (temporal variety for training)
- [ ] Dataiku Free Edition installed and connected to PostgreSQL
- [ ] FastAPI scorer deployed
- [ ] n8n workflow (cron → PostgreSQL → scorer → alert)
- [ ] Grafana dashboards
- [ ] Elasticsearch + Kibana
- [ ] NEXRAD replay mode (simulate live feed from local file)
- [ ] Model trained (LightGBM, Dataiku)
- [ ] Offline packaging

---

## Quick Start

### 1. Clone

```bash
git clone https://github.com/Adrien-1997/radar-echo-classifier.git
cd radar-echo-classifier
```

### 2. Start the stack

Start all services:
```bash
docker compose up -d
```

Or start a single service (e.g. PostgreSQL only):
```bash
docker compose up -d postgres
```

Stop everything (data is preserved in Docker volumes):
```bash
docker compose down
```

### 3. Bootstrap the database and load synthetic data

```bash
bash setup.sh
```

This will:
- Wait for PostgreSQL to be ready
- Create the schema (`sql/init_schema.sql`)
- Generate and insert 50 000 synthetic radar echoes (`generate_data.py`)

### 4. Open the tools

| URL | Credentials |
|-----|-------------|
| http://localhost:8888 | Jupyter Lab (no password) |
| http://localhost:3000 | Grafana (admin / admin) |
| http://localhost:5601 | Kibana |
| http://localhost:5678 | n8n (admin / admin) |
| http://localhost:8000/docs | FastAPI Swagger UI |
| http://localhost:9200 | Elasticsearch |

### 5. Score a single echo

```bash
curl -X POST http://localhost:8000/predict \
  -H "Content-Type: application/json" \
  -d '{"zh_dbz": 35, "zdr_db": 1.2, "kdp_deg_km": 0.4, "rhohv": 0.97, "phidp_deg": 45, "azimuth": 120, "elevation": 2.5, "range_km": 80}'
```

### 6. Connect to PostgreSQL directly

From WSL terminal (requires `psql`):
```bash
psql -h localhost -U radar -d radar_db
# password: radar
```

Via Docker (no client needed):
```bash
docker exec -it radar-echo-classifier-postgres-1 psql -U radar -d radar_db
```

From a GUI client (DBeaver, TablePlus, DataGrip):
- Host: `localhost`, Port: `5432`, DB: `radar_db`, User: `radar`, Password: `radar`

---

## Local Python Environment (without Docker)

```bash
conda env create -f environment.yml
conda activate radar-pipeline
```

---

## License

MIT — see [LICENSE](LICENSE).
