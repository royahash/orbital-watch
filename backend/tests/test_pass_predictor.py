import math
import pytest
from datetime import datetime, timezone
from pass_predictor import (
    geodetic_to_ecef, compute_look_angle, find_passes,
    predict_passes_for_group,
)
from orbital_math import WGS84_A, WGS84_B, eci_to_ecef, propagate_to_time
from tests.conftest import ISS_TLE1, ISS_TLE2, REFERENCE_TIME


class TestGeodeticToEcef:
    def test_equator_prime_meridian(self):
        ecef = geodetic_to_ecef(0, 0, 0)
        assert abs(ecef[0] - WGS84_A) < 0.01
        assert abs(ecef[1]) < 0.01
        assert abs(ecef[2]) < 0.01

    def test_north_pole(self):
        ecef = geodetic_to_ecef(90, 0, 0)
        assert abs(ecef[0]) < 0.01
        assert abs(ecef[1]) < 0.01
        assert abs(ecef[2] - WGS84_B) < 0.01

    def test_south_pole(self):
        ecef = geodetic_to_ecef(-90, 0, 0)
        assert abs(ecef[0]) < 0.01
        assert abs(ecef[1]) < 0.01
        assert abs(ecef[2] + WGS84_B) < 0.01

    def test_altitude_increases_magnitude(self):
        low = geodetic_to_ecef(0, 0, 0)
        high = geodetic_to_ecef(0, 0, 100)
        mag_low = math.sqrt(sum(x**2 for x in low))
        mag_high = math.sqrt(sum(x**2 for x in high))
        assert mag_high > mag_low
        assert abs((mag_high - mag_low) - 100) < 1


class TestComputeLookAngle:
    def test_directly_overhead_high_elevation(self):
        station_ecef = geodetic_to_ecef(0, 0, 0)
        # Satellite directly above at 400km
        sat_ecef = geodetic_to_ecef(0, 0, 400)
        look = compute_look_angle(station_ecef, 0.0, 0.0, sat_ecef)
        assert look["elevation_deg"] > 85

    def test_far_away_negative_elevation(self):
        station_ecef = geodetic_to_ecef(0, 0, 0)
        # Satellite on opposite side of Earth
        sat_ecef = geodetic_to_ecef(0, 180, 400)
        look = compute_look_angle(station_ecef, 0.0, 0.0, sat_ecef)
        assert look["elevation_deg"] < 0

    def test_range_is_positive(self):
        station_ecef = geodetic_to_ecef(34, -118, 0)
        sat_ecef = geodetic_to_ecef(35, -117, 400)
        look = compute_look_angle(
            station_ecef, math.radians(34), math.radians(-118), sat_ecef
        )
        assert look["range_km"] > 0

    def test_azimuth_in_range(self):
        station_ecef = geodetic_to_ecef(34, -118, 0)
        sat_ecef = geodetic_to_ecef(35, -117, 400)
        look = compute_look_angle(
            station_ecef, math.radians(34), math.radians(-118), sat_ecef
        )
        assert 0 <= look["azimuth_deg"] < 360


class TestFindPasses:
    def test_iss_has_passes_from_mid_latitude(self, iss_sat):
        # LA (34°N) — ISS at 51.6° inclination should be visible
        passes = find_passes(iss_sat, 34.05, -118.24, hours=24.0, min_elevation_deg=5.0)
        assert len(passes) > 0

    def test_pass_has_required_fields(self, iss_sat):
        passes = find_passes(iss_sat, 34.05, -118.24, hours=24.0)
        if passes:
            p = passes[0]
            assert "aos" in p
            assert "los" in p
            assert "duration_seconds" in p
            assert "max_elevation_deg" in p
            assert "ground_track" in p

    def test_aos_before_los(self, iss_sat):
        passes = find_passes(iss_sat, 34.05, -118.24, hours=24.0)
        for p in passes:
            assert p["aos"] < p["los"]

    def test_duration_is_reasonable(self, iss_sat):
        passes = find_passes(iss_sat, 34.05, -118.24, hours=24.0)
        for p in passes:
            # ISS pass: typically 1-10 minutes
            assert 30 < p["duration_seconds"] < 900

    def test_max_elevation_above_minimum(self, iss_sat):
        min_el = 10.0
        passes = find_passes(iss_sat, 34.05, -118.24, hours=24.0, min_elevation_deg=min_el)
        for p in passes:
            assert p["max_elevation_deg"] >= min_el

    def test_no_passes_from_extreme_latitude(self, iss_sat):
        # ISS at 51.6° inclination can't be seen from 80°N with 10° min elevation
        passes = find_passes(iss_sat, 80.0, 0.0, hours=12.0, min_elevation_deg=10.0)
        assert len(passes) == 0

    def test_ground_track_is_populated(self, iss_sat):
        passes = find_passes(iss_sat, 34.05, -118.24, hours=24.0)
        if passes:
            assert len(passes[0]["ground_track"]) > 0


class TestPredictPassesForGroup:
    def test_results_sorted_by_aos(self):
        satellites = [
            {"OBJECT_NAME": "ISS", "NORAD_CAT_ID": "25544",
             "TLE_LINE1": ISS_TLE1, "TLE_LINE2": ISS_TLE2, "INCLINATION": 51.6},
        ]
        passes = predict_passes_for_group(satellites, 34.05, -118.24, hours=24.0)
        for i in range(len(passes) - 1):
            assert passes[i]["aos"] <= passes[i + 1]["aos"]

    def test_results_include_satellite_name(self):
        satellites = [
            {"OBJECT_NAME": "ISS", "NORAD_CAT_ID": "25544",
             "TLE_LINE1": ISS_TLE1, "TLE_LINE2": ISS_TLE2, "INCLINATION": 51.6},
        ]
        passes = predict_passes_for_group(satellites, 34.05, -118.24, hours=24.0)
        for p in passes:
            assert "satellite_name" in p
            assert "norad_id" in p

    def test_empty_input(self):
        assert predict_passes_for_group([], 34.05, -118.24) == []

    def test_skips_unreachable_inclination(self):
        # CSS at 41.5° inclination from 60°N — should be filtered out
        satellites = [
            {"OBJECT_NAME": "CSS", "NORAD_CAT_ID": "48274",
             "TLE_LINE1": ISS_TLE1, "TLE_LINE2": ISS_TLE2, "INCLINATION": 41.5},
        ]
        passes = predict_passes_for_group(
            satellites, 60.0, 0.0, hours=24.0, min_elevation_deg=10.0
        )
        assert len(passes) == 0
