"""
FastAPI scorer — serves rain/clutter predictions.
"""

import logging
import random
from pathlib import Path

import joblib
import numpy as np
from fastapi import FastAPI
from pydantic import BaseModel

MODEL_PATH = Path("model.pkl")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Radar Echo Scorer", version="0.1.0")

# Load model once at startup if available
model = None
if MODEL_PATH.exists():
    model = joblib.load(MODEL_PATH)
    logger.info("Model loaded from %s", MODEL_PATH)
else:
    logger.warning("model.pkl not found — /predict will return random scores.")


class EchoInput(BaseModel):
    zh_dbz: float
    zdr_db: float
    kdp_deg_km: float
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
    return {"status": "ok"}


@app.post("/predict", response_model=PredictionOutput)
def predict(echo: EchoInput):
    if model is None:
        clutter_proba = round(random.uniform(0, 1), 4)
    else:
        features = np.array(
            [[
                echo.zh_dbz,
                echo.zdr_db,
                echo.kdp_deg_km,
                echo.rhohv,
                echo.phidp_deg,
                echo.azimuth,
                echo.elevation,
                echo.range_km,
            ]]
        )
        clutter_proba = float(model.predict_proba(features)[0, 1])

    prediction = int(clutter_proba >= 0.5)
    return PredictionOutput(clutter_proba=round(clutter_proba, 4), prediction=prediction)
