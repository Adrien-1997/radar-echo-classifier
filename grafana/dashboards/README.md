# Grafana Dashboards

Access Grafana at **http://localhost:3000** (credentials: `admin` / `admin`).

The datasource and dashboards are **auto-provisioned** on startup from `grafana/provisioning/` — no manual setup needed.

---

## Radar Clutter Monitor

Dashboard file: `grafana/dashboards/clutter_monitor.json`

### Panels

| Panel | Type | Description |
|-------|------|-------------|
| **Clutter Rate Over Time** | Time series | `clutter_rate` per run over the last 24h — red threshold line at 40% |
| **Last Clutter Rate** | Stat | Most recent clutter rate — green/red background |
| **Last Site** | Stat | ICAO code of the last scored site |
| **Runs (last 24h)** | Stat | Total number of scoring runs in the last 24 hours |
| **Alerts Today** | Stat | Runs where `clutter_rate > 0.4` in the last 24 hours |
| **Recent Runs** | Table | Last 20 runs with site, scan date, clutter %, gate counts — color-coded |

All panels query `radar_scoring_runs` (one row per n8n workflow execution).

### Annotations

Red vertical markers appear on the time series when n8n detects clutter and posts to `POST grafana:3000/api/annotations` with tags `["clutter", "alert", "<site>"]`.

---

## Provisioning

| File | Purpose |
|------|---------|
| `grafana/provisioning/datasources/postgres.yaml` | Configures the `RadarDB` PostgreSQL datasource |
| `grafana/provisioning/dashboards/provider.yaml` | Tells Grafana to load dashboards from `/var/lib/grafana/dashboards` |

Both are mounted read-only in `docker-compose.yml`.
