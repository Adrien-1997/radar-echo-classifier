"""
FastAPI scorer — serves rain/clutter predictions.

Loads a single sklearn Pipeline (PolarimetricEngineer → SimpleImputer → LightGBM) from clf.pkl.
The pipeline is produced by notebooks/02_train.ipynb and dropped in model/.
Feature engineering (azimuth → sin/cos, range_km → log1p) is baked into the pipeline.
"""

import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import joblib
import numpy as np
import psycopg2
import psycopg2.extras
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from feature_engineering import PolarimetricEngineer  # noqa: F401 — required for joblib deserialization
from nexrad_ingest import fetch_and_parse

# Raw features fed into the pipeline (PolarimetricEngineer handles transforms internally)
FEATURES = ["zh_dbz", "zdr_db", "rhohv", "azimuth", "range_km"]

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Radar Echo Scorer", version="0.4.0")

MODEL_DIR = Path(os.getenv("MODEL_DIR", "/model"))
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://radar:radar@postgres:5432/radar_db")
clf_path = MODEL_DIR / "clf.pkl"

model = None
if clf_path.exists():
    model = joblib.load(clf_path)
    logger.info("Model loaded from %s", clf_path)
else:
    logger.warning("Model not found at %s — /predict will return random scores.", clf_path)


class EchoInput(BaseModel):
    zh_dbz: Optional[float] = None
    zdr_db: Optional[float] = None
    rhohv: Optional[float] = None
    azimuth: float
    range_km: float
    # Legacy fields — accepted for backward compat but not used by the pipeline
    kdp_deg_km: Optional[float] = None
    phidp_deg: Optional[float] = None
    elevation: Optional[float] = None


class PredictionOutput(BaseModel):
    clutter_proba: float
    prediction: int


@app.get("/health")
def health():
    return {"status": "ok", "model_loaded": model is not None}


class LogRunParams(BaseModel):
    site: str = "KBRO"
    date: Optional[str] = None
    n_scored: int
    n_clutter: int
    clutter_rate: float


@app.post("/log_run", response_model=ScoreNexradResult if False else dict)
def log_run(params: LogRunParams):
    """
    Write a scoring run summary directly to radar_scoring_runs — no model, no NEXRAD fetch.
    Useful for testing the Grafana dashboard or replaying historical stats.
    """
    date = params.date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    run_id = str(uuid.uuid4())

    try:
        conn = psycopg2.connect(DATABASE_URL)
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO radar_scoring_runs
                    (run_id, site, scan_date, n_scored, n_clutter, clutter_rate)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (run_id, params.site, date, params.n_scored, params.n_clutter, params.clutter_rate),
            )
        conn.commit()
        conn.close()
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"DB write failed: {e}")

    logger.info("log_run run=%s site=%s clutter_rate=%.3f", run_id, params.site, params.clutter_rate)
    return {"run_id": run_id, "site": params.site, "date": date,
            "n_scored": params.n_scored, "n_clutter": params.n_clutter,
            "clutter_rate": params.clutter_rate}


class ScoreLatestParams(BaseModel):
    limit: int = 10000


class ScoreLatestResult(BaseModel):
    run_id: str
    n_scored: int
    n_clutter: int
    clutter_rate: float


@app.post("/score_latest", response_model=ScoreLatestResult)
def score_latest(params: ScoreLatestParams = ScoreLatestParams()):
    """
    Pull the most recent `limit` gates from radar_echoes, score them,
    write results to radar_predictions, and return clutter stats.
    """
    if model is None:
        raise HTTPException(status_code=503, detail="Model not loaded")

    run_id = str(uuid.uuid4())

    try:
        conn = psycopg2.connect(DATABASE_URL)
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"DB connection failed: {e}")

    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT id, zh_dbz, zdr_db, rhohv, azimuth, range_km
                FROM radar_echoes
                ORDER BY id DESC
                LIMIT %s
                """,
                (params.limit,),
            )
            rows = cur.fetchall()

        if not rows:
            conn.close()
            return ScoreLatestResult(run_id=run_id, n_scored=0, n_clutter=0, clutter_rate=0.0)

        X = np.array(
            [[r["zh_dbz"], r["zdr_db"], r["rhohv"], r["azimuth"], r["range_km"]]
             for r in rows],
            dtype=float,
        )
        probas = model.predict_proba(X)[:, 1]
        preds = (probas >= 0.5).astype(int)

        records = [
            (rows[i]["id"], float(probas[i]), int(preds[i]), run_id)
            for i in range(len(rows))
        ]

        with conn.cursor() as cur:
            psycopg2.extras.execute_values(
                cur,
                """
                INSERT INTO radar_predictions (echo_id, clutter_proba, prediction, run_id)
                VALUES %s
                ON CONFLICT DO NOTHING
                """,
                records,
            )
        conn.commit()
    finally:
        conn.close()

    n_clutter = int(preds.sum())
    clutter_rate = round(n_clutter / len(rows), 4)
    logger.info("run=%s scored=%d clutter_rate=%.3f", run_id, len(rows), clutter_rate)

    return ScoreLatestResult(
        run_id=run_id,
        n_scored=len(rows),
        n_clutter=n_clutter,
        clutter_rate=clutter_rate,
    )


class ScoreNexradParams(BaseModel):
    site: str = "KBRO"
    date: Optional[str] = None   # YYYY-MM-DD; defaults to today UTC
    scan_index: int = -1          # -1 = latest available scan


class ScoreNexradResult(BaseModel):
    run_id: str
    site: str
    date: str
    n_scored: int
    n_clutter: int
    clutter_rate: float


@app.post("/score_nexrad", response_model=ScoreNexradResult)
def score_nexrad(params: ScoreNexradParams = ScoreNexradParams()):
    """
    Fetch a live NEXRAD Level-III scan from Unidata THREDDS, score every gate,
    and return clutter stats. No database read or write — fully self-contained.
    """
    if model is None:
        raise HTTPException(status_code=503, detail="Model not loaded")

    date = params.date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    run_id = str(uuid.uuid4())

    try:
        df = fetch_and_parse(params.site, date, params.scan_index)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"NEXRAD fetch failed: {e}")

    if df.empty:
        return ScoreNexradResult(
            run_id=run_id, site=params.site, date=date,
            n_scored=0, n_clutter=0, clutter_rate=0.0,
        )

    X = df[FEATURES].to_numpy(dtype=float)
    probas = model.predict_proba(X)[:, 1]
    preds = (probas >= 0.5).astype(int)

    n_clutter = int(preds.sum())
    clutter_rate = round(n_clutter / len(df), 4)
    logger.info("run=%s site=%s date=%s scored=%d clutter_rate=%.3f",
                run_id, params.site, date, len(df), clutter_rate)

    return ScoreNexradResult(
        run_id=run_id,
        site=params.site,
        date=date,
        n_scored=len(df),
        n_clutter=n_clutter,
        clutter_rate=clutter_rate,
    )


@app.post("/predict", response_model=PredictionOutput)
def predict(echo: EchoInput):
    if model is None:
        import random
        clutter_proba = round(random.uniform(0, 1), 4)
    else:
        raw = np.array([[
            echo.zh_dbz,
            echo.zdr_db,
            echo.rhohv,
            echo.azimuth,
            echo.range_km,
        ]], dtype=float)  # NaN for None fields — pipeline imputer handles these
        clutter_proba = float(model.predict_proba(raw)[0, 1])

    prediction = int(clutter_proba >= 0.5)
    return PredictionOutput(clutter_proba=round(clutter_proba, 4), prediction=prediction)
