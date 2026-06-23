import math
from datetime import datetime, timezone, timedelta
from typing import List, Dict
from sgp4.api import Satrec
from orbital_math import build_satellite, propagate_to_time, eci_to_geodetic


def compute_distance_at_time(sat1: Satrec, sat2: Satrec, dt: datetime) -> float:
    r1, _ = propagate_to_time(sat1, dt)
    r2, _ = propagate_to_time(sat2, dt)
    return math.sqrt(sum((a - b) ** 2 for a, b in zip(r1, r2)))


def find_closest_approach(
    sat1: Satrec,
    sat2: Satrec,
    start_time: datetime,
    hours: float = 24.0,
    coarse_step_min: float = 2.0,
    bisection_iterations: int = 20,
) -> Dict:
    end_time = start_time + timedelta(hours=hours)
    steps = int((hours * 60) / coarse_step_min)

    best_time = start_time
    best_dist = float("inf")

    for i in range(steps + 1):
        dt = start_time + timedelta(minutes=i * coarse_step_min)
        try:
            dist = compute_distance_at_time(sat1, sat2, dt)
            if dist < best_dist:
                best_dist = dist
                best_time = dt
        except ValueError:
            continue

    # Bisection refinement around the coarse minimum
    lo = best_time - timedelta(minutes=coarse_step_min)
    hi = best_time + timedelta(minutes=coarse_step_min)
    if lo < start_time:
        lo = start_time
    if hi > end_time:
        hi = end_time

    for _ in range(bisection_iterations):
        mid = lo + (hi - lo) / 2
        left = lo + (mid - lo) / 2
        right = mid + (hi - mid) / 2
        try:
            d_left = compute_distance_at_time(sat1, sat2, left)
            d_right = compute_distance_at_time(sat1, sat2, right)
        except ValueError:
            break
        if d_left < d_right:
            hi = mid
        else:
            lo = mid

    tca = lo + (hi - lo) / 2
    try:
        dca = compute_distance_at_time(sat1, sat2, tca)
    except ValueError:
        dca = best_dist
        tca = best_time

    try:
        r1, _ = propagate_to_time(sat1, tca)
        r2, _ = propagate_to_time(sat2, tca)
        pos1 = eci_to_geodetic(r1, tca)
        pos2 = eci_to_geodetic(r2, tca)
    except ValueError:
        pos1 = {"lat": 0, "lon": 0, "alt_km": 0}
        pos2 = {"lat": 0, "lon": 0, "alt_km": 0}

    return {
        "tca": tca.isoformat(),
        "dca_km": round(dca, 3),
        "sat1_position": {k: round(v, 4) for k, v in pos1.items()},
        "sat2_position": {k: round(v, 4) for k, v in pos2.items()},
    }


def classify_severity(dca_km: float) -> str:
    if dca_km < 1:
        return "critical"
    if dca_km < 5:
        return "warning"
    return "caution"


def screen_conjunctions(
    satellites: List[Dict],
    threshold_km: float = 25.0,
    hours: float = 24.0,
    max_pairs: int = 50,
) -> List[Dict]:
    now = datetime.now(timezone.utc)

    # Build Satrec objects and compute reference altitudes for pre-filtering
    sat_records = []
    for item in satellites:
        tle1 = item.get("TLE_LINE1", "")
        tle2 = item.get("TLE_LINE2", "")
        if not tle1 or not tle2:
            continue
        try:
            sat = build_satellite(tle1, tle2)
            r, _ = propagate_to_time(sat, now)
            alt = math.sqrt(sum(x ** 2 for x in r)) - 6378.137
            sat_records.append({
                "sat": sat,
                "name": item.get("OBJECT_NAME", "UNKNOWN"),
                "norad_id": str(item.get("NORAD_CAT_ID", "")),
                "alt_km": alt,
            })
        except (ValueError, Exception):
            continue

    # Pre-filter: skip pairs where altitude difference alone exceeds threshold * 2
    alt_threshold = threshold_km * 2
    candidates = []
    for i in range(len(sat_records)):
        for j in range(i + 1, len(sat_records)):
            if abs(sat_records[i]["alt_km"] - sat_records[j]["alt_km"]) < alt_threshold:
                candidates.append((sat_records[i], sat_records[j]))

    results = []
    for s1, s2 in candidates:
        try:
            approach = find_closest_approach(s1["sat"], s2["sat"], now, hours=hours)
            if approach["dca_km"] <= threshold_km:
                results.append({
                    "sat1_name": s1["name"],
                    "sat1_norad_id": s1["norad_id"],
                    "sat2_name": s2["name"],
                    "sat2_norad_id": s2["norad_id"],
                    "tca": approach["tca"],
                    "dca_km": approach["dca_km"],
                    "severity": classify_severity(approach["dca_km"]),
                    "sat1_position": approach["sat1_position"],
                    "sat2_position": approach["sat2_position"],
                })
        except Exception:
            continue

        if len(results) >= max_pairs:
            break

    results.sort(key=lambda x: x["dca_km"])
    return results
