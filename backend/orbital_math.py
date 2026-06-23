"""
orbital_math.py
---------------
Converts raw TLE data into real-world satellite positions.

The key library here is sgp4, which implements the SGP4/SDP4 algorithm —
the same algorithm used by NORAD and every serious orbital mechanics tool.

SGP4 = Simplified General Perturbations 4
  It accounts for:
  - Earth's non-spherical shape (J2 perturbation — the equatorial bulge)
  - Atmospheric drag (important for low Earth orbit like Starlink)
  - Solar radiation pressure
  - Lunar and solar gravity

The output is a position vector in the ECI (Earth-Centered Inertial) frame:
  X, Y, Z in kilometers, where the origin is Earth's center and the
  axes are fixed to distant stars (not rotating with Earth).

We then convert ECI → geodetic (lat/lon/alt) so Cesium.js can place
the satellite on the globe.
"""

import math
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Tuple
from sgp4.api import Satrec, jday  # sgp4's two main tools


def build_satellite(tle_line1: str, tle_line2: str) -> Satrec:
    """
    Parses TLE lines into an sgp4 Satrec (satellite record) object.
    This object holds all the orbital parameters and can be propagated
    forward in time.
    """
    return Satrec.twoline2rv(tle_line1, tle_line2)


def propagate_to_time(sat: Satrec, dt: datetime) -> Tuple[List[float], List[float]]:
    """
    Predicts where a satellite is at a given datetime.

    Returns (position, velocity):
      - position: [x, y, z] in km (ECI frame)
      - velocity: [vx, vy, vz] in km/s

    jday() converts a calendar date to a Julian Day Number, which sgp4 needs.
    Julian dates are a continuous count of days since noon, Jan 1, 4713 BC —
    it's the astronomer's universal timestamp, avoiding timezone headaches.
    """
    year, month, day = dt.year, dt.month, dt.day
    hour, minute, second = dt.hour, dt.minute, dt.second
    microsecond = dt.microsecond

    # Convert to Julian date
    jd, fr = jday(year, month, day, hour, minute, second + microsecond / 1e6)

    # Propagate: returns error code, position (km), velocity (km/s)
    e, r, v = sat.sgp4(jd, fr)

    if e != 0:
        raise ValueError(f"SGP4 propagation error code {e}")

    return list(r), list(v)


WGS84_A = 6378.137
WGS84_F = 1 / 298.257223563
WGS84_B = WGS84_A * (1 - WGS84_F)
WGS84_E2 = 1 - (WGS84_B / WGS84_A) ** 2


def compute_gmst_rad(dt: datetime) -> float:
    """
    Compute Greenwich Mean Sidereal Time in radians.
    Uses the IAU formula referenced to J2000.
    """
    J2000 = 2451545.0
    jd, fr = jday(dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second)
    jd_total = jd + fr
    T = (jd_total - J2000) / 36525.0

    gmst_deg = (
        280.46061837
        + 360.98564736629 * (jd_total - J2000)
        + T * T * 0.000387933
        - T * T * T / 38710000.0
    ) % 360.0

    return math.radians(gmst_deg)


def eci_to_ecef(r: List[float], dt: datetime) -> List[float]:
    """
    Rotate an ECI position vector to ECEF using GMST.
    """
    gmst = compute_gmst_rad(dt)
    x, y, z = r
    return [
        x * math.cos(gmst) + y * math.sin(gmst),
       -x * math.sin(gmst) + y * math.cos(gmst),
        z,
    ]


def eci_to_geodetic(r: List[float], dt: datetime) -> Dict[str, float]:
    """
    Converts ECI (Earth-Centered Inertial) coordinates to
    geodetic coordinates: latitude, longitude, altitude.

    Steps:
      1. Rotate ECI → ECEF using GMST
      2. Convert ECEF to lat/lon/alt using WGS84 ellipsoid math
    """
    ecef_x, ecef_y, ecef_z = eci_to_ecef(r, dt)

    lon_rad = math.atan2(ecef_y, ecef_x)
    p = math.sqrt(ecef_x ** 2 + ecef_y ** 2)

    lat_rad = math.atan2(ecef_z, p * (1 - WGS84_E2))
    for _ in range(5):
        sin_lat = math.sin(lat_rad)
        N = WGS84_A / math.sqrt(1 - WGS84_E2 * sin_lat ** 2)
        lat_rad = math.atan2(ecef_z + WGS84_E2 * N * sin_lat, p)

    sin_lat = math.sin(lat_rad)
    N = WGS84_A / math.sqrt(1 - WGS84_E2 * sin_lat ** 2)
    alt = p / math.cos(lat_rad) - N if abs(math.cos(lat_rad)) > 1e-10 else abs(ecef_z) / abs(sin_lat) - N * (1 - WGS84_E2)

    return {
        "lat": math.degrees(lat_rad),
        "lon": math.degrees(lon_rad),
        "alt_km": alt,
    }


def get_orbit_path(sat: Satrec, num_points: int = 90) -> List[Dict]:
    """
    Generates a list of lat/lon/alt points tracing one full orbit.

    We sample the satellite's position at regular intervals over one
    orbital period. The period (in minutes) is 1440 / mean_motion,
    where mean_motion is revolutions per day (stored in the TLE).

    num_points=90 gives a smooth curve without being too heavy for the browser.
    """
    # Mean motion is in rev/day; convert to orbital period in minutes
    period_min = 1440.0 / sat.no_kozai * (2 * math.pi)  # no_kozai is rad/min

    now = datetime.now(timezone.utc)
    points = []

    for i in range(num_points):
        fraction = i / num_points
        dt = now + timedelta(minutes=fraction * period_min)
        try:
            r, _ = propagate_to_time(sat, dt)
            geo = eci_to_geodetic(r, dt)
            geo["time_offset_min"] = round(fraction * period_min, 2)
            points.append(geo)
        except ValueError:
            continue  # skip points where propagation fails (rare edge case)

    return points


def compute_altitude_series(sat: Satrec, hours: int = 24) -> List[Dict]:
    """
    Generates an altitude time-series for the past N hours.
    Used by the D3.js telemetry chart to show altitude over time.

    Altitude dropping unexpectedly → possible atmospheric drag anomaly.
    This is the data our ML model will watch.
    """
    now = datetime.now(timezone.utc)
    series = []

    for i in range(hours * 6):  # sample every 10 minutes
        dt = now - timedelta(minutes=(hours * 60) - i * 10)
        try:
            r, v = propagate_to_time(sat, dt)
            geo = eci_to_geodetic(r, dt)
            speed_km_s = math.sqrt(sum(vi ** 2 for vi in v))
            series.append({
                "timestamp": dt.isoformat(),
                "alt_km": round(geo["alt_km"], 3),
                "lat": round(geo["lat"], 4),
                "lon": round(geo["lon"], 4),
                "speed_km_s": round(speed_km_s, 4),
            })
        except ValueError:
            continue

    return series
