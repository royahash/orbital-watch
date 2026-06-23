import numpy as np
import pytest
from anomaly_detector import extract_features, detect_anomalies, summarize_anomalies


def _make_series(n=50, alt=420.0, speed=7.66):
    """Generate a uniform time-series for testing."""
    return [
        {
            "timestamp": f"2026-06-21T{i:02d}:00:00+00:00",
            "alt_km": alt + np.random.normal(0, 0.1),
            "speed_km_s": speed + np.random.normal(0, 0.001),
            "lat": 0.0,
            "lon": 0.0,
        }
        for i in range(n)
    ]


class TestExtractFeatures:
    def test_output_shape(self):
        series = _make_series(30)
        X = extract_features(series)
        assert X.shape == (30, 4)

    def test_columns_are_alt_speed_deltas(self):
        series = _make_series(10)
        X = extract_features(series)
        # First column should be altitudes
        for i, pt in enumerate(series):
            assert abs(X[i, 0] - pt["alt_km"]) < 1e-6
        # Second column should be speeds
        for i, pt in enumerate(series):
            assert abs(X[i, 1] - pt["speed_km_s"]) < 1e-6

    def test_first_delta_is_zero(self):
        series = _make_series(10)
        X = extract_features(series)
        assert X[0, 2] == 0.0  # alt change
        assert X[0, 3] == 0.0  # speed change


class TestDetectAnomalies:
    def test_preserves_original_fields(self):
        series = _make_series(30)
        result = detect_anomalies(series)
        for r in result:
            assert "alt_km" in r
            assert "speed_km_s" in r
            assert "timestamp" in r

    def test_adds_anomaly_fields(self):
        series = _make_series(30)
        result = detect_anomalies(series)
        for r in result:
            assert "anomaly" in r
            assert isinstance(r["anomaly"], bool)
            assert "anomaly_score" in r
            assert isinstance(r["anomaly_score"], float)

    def test_short_series_no_anomalies(self):
        series = _make_series(5)
        result = detect_anomalies(series)
        for r in result:
            assert r["anomaly"] is False
            assert r["anomaly_score"] == 0.0

    def test_injected_outlier_detected(self):
        np.random.seed(42)
        series = _make_series(100)
        # Inject a dramatic outlier
        series[50]["alt_km"] = 200.0
        series[50]["speed_km_s"] = 12.0
        result = detect_anomalies(series, contamination=0.05)
        assert result[50]["anomaly"] is True

    def test_output_length_matches_input(self):
        series = _make_series(40)
        result = detect_anomalies(series)
        assert len(result) == 40


class TestSummarizeAnomalies:
    def test_nominal_when_no_anomalies(self):
        series = [{"anomaly": False, "anomaly_score": 0.1} for _ in range(20)]
        summary = summarize_anomalies(series)
        assert summary["status"] == "nominal"
        assert summary["anomaly_count"] == 0

    def test_watch_for_few_minor_anomalies(self):
        series = [{"anomaly": False, "anomaly_score": 0.1} for _ in range(20)]
        series[5] = {"anomaly": True, "anomaly_score": -0.2}
        series[10] = {"anomaly": True, "anomaly_score": -0.25}
        summary = summarize_anomalies(series)
        assert summary["status"] == "watch"
        assert summary["anomaly_count"] == 2

    def test_alert_for_many_anomalies(self):
        series = [{"anomaly": False, "anomaly_score": 0.1} for _ in range(20)]
        for i in range(5):
            series[i] = {"anomaly": True, "anomaly_score": -0.4}
        summary = summarize_anomalies(series)
        assert summary["status"] == "alert"
        assert summary["anomaly_count"] == 5

    def test_alert_for_severe_anomaly(self):
        series = [{"anomaly": False, "anomaly_score": 0.1} for _ in range(20)]
        series[0] = {"anomaly": True, "anomaly_score": -0.5}
        summary = summarize_anomalies(series)
        assert summary["status"] == "alert"

    def test_summary_has_required_fields(self):
        series = [{"anomaly": True, "anomaly_score": -0.3}]
        summary = summarize_anomalies(series)
        assert "status" in summary
        assert "anomaly_count" in summary
        assert "worst_score" in summary
        assert "message" in summary
