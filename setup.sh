#!/usr/bin/env bash
set -euo pipefail

PGHOST="${PGHOST:-localhost}"
PGPORT="${PGPORT:-5432}"
PGUSER="${PGUSER:-radar}"
PGPASSWORD="${PGPASSWORD:-radar}"
PGDATABASE="${PGDATABASE:-radar_db}"

export PGPASSWORD

echo "Waiting for PostgreSQL to be ready..."
until pg_isready -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$PGDATABASE" > /dev/null 2>&1; do
  echo "  PostgreSQL not ready yet — retrying in 2s..."
  sleep 2
done
echo "PostgreSQL is ready."

echo "Running schema init..."
psql -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$PGDATABASE" -f sql/init_schema.sql
echo "Schema created."

echo "Generating and loading synthetic data..."
python generate_data.py
echo "Data loaded."

echo ""
echo "Setup complete. Stack is ready."
echo "  Jupyter : http://localhost:8888"
echo "  Grafana : http://localhost:3000"
echo "  Kibana  : http://localhost:5601"
echo "  n8n     : http://localhost:5678"
echo "  Scorer  : http://localhost:8000/docs"
