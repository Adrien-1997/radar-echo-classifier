"""
FastAPI scorer — serves rain/clutter predictions.

Loads model and rescalers from the Dataiku saved model directory,
configured via DSS_MODEL_DIR environment variable.
"""

import json
import logging
import os
import random
from pathlib import Path

import joblib
import numpy as np
from fastapi import FastAPI
from pydantic import BaseModel

# Feature order must match Dataiku training order
FEATURES = ["elevation", "zdr_db", "rhohv", "phidp_deg", "range_km", "azimuth", "zh_dbz"]

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Radar Echo Scorer", version="0.2.0")

# Load model and rescalers from DSS saved model directory
DSS_MODEL_DIR = Path(os.getenv(
    "DSS_MODEL_DIR",
    "/dss_model",  # default mount point in container
))

model = None
shifts = None
inv_scales = None

clf_path = DSS_MODEL_DIR / "clf.pkl"
rescalers_path = DSS_MODEL_DIR / "rescalers.json"

if clf_path.exists() and rescalers_path.exists():
    model = joblib.load(clf_path)
    with open(rescalers_path) as f:
        r = json.load(f)
    shifts = np.array(r["shifts"])
    inv_scales = np.array(r["inv_scales"])
    logger.info("Model loaded from %s", DSS_MODEL_DIR)
else:
    logger.warning("Model not found at %s — /predict will return random scores.", DSS_MODEL_DIR)


class EchoInput(BaseModel):
    zh_dbz: float
    zdr_db: float
    rhohv: float
    phidp_deg: float
    azimuth: float
    elevation: float
    range_km: float


class PredictionOutput(BaseModel):
    clutter_proba: float
    prediction: int


@app.get("/health")
def health():
    return {"status": "ok", "model_loaded": model is not None}


@app.post("/predict", response_model=PredictionOutput)
def predict(echo: EchoInput):
    if model is None:
        clutter_proba = round(random.uniform(0, 1), 4)
    else:
        raw = np.array([[
            echo.elevation,
            echo.zdr_db,
            echo.rhohv,
            echo.phidp_deg,
            echo.range_km,
            echo.azimuth,
            echo.zh_dbz,
        ]])
        scaled = (raw - shifts) * inv_scales
        clutter_proba = float(model.predict_proba(scaled)[0, 1])

    prediction = int(clutter_proba >= 0.5)
    return PredictionOutput(clutter_proba=round(clutter_proba, 4), prediction=prediction)
