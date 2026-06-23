import math
from datetime import datetime, timezone, timedelta
from typing import List, Dict
from sgp4.api import Satrec
from orbital_math import (
    build_satellite, propagate_to_time, eci_to_ecef, eci_to_geodetic,
    WGS84_A, WGS84_F, WGS84_B, WGS84_E2,
)


def geodetic_to_ecef(lat_deg: float, lon_deg: float, alt_km: float = 0.0) -> List[float]:
    lat = math.radians(lat_deg)
    lon = math.radians(lon_deg)
    sin_lat = math.sin(lat)
    cos_lat = math.cos(lat)
    N = WGS84_A / math.sqrt(1 - WGS84_E2 * sin_lat ** 2)
    x = (N + alt_km) * cos_lat * math.cos(lon)
    y = (N + alt_km) * cos_lat * math.sin(lon)
    z = (N * (1 - WGS84_E2) + alt_km) * sin_lat
    return [x, y, z]


def compute_look_angle(
    station_ecef: List[float],
    station_lat_rad: float,
    station_lon_rad: float,
    sat_ecef: List[float],
) -> Dict[str, float]:
    # Range vector in ECEF
    dx = sat_ecef[0] - station_ecef[0]
    dy = sat_ecef[1] - station_ecef[1]
    dz = sat_ecef[2] - station_ecef[2]
    range_km = math.sqrt(dx ** 2 + dy ** 2 + dz ** 2)

    # Rotate to topocentric (South-East-Up)
    sin_lat = math.sin(station_lat_rad)
    cos_lat = math.cos(station_lat_rad)
    sin_lon = math.sin(station_lon_rad)
    cos_lon = math.cos(station_lon_rad)

    south = sin_lat * cos_lon * dx + sin_lat * sin_lon * dy - cos_lat * dz
    east = -sin_lon * dx + cos_lon * dy
    up = cos_lat * cos_lon * dx + cos_lat * sin_lon * dy + sin_lat * dz

    elevation_rad = math.atan2(up, math.sqrt(south ** 2 + east ** 2))
    azimuth_rad = math.atan2(east, -south) % (2 * math.pi)

    return {
        "azimuth_deg": round(math.degrees(azimuth_rad), 2),
        "elevation_deg": round(math.degrees(elevation_rad), 2),
        "range_km": round(range_km, 2),
    }


def _elevation_at_time(
    sat: Satrec,
    dt: datetime,
    station_ecef: List[float],
    station_lat_rad: float,
    station_lon_rad: float,
) -> float:
    r, _ = propagate_to_time(sat, dt)
    sat_ecef = eci_to_ecef(r, dt)
    look = compute_look_angle(station_ecef, station_lat_rad, station_lon_rad, sat_ecef)
    return look["elevation_deg"]


def _refine_crossing(
    sat: Satrec,
    t_below: datetime,
    t_above: datetime,
    station_ecef: List[float],
    station_lat_rad: float,
    station_lon_rad: float,
    threshold_deg: float,
    iterations: int = 15,
) -> datetime:
    """Bisection to find the moment elevation crosses the threshold."""
    for _ in range(iterations):
        mid = t_below + (t_above - t_below) / 2
        el = _elevation_at_time(sat, mid, station_ecef, station_lat_rad, station_lon_rad)
        if el >= threshold_deg:
            t_above = mid
        else:
            t_below = mid
    return t_below + (t_above - t_below) / 2


