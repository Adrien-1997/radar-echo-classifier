"""
Generate synthetic polarimetric radar echo data and insert into PostgreSQL.
50 000 rows covering a range of rain and clutter signatures.
"""

import os
import numpy as np
import pandas as pd
from sqlalchemy import create_engine, text

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://radar:radar@localhost:5432/radar_db",
)

N_ROWS = 50_000
RANDOM_SEED = 42

rng = np.random.default_rng(RANDOM_SEED)

timestamps = pd.date_range("2024-01-01", periods=N_ROWS, freq="1min")

azimuth = rng.uniform(0, 360, N_ROWS)
elevation = rng.uniform(0, 15, N_ROWS)
range_km = rng.exponential(scale=50, size=N_ROWS)
zh_dbz = rng.normal(30, 15, N_ROWS)
zdr_db = rng.normal(1.5, 1.2, N_ROWS)
kdp_deg_km = rng.normal(0.5, 0.8, N_ROWS)
rhohv = np.clip(rng.normal(0.95, 0.05, N_ROWS), 0, 1)
phidp_deg = rng.uniform(0, 180, N_ROWS)

label = np.where(
    (rhohv < 0.85) | ((zh_dbz > 45) & (zdr_db < 0)),
    1,
    0,
)

df = pd.DataFrame(
    {
        "timestamp": timestamps,
        "azimuth": azimuth,
        "elevation": elevation,
        "range_km": range_km,
        "zh_dbz": zh_dbz,
        "zdr_db": zdr_db,
        "kdp_deg_km": kdp_deg_km,
        "rhohv": rhohv,
        "phidp_deg": phidp_deg,
        "label": label.astype(int),
    }
)

print(f"Generated {len(df)} rows — clutter rate: {label.mean():.2%}")

engine = create_engine(DATABASE_URL)
with engine.begin() as conn:
    df.to_sql(
        "radar_echoes",
        conn,
        if_exists="append",
        index=False,
        method="multi",
        chunksize=1000,
    )

print("Data inserted into radar_echoes successfully.")