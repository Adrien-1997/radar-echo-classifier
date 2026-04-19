import numpy as np
from sklearn.base import BaseEstimator, TransformerMixin


class PolarimetricEngineer(BaseEstimator, TransformerMixin):
    """Feature transforms for polarimetric radar data.

    Input column order:  [zh_dbz, zdr_db, rhohv, azimuth, range_km]
    Output column order: [zh_dbz, zdr_db, rhohv, sin_azimuth, cos_azimuth, log_range_km]

    azimuth  → sin + cos  (circular encoding — 0° and 360° are neighbours)
    range_km → log1p      (right-skewed: median ~33 km, max ~300 km)
    """

    def fit(self, X, y=None):
        return self

    def transform(self, X):
        X = np.asarray(X, dtype=float)
        az_rad = np.deg2rad(X[:, 3])
        return np.column_stack([
            X[:, 0],            # zh_dbz
            X[:, 1],            # zdr_db
            X[:, 2],            # rhohv
            np.sin(az_rad),     # sin_azimuth
            np.cos(az_rad),     # cos_azimuth
            np.log1p(X[:, 4]), # log_range_km
        ])
