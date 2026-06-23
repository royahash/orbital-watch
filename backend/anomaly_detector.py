"""
anomaly_detector.py
-------------------
Detects unusual orbital behavior using Isolation Forest.

Why Isolation Forest?
  Unlike regression models, Isolation Forest doesn't need labeled examples
  of "bad" satellite behavior (which are rare and hard to collect).
  Instead, it learns what "normal" looks like and flags anything that's
  an outlier — an "anomaly."

  It works by randomly partitioning data. Points that are easy to isolate
  (require fewer random splits to separate from the rest) are anomalies.
  This is perfect for orbital data: normal satellites behave predictably,
  so truly abnormal readings stand out quickly.

What we flag:
  - Sudden altitude drops (reentry risk, propulsion issue)
  - Unusual speed changes (maneuver or collision avoidance)
  - Rapid inclination drift (rare, might indicate attitude control issue)

In a real mission ops center, this module would feed into a pager alert.
For the portfolio, it feeds a red/yellow/green status indicator on the dashboard.
"""

import numpy as np
from sklearn.ensemble import IsolationForest
from typing import List, Dict, Tuple


def extract_features(series: List[Dict]) -> np.ndarray:
    """
    Converts a time-series list of orbital readings into a NumPy feature matrix.

    Features per time step:
      [altitude_km, speed_km_s, altitude_change, speed_change]

    We compute first-order differences (changes) because anomalies often
    show up as sudden *changes*, not just unusual absolute values.
    """
    alts = np.array([pt["alt_km"] for pt in series])
    speeds = np.array([pt["speed_km_s"] for pt in series])

    # Pad changes so array length matches (first difference is always 0)
    alt_changes = np.diff(alts, prepend=alts[0])
    speed_changes = np.diff(speeds, prepend=speeds[0])

    return np.column_stack([alts, speeds, alt_changes, speed_changes])


def detect_anomalies(series: List[Dict], contamination: float = 0.05) -> List[Dict]:
    """
    Runs Isolation Forest on the time-series data.

    Parameters:
      series: list of dicts from orbital_math.compute_altitude_series()
      contamination: expected fraction of anomalous points (5% default).
        In practice, tune this based on your satellite's historical behavior.

    Returns the series with an added "anomaly" boolean and "anomaly_score" field.
    The score ranges from -0.5 (very anomalous) to 0.5 (very normal).
    Cesium/D3 will color-code these points on the dashboard.
    """
    if len(series) < 10:
        # Not enough data to train a meaningful model
        return [{**pt, "anomaly": False, "anomaly_score": 0.0} for pt in series]

    X = extract_features(series)

    model = IsolationForest(
        n_estimators=100,      # number of isolation trees (more = more stable)
        contamination=contamination,
        random_state=42,       # reproducible results
    )
    model.fit(X)

    # predict() returns 1 (normal) or -1 (anomaly)
    labels = model.predict(X)
    scores = model.score_samples(X)  # raw anomaly scores

    result = []
    for i, pt in enumerate(series):
        result.append({
            **pt,
            "anomaly": bool(labels[i] == -1),
            "anomaly_score": round(float(scores[i]), 4),
        })

    return result


def summarize_anomalies(analyzed_series: List[Dict]) -> Dict:
    """
    Produces a summary dict for the dashboard status indicator.

    Returns:
      status: "nominal" | "watch" | "alert"
      anomaly_count: how many flagged points
      worst_score: the most anomalous score seen
      message: human-readable explanation
    """
    anomalies = [pt for pt in analyzed_series if pt.get("anomaly")]
    count = len(anomalies)

    if count == 0:
        return {
            "status": "nominal",
            "anomaly_count": 0,
            "worst_score": None,
            "message": "All orbital parameters within expected bounds.",
        }

    worst_score = min(pt["anomaly_score"] for pt in anomalies)

    if count <= 3 and worst_score > -0.3:
        status = "watch"
        message = f"{count} minor anomalous reading(s) detected. Monitoring."
    else:
        status = "alert"
        message = f"{count} anomalous readings detected. Worst score: {worst_score:.3f}. Manual review recommended."

    return {
        "status": status,
        "anomaly_count": count,
        "worst_score": round(worst_score, 4),
        "message": message,
    }
