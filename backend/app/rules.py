import numpy as np
import pandas as pd

from .config import TEMP_MAX, TEMP_MIN


def apply_rules(df, faults):
    pm, t, rh = df["pm25"].to_numpy(), df["temp"].to_numpy(), df["rh"].to_numpy()
    missing = np.isnan(pm) | np.isnan(t) | np.isnan(rh)
    conds = [
        missing,
        (t >= TEMP_MAX) | (t <= TEMP_MIN),
        (rh < 0) | (rh > 100),
        np.isclose(pm, faults["sentinel"], atol=0.005),
        pm >= faults["sat_floor"],
    ]
    names = ["dropout", "impossible_temp", "rh_fault", "stuck", "saturation"]
    return pd.Series(np.select(conds, names, default=""), index=df.index)
