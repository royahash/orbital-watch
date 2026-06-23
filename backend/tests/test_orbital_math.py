import math
import pytest
from datetime import datetime, timezone, timedelta
from sgp4.api import Satrec
from orbital_math import (
    build_satellite, propagate_to_time, eci_to_geodetic, eci_to_ecef,
    compute_gmst_rad, get_orbit_path, compute_altitude_series,
    WGS84_A, WGS84_E2,
)
from tests.conftest import ISS_TLE1, ISS_TLE2, REFERENCE_TIME


class TestBuildSatellite:
    def test_returns_satrec(self):
        sat = build_satellite(ISS_TLE1, ISS_TLE2)
        assert isinstance(sat, Satrec)

    def test_has_orbital_elements(self, iss_sat):
        assert iss_sat.no_kozai > 0  # mean motion
        assert 0 <= iss_sat.ecco < 1  # eccentricity
        assert iss_sat.inclo > 0  # inclination (radians)


class TestPropagateToTime:
    def test_returns_position_and_velocity(self, iss_sat, ref_time):
        r, v = propagate_to_time(iss_sat, ref_time)
        assert len(r) == 3
        assert len(v) == 3

    def test_position_magnitude_is_reasonable(self, iss_sat, ref_time):
        r, _ = propagate_to_time(iss_sat, ref_time)
        mag = math.sqrt(sum(x**2 for x in r))
        # ISS orbits at ~420km altitude; Earth radius ~6378km
        assert 6700 < mag < 6900

    def test_velocity_magnitude_is_reasonable(self, iss_sat, ref_time):
        _, v = propagate_to_time(iss_sat, ref_time)
        speed = math.sqrt(sum(x**2 for x in v))
        # LEO orbital speed ~7.5-7.8 km/s
        assert 7.0 < speed < 8.5

    def test_raises_on_invalid_propagation(self):
        sat = Satrec()
        with pytest.raises(ValueError):
            propagate_to_time(sat, REFERENCE_TIME)


class TestComputeGmstRad:
    def test_returns_float(self, ref_time):
        gmst = compute_gmst_rad(ref_time)
        assert isinstance(gmst, float)

    def test_within_valid_range(self, ref_time):
        gmst = compute_gmst_rad(ref_time)
        assert 0 <= gmst < 2 * math.pi


class TestEciToEcef:
    def test_preserves_magnitude(self, iss_sat, ref_time):
        r, _ = propagate_to_time(iss_sat, ref_time)
        ecef = eci_to_ecef(r, ref_time)
        mag_eci = math.sqrt(sum(x**2 for x in r))
        mag_ecef = math.sqrt(sum(x**2 for x in ecef))
        assert abs(mag_eci - mag_ecef) < 1e-6

    def test_z_component_unchanged(self, iss_sat, ref_time):
        r, _ = propagate_to_time(iss_sat, ref_time)
        ecef = eci_to_ecef(r, ref_time)
        assert ecef[2] == r[2]


class TestEciToGeodetic:
    def test_latitude_in_range(self, iss_sat, ref_time):
        r, _ = propagate_to_time(iss_sat, ref_time)
        geo = eci_to_geodetic(r, ref_time)
        assert -90 <= geo["lat"] <= 90

    def test_longitude_in_range(self, iss_sat, ref_time):
        r, _ = propagate_to_time(iss_sat, ref_time)
        geo = eci_to_geodetic(r, ref_time)
        assert -180 <= geo["lon"] <= 180

    def test_iss_altitude_range(self, iss_sat, ref_time):
        r, _ = propagate_to_time(iss_sat, ref_time)
        geo = eci_to_geodetic(r, ref_time)
        # ISS orbits at 390-430 km
        assert 370 < geo["alt_km"] < 450

    def test_iss_latitude_within_inclination(self, iss_sat, ref_time):
        r, _ = propagate_to_time(iss_sat, ref_time)
        geo = eci_to_geodetic(r, ref_time)
        # ISS inclination is 51.6°, latitude cannot exceed this
        assert abs(geo["lat"]) <= 53

    def test_known_equatorial_point(self):
        # A point on the x-axis in ECI at GMST=0 should be near lon=0
        dt = datetime(2000, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        gmst = compute_gmst_rad(dt)
        # Place a point at equator along GMST direction
        r_mag = WGS84_A + 400  # 400km altitude
        r = [r_mag * math.cos(gmst), r_mag * math.sin(gmst), 0.0]
        geo = eci_to_geodetic(r, dt)
        assert abs(geo["lat"]) < 1.0
        assert abs(geo["lon"]) < 1.0
        assert abs(geo["alt_km"] - 400) < 5


class TestGetOrbitPath:
    def test_returns_expected_length(self, iss_sat):
        path = get_orbit_path(iss_sat, num_points=45)
        # Allow some tolerance for propagation failures
        assert 40 <= len(path) <= 45

    def test_points_have_required_fields(self, iss_sat):
        path = get_orbit_path(iss_sat, num_points=20)
        for pt in path:
            assert "lat" in pt
            assert "lon" in pt
            assert "alt_km" in pt
            assert "time_offset_min" in pt

    def test_latitude_range_matches_inclination(self, iss_sat):
        path = get_orbit_path(iss_sat, num_points=90)
        lats = [pt["lat"] for pt in path]
        # ISS at 51.6° inclination should span roughly ±51.6° latitude
        assert max(lats) > 40
        assert min(lats) < -40


class TestComputeAltitudeSeries:
    def test_returns_expected_count(self, iss_sat):
        series = compute_altitude_series(iss_sat, hours=6)
        # 6 hours * 6 samples/hour = 36 points
        assert 30 <= len(series) <= 36

    def test_points_have_required_fields(self, iss_sat):
        series = compute_altitude_series(iss_sat, hours=2)
        for pt in series:
            assert "timestamp" in pt
            assert "alt_km" in pt
            assert "lat" in pt
            assert "lon" in pt
            assert "speed_km_s" in pt

    def test_altitude_values_reasonable(self, iss_sat):
        series = compute_altitude_series(iss_sat, hours=2)
        for pt in series:
            assert 370 < pt["alt_km"] < 450

    def test_speed_values_reasonable(self, iss_sat):
        series = compute_altitude_series(iss_sat, hours=2)
        for pt in series:
            assert 7.0 < pt["speed_km_s"] < 8.5
