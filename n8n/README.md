# n8n Workflow — Automated Scoring and Alerting

Access n8n at **http://localhost:5678** (credentials: `admin` / `admin`).

## Workflow to build

### Trigger: Cron

- Schedule: every 15 minutes (or configurable)
- Kicks off the scoring pipeline for the most recent radar echoes

### Step 1 — Query PostgreSQL

- Node type: **Postgres**
- Query: fetch the last N radar echoes from `radar_echoes` that have not yet been scored (left join on `radar_predictions`)
- Output: list of echo rows with polarimetric features

### Step 2 — HTTP Request to FastAPI scorer

- Node type: **HTTP Request**
- Method: POST
- URL: `http://scorer:8000/predict`
- Body: one echo at a time (or batch with a loop node)
- Output: `clutter_proba`, `prediction`

### Step 3 — Write predictions back to PostgreSQL

- Node type: **Postgres**
- Insert each prediction into `radar_predictions` with the corresponding `echo_id` and a generated `run_id` (UUID)

### Step 4 — Compute run clutter rate

- Node type: **Function** (JavaScript)
- Calculate `clutter_rate = count(prediction == 1) / total`

### Step 5 — IF condition

- Node type: **IF**
- Condition: `clutter_rate > 0.4`

### Step 6a — Alert (clutter rate high)

- Node type: **Slack** / **Email** / **Webhook** (choose your preferred channel)
- Message: `[radar-echo-classifier] High clutter rate detected: {{ clutter_rate }} for run {{ run_id }}`

### Step 6b — No alert (clutter rate normal)

- Node type: **NoOp** or log to a monitoring endpoint

---

## Tips

- Export completed workflows to `n8n/` as JSON for version control
- Use the n8n environment variables in docker-compose to persist credentials
- The `scorer` service is reachable inside the Docker network as `http://scorer:8000`
