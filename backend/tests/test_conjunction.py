import pytest
from datetime import datetime, timezone
from conjunction import (
    compute_distance_at_time, find_closest_approach,
    classify_severity, screen_conjunctions,
)
from orbital_math import build_satellite
from tests.conftest import (
    ISS_TLE1, ISS_TLE2, CSS_TLE1, CSS_TLE2,
    FREGAT_TLE1, FREGAT_TLE2, REFERENCE_TIME,
)


class TestComputeDistanceAtTime:
    def test_same_satellite_distance_zero(self, iss_sat, ref_time):
        dist = compute_distance_at_time(iss_sat, iss_sat, ref_time)
        assert dist == 0.0

    def test_different_orbits_positive_distance(self, iss_sat, css_sat, ref_time):
        dist = compute_distance_at_time(iss_sat, css_sat, ref_time)
        assert dist > 0

    def test_distant_orbits_large_distance(self, iss_sat, fregat_sat, ref_time):
        dist = compute_distance_at_time(iss_sat, fregat_sat, ref_time)
        # ISS LEO vs FREGAT eccentric orbit — should be far apart (usually)
        assert dist > 10


class TestFindClosestApproach:
    def test_returns_valid_structure(self, iss_sat, css_sat, ref_time):
        result = find_closest_approach(iss_sat, css_sat, ref_time, hours=1.0)
        assert "tca" in result
        assert "dca_km" in result
        assert "sat1_position" in result
        assert "sat2_position" in result

    def test_dca_is_non_negative(self, iss_sat, css_sat, ref_time):
        result = find_closest_approach(iss_sat, css_sat, ref_time, hours=1.0)
        assert result["dca_km"] >= 0

    def test_positions_have_geodetic_fields(self, iss_sat, css_sat, ref_time):
        result = find_closest_approach(iss_sat, css_sat, ref_time, hours=1.0)
        for pos in [result["sat1_position"], result["sat2_position"]]:
            assert "lat" in pos
            assert "lon" in pos
            assert "alt_km" in pos

    def test_same_satellite_dca_zero(self, iss_sat, ref_time):
        result = find_closest_approach(iss_sat, iss_sat, ref_time, hours=1.0)
        assert result["dca_km"] < 0.01


class TestClassifySeverity:
    def test_critical(self):
        assert classify_severity(0.5) == "critical"

    def test_critical_boundary(self):
        assert classify_severity(0.99) == "critical"

    def test_warning(self):
        assert classify_severity(3.0) == "warning"

    def test_warning_boundary(self):
        assert classify_severity(1.0) == "warning"

    def test_caution(self):
        assert classify_severity(15.0) == "caution"

    def test_caution_boundary(self):
        assert classify_severity(5.0) == "caution"


class TestScreenConjunctions:
    def test_results_sorted_by_dca(self):
        satellites = [
            {"OBJECT_NAME": "SAT-A", "NORAD_CAT_ID": "1", "TLE_LINE1": ISS_TLE1, "TLE_LINE2": ISS_TLE2},
            {"OBJECT_NAME": "SAT-B", "NORAD_CAT_ID": "2", "TLE_LINE1": CSS_TLE1, "TLE_LINE2": CSS_TLE2},
        ]
        results = screen_conjunctions(satellites, threshold_km=50000, hours=1.0)
        for i in range(len(results) - 1):
            assert results[i]["dca_km"] <= results[i + 1]["dca_km"]

    def test_respects_threshold(self):
        satellites = [
            {"OBJECT_NAME": "ISS", "NORAD_CAT_ID": "25544", "TLE_LINE1": ISS_TLE1, "TLE_LINE2": ISS_TLE2},
            {"OBJECT_NAME": "FREGAT", "NORAD_CAT_ID": "49271", "TLE_LINE1": FREGAT_TLE1, "TLE_LINE2": FREGAT_TLE2},
        ]
        results = screen_conjunctions(satellites, threshold_km=1.0, hours=1.0)
        for r in results:
            assert r["dca_km"] <= 1.0

    def test_empty_input_returns_empty(self):
        assert screen_conjunctions([], threshold_km=25) == []

    def test_single_satellite_returns_empty(self):
        satellites = [
            {"OBJECT_NAME": "ISS", "NORAD_CAT_ID": "25544", "TLE_LINE1": ISS_TLE1, "TLE_LINE2": ISS_TLE2},
        ]
        assert screen_conjunctions(satellites, threshold_km=25, hours=1.0) == []

    def test_result_has_required_fields(self):
        satellites = [
            {"OBJECT_NAME": "SAT-A", "NORAD_CAT_ID": "1", "TLE_LINE1": ISS_TLE1, "TLE_LINE2": ISS_TLE2},
            {"OBJECT_NAME": "SAT-B", "NORAD_CAT_ID": "2", "TLE_LINE1": ISS_TLE1, "TLE_LINE2": ISS_TLE2},
        ]
        results = screen_conjunctions(satellites, threshold_km=50000, hours=1.0)
        assert len(results) > 0
        r = results[0]
        assert "sat1_name" in r
        assert "sat2_name" in r
        assert "tca" in r
        assert "dca_km" in r
        assert "severity" in r
