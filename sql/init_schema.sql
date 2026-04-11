-- Radar echo classifier — database schema

CREATE TABLE IF NOT EXISTS radar_echoes (
    id          SERIAL PRIMARY KEY,
    timestamp   TIMESTAMPTZ NOT NULL,
    azimuth     FLOAT NOT NULL,
    elevation   FLOAT NOT NULL,
    range_km    FLOAT NOT NULL,
    zh_dbz      FLOAT,
    zdr_db      FLOAT,
    kdp_deg_km  FLOAT,
    rhohv       FLOAT,
    phidp_deg   FLOAT,
    label       INT NOT NULL
);

CREATE TABLE IF NOT EXISTS radar_features (
    id              SERIAL PRIMARY KEY,
    timestamp       TIMESTAMPTZ NOT NULL,
    azimuth         FLOAT NOT NULL,
    elevation       FLOAT NOT NULL,
    range_km        FLOAT NOT NULL,
    zh_dbz          FLOAT NOT NULL,
    zdr_db          FLOAT,
    kdp_deg_km      FLOAT,
    rhohv           FLOAT NOT NULL,
    phidp_deg       FLOAT,
    label           INT NOT NULL,
    ratio_zh_zdr    FLOAT,
    rhohv_flag      INT,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS radar_predictions (
    id              SERIAL PRIMARY KEY,
    echo_id         INT REFERENCES radar_echoes(id),
    clutter_proba   FLOAT NOT NULL,
    prediction      INT NOT NULL,
    run_id          UUID NOT NULL,
    predicted_at    TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_echoes_timestamp   ON radar_echoes(timestamp);
CREATE INDEX IF NOT EXISTS idx_features_timestamp ON radar_features(timestamp);
CREATE INDEX IF NOT EXISTS idx_preds_echo_id      ON radar_predictions(echo_id);
CREATE INDEX IF NOT EXISTS idx_preds_run_id       ON radar_predictions(run_id);
