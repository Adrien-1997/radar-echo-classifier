# radar-echo-classifier

End-to-end ML pipeline for meteorological radar echo classification (rain vs clutter). Stack: Python, PostgreSQL, Dataiku, Grafana, Kibana, Elasticsearch, n8n, FastAPI, Jupyter.

This is a data science side project that explores how to build a production-grade classification pipeline on polarimetric weather radar data, from raw echo ingestion to automated alerting.

---

## Overview

Weather radars return echoes from both precipitation and non-meteorological sources (ground clutter, insects, aircraft, etc.). This project builds a full ML pipeline to classify each radar gate as **rain** or **clutter** using dual-polarization variables, and wraps it in a modern data platform stack.

---

## Stack

| Component | Role |
|-----------|------|
| **PostgreSQL 15** | Store raw radar echoes, engineered features, and model predictions |
| **Elasticsearch 8** | Index predictions and logs for full-text search and analytics |
| **Kibana 8** | Explore and visualize Elasticsearch indices |
| **Grafana** | Real-time dashboards: clutter rate, rolling AUC, latency |
| **n8n** | Workflow automation: cron scoring, alerting when clutter rate > 40% |
| **Jupyter (scipy-notebook)** | EDA, feature engineering, model training, SHAP explainability |
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
| 8888 | Jupyter Lab |
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

| Component | Status |
|-----------|--------|
| docker-compose | done — `version` field removed (obsolete) |
| PostgreSQL | running and healthy on `localhost:5432` |
| FastAPI scorer | built, not yet started |
| Grafana | not yet started |
| n8n | not yet started |
| Elasticsearch + Kibana | not yet started |
| Jupyter | not yet started |
| DB schema | not yet applied |
| Synthetic data | not yet loaded |
| Model training | not yet done |

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