def find_passes(
    sat: Satrec,
    station_lat: float,
    station_lon: float,
    station_alt_km: float = 0.0,
    hours: float = 24.0,
    min_elevation_deg: float = 5.0,
    step_seconds: float = 30.0,
) -> List[Dict]:
    station_ecef = geodetic_to_ecef(station_lat, station_lon, station_alt_km)
    station_lat_rad = math.radians(station_lat)
    station_lon_rad = math.radians(station_lon)

    now = datetime.now(timezone.utc)
    end = now + timedelta(hours=hours)
    steps = int((hours * 3600) / step_seconds)

    passes = []
    in_pass = False
    aos_time = None
    max_el = 0.0
    max_el_time = None
    max_el_az = 0.0
    prev_time = None
    prev_el = -90.0

    for i in range(steps + 1):
        dt = now + timedelta(seconds=i * step_seconds)
        try:
            r, _ = propagate_to_time(sat, dt)
            sat_ecef = eci_to_ecef(r, dt)
            look = compute_look_angle(station_ecef, station_lat_rad, station_lon_rad, sat_ecef)
            el = look["elevation_deg"]
        except ValueError:
            continue

        if not in_pass and el >= min_elevation_deg and prev_el < min_elevation_deg and prev_time is not None:
            # AOS detected — refine
            aos_time = _refine_crossing(
                sat, prev_time, dt, station_ecef, station_lat_rad, station_lon_rad, min_elevation_deg
            )
            in_pass = True
            max_el = el
            max_el_time = dt
            max_el_az = look["azimuth_deg"]

        elif in_pass:
            if el > max_el:
                max_el = el
                max_el_time = dt
                max_el_az = look["azimuth_deg"]

            if el < min_elevation_deg:
                # LOS detected — refine
                los_time = _refine_crossing(
                    sat, dt, prev_time, station_ecef, station_lat_rad, station_lon_rad, min_elevation_deg
                )
                # Swap if needed (los should be after aos)
                if los_time < aos_time:
                    los_time = dt

                duration = (los_time - aos_time).total_seconds()

                # Build ground track during pass
                ground_track = _compute_ground_track(sat, aos_time, los_time)

                passes.append({
                    "aos": aos_time.isoformat(),
                    "los": los_time.isoformat(),
                    "duration_seconds": round(duration),
                    "max_elevation_deg": round(max_el, 1),
                    "max_elevation_time": max_el_time.isoformat(),
                    "max_elevation_azimuth_deg": round(max_el_az, 1),
                    "ground_track": ground_track,
                })

                in_pass = False
                aos_time = None
                max_el = 0.0

        prev_time = dt
        prev_el = el

    return passes


def _compute_ground_track(sat: Satrec, aos: datetime, los: datetime, num_points: int = 30) -> List[Dict]:
    duration = (los - aos).total_seconds()
    track = []
    for i in range(num_points + 1):
        dt = aos + timedelta(seconds=i * duration / num_points)
        try:
            r, _ = propagate_to_time(sat, dt)
            geo = eci_to_geodetic(r, dt)
            track.append({
                "lat": round(geo["lat"], 4),
                "lon": round(geo["lon"], 4),
                "time": dt.isoformat(),
            })
        except ValueError:
            continue
    return track


def predict_passes_for_group(
    satellites: List[Dict],
    station_lat: float,
    station_lon: float,
    station_alt_km: float = 0.0,
    hours: float = 24.0,
    min_elevation_deg: float = 5.0,
) -> List[Dict]:
    all_passes = []

    # Pre-filter: satellites whose inclination can't reach the station latitude
    station_lat_abs = abs(station_lat)

    for item in satellites:
        tle1 = item.get("TLE_LINE1", "")
        tle2 = item.get("TLE_LINE2", "")
        if not tle1 or not tle2:
            continue

        inc = item.get("INCLINATION")
        if inc is not None:
            inc_deg = float(inc)
            # Satellite ground track can't exceed its inclination + ~5 degrees for elevation
            if station_lat_abs > inc_deg + 10:
                continue

        try:
            sat = build_satellite(tle1, tle2)
            passes = find_passes(
                sat, station_lat, station_lon, station_alt_km,
                hours=hours, min_elevation_deg=min_elevation_deg,
            )
            for p in passes:
                p["satellite_name"] = item.get("OBJECT_NAME", "UNKNOWN")
                p["norad_id"] = str(item.get("NORAD_CAT_ID", ""))
                all_passes.append(p)
        except Exception:
            continue

    all_passes.sort(key=lambda p: p["aos"])
    return all_passes
