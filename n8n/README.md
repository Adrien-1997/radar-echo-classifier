# n8n Workflow — Live NEXRAD Scoring and Alerting

Access n8n at **http://localhost:5678** (credentials: `admin` / `admin`).

Import the workflow: **Workflows → Import from file → `n8n/workflow_score_latest.json`**

---

## Workflow: Radar Live Scoring

```
Manual Trigger
  → Parameters (site, scan_index)
  → Score Nexrad  ──┬──→ Log Run          (writes to radar_scoring_runs → Grafana)
                    └──→ Clutter > 40%?
                              yes → Alert → Grafana Annotation (red marker on dashboard)
                              no  → OK
```

### Nodes

| Node | Type | Description |
|------|------|-------------|
| **Manual Trigger** | Trigger | Starts the workflow on demand |
| **Parameters** | Set | Defines `site` (default: `KBRO`) and `scan_index` (default: `-1` = latest) |
| **Score Nexrad** | HTTP POST | `POST scorer:8000/score_nexrad` — fetches live scan from Unidata THREDDS, scores all gates in memory, returns `clutter_rate`, `n_clutter`, `n_scored`, `site`, `date` |
| **Log Run** | HTTP POST | `POST scorer:8000/log_run` — persists the run summary to `radar_scoring_runs` (feeds Grafana dashboard) |
| **Clutter > 40%?** | If | Branches on `clutter_rate > 0.4` |
| **Alert** | Set | Formats the alert message with site, date, clutter % and gate counts |
| **Grafana Annotation** | HTTP POST | `POST grafana:3000/api/annotations` — places a red vertical marker on the Grafana dashboard |
| **OK** | Set | Formats a normal status message (no further action) |

### Configurable parameters

Edit the **Parameters** node to change:
- `site` — 4-letter ICAO radar code (e.g. `KBRO`, `KTLX`, `KAMX`, `KPBZ`)
- `scan_index` — `-1` for the latest scan of the day, `0` for the first

---

## Scorer endpoints used

| Endpoint | Purpose |
|----------|---------|
| `POST /score_nexrad` | Fetch + score a live NEXRAD scan (no DB read required) |
| `POST /log_run` | Write a run summary row to `radar_scoring_runs` |

See `scorer/main.py` or http://localhost:8000/docs for the full API.
