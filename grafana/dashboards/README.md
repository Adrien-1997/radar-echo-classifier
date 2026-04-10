# Grafana Dashboards

Access Grafana at **http://localhost:3000** (default credentials: `admin` / `admin`).

Connect Grafana to PostgreSQL as a data source:
- Host: `postgres:5432`
- Database: `radar_db`
- User: `radar`
- Password: `radar`
- SSL mode: disable

---

## Dashboards to build

### 1. Clutter Rate — Time Series

- Data source: PostgreSQL
- Query: rolling 1-hour clutter rate from `radar_predictions` joined with `radar_echoes`
- Panel type: Time series
- Alert threshold line at 40%
- Useful for monitoring drift in clutter prevalence over time

### 2. Rolling AUC

- Data source: PostgreSQL
- Query: compute AUC per `run_id` using a stored procedure or pre-aggregated table
- Panel type: Stat / Time series
- Requires a ground-truth label comparison — link `radar_predictions.echo_id` back to `radar_echoes.label`

### 3. Azimuth / Elevation Heatmap

- Data source: PostgreSQL
- Query: average `clutter_proba` grouped by azimuth bin (5°) and elevation bin (1°)
- Panel type: Heatmap
- Reveals spatial patterns of clutter (e.g., ground clutter near 0° elevation)

### 4. Pipeline Latency

- Data source: PostgreSQL
- Query: `predicted_at - timestamp` per prediction as pipeline latency
- Panel type: Histogram or Time series
- Useful for detecting slowdowns in the scoring pipeline

---

## Tips

- Save dashboard JSON exports to this folder for version control
- Use Grafana provisioning (`grafana/provisioning/`) to load dashboards automatically on startup
- Tag dashboards with `radar` and `clutter` for easy filtering
