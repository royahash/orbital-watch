"""
main.py
-------
The FastAPI application — this is the "server" that the frontend talks to.

FastAPI is a modern Python web framework that:
  - Auto-generates API documentation at /docs (try it after running the server)
  - Uses async/await for non-blocking I/O (handles many users simultaneously)
  - Validates request/response types automatically

How this connects to everything:
  Browser (Cesium + D3)  →  HTTP requests  →  FastAPI (here)
                                                    ↓
                                            CelesTrak API (TLE data)
                                                    ↓
                                            sgp4 (orbital math)
                                                    ↓
                                        scikit-learn (anomaly detection)
                                                    ↓
                         ←  JSON response  ←  FastAPI sends results back

To run the server:
  cd backend
  pip install -r requirements.txt
  uvicorn main:app --reload --port 8000

Then open http://localhost:8000/docs to see all available endpoints.
"""

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Optional
import asyncio

from tle_fetcher import fetch_tle_group
from orbital_math import build_satellite, propagate_to_time, eci_to_geodetic, get_orbit_path, compute_altitude_series
from anomaly_detector import detect_anomalies, summarize_anomalies
from conjunction import screen_conjunctions
from pass_predictor import predict_passes_for_group
from datetime import datetime, timezone

# Initialize the FastAPI app
app = FastAPI(
    title="OrbitalWatch API",
    description="Real-time satellite telemetry and orbital analytics platform",
    version="1.0.0",
)

# CORS = Cross-Origin Resource Sharing
# Browsers block requests from one origin (your HTML file) to another (localhost:8000)
# unless the server explicitly says "I allow it." This enables that.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # in production, restrict to your actual domain
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    """Health check endpoint."""
    return {"status": "OrbitalWatch API is running", "time_utc": datetime.now(timezone.utc).isoformat()}


@app.get("/satellites")
async def list_satellites(
    group: str = Query(default="starlink", description="Satellite group: starlink, gps, iss")
):
    """
    Returns a list of satellites in the requested group with their current position.

    The frontend calls this on load to populate the 3D globe.
    We process up to 200 satellites at a time to keep response times reasonable.
    """
    try:
        raw = await fetch_tle_group(group)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to fetch TLE data: {e}")

    now = datetime.now(timezone.utc)
    satellites = []

    # Limit to 200 for performance; Starlink alone has 6000+ satellites
    for item in raw[:200]:
        try:
            name = item.get("OBJECT_NAME", "UNKNOWN")
            tle1 = item.get("TLE_LINE1", "")
            tle2 = item.get("TLE_LINE2", "")

            if not tle1 or not tle2:
                continue

            sat = build_satellite(tle1, tle2)
            r, v = propagate_to_time(sat, now)
            geo = eci_to_geodetic(r, now)

            satellites.append({
                "name": name,
                "norad_id": item.get("NORAD_CAT_ID"),
                "lat": round(geo["lat"], 4),
                "lon": round(geo["lon"], 4),
                "alt_km": round(geo["alt_km"], 2),
                "epoch": item.get("EPOCH"),
                "inclination_deg": item.get("INCLINATION"),
                "eccentricity": item.get("ECCENTRICITY"),
                "mean_motion_rev_per_day": item.get("MEAN_MOTION"),
            })
        except Exception:
            continue  # skip any satellite that fails to parse

    return {"group": group, "count": len(satellites), "satellites": satellites}


@app.get("/satellite/{norad_id}/orbit")
async def get_orbit(
    norad_id: str,
    group: str = Query(default="starlink"),
    num_points: int = Query(default=90, ge=20, le=360),
):
    """
    Returns a list of lat/lon/alt points tracing one complete orbit for
    a specific satellite (identified by its NORAD catalog ID).

    Cesium.js uses this to draw the orbit path as a line on the globe.
    """
    raw = await fetch_tle_group(group)
    item = next((s for s in raw if str(s.get("NORAD_CAT_ID")) == str(norad_id)), None)

    if not item:
        raise HTTPException(status_code=404, detail=f"Satellite {norad_id} not found in group '{group}'")

    sat = build_satellite(item["TLE_LINE1"], item["TLE_LINE2"])
    path = get_orbit_path(sat, num_points=num_points)

    return {
        "norad_id": norad_id,
        "name": item.get("OBJECT_NAME"),
        "orbit_path": path,
    }


@app.get("/satellite/{norad_id}/telemetry")
async def get_telemetry(
    norad_id: str,
    group: str = Query(default="starlink"),
    hours: int = Query(default=24, ge=1, le=72),
):
    """
    Returns altitude, speed, and position data for the past N hours,
    with anomaly detection scores applied to each data point.

    This feeds the D3.js time-series chart on the right panel of the dashboard.
    Red dots = anomaly flagged. Green = nominal.
    """
    raw = await fetch_tle_group(group)
    item = next((s for s in raw if str(s.get("NORAD_CAT_ID")) == str(norad_id)), None)

    if not item:
        raise HTTPException(status_code=404, detail=f"Satellite {norad_id} not found")

    sat = build_satellite(item["TLE_LINE1"], item["TLE_LINE2"])
    series = compute_altitude_series(sat, hours=hours)
    analyzed = detect_anomalies(series)
    summary = summarize_anomalies(analyzed)

    return {
        "norad_id": norad_id,
        "name": item.get("OBJECT_NAME"),
        "hours": hours,
        "summary": summary,
        "telemetry": analyzed,
    }


@app.get("/conjunctions")
async def get_conjunctions(
    group: str = Query(default="starlink", description="Satellite group"),
    threshold_km: float = Query(default=25.0, ge=0.1, le=100.0, description="Max close-approach distance in km"),
    hours: float = Query(default=24.0, ge=1.0, le=72.0, description="Look-ahead window in hours"),
):
    """
    Screens satellite pairs for close approaches (conjunctions).
    Returns events sorted by closest approach distance.
    """
    try:
        raw = await fetch_tle_group(group)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to fetch TLE data: {e}")

    conjunctions = screen_conjunctions(raw[:200], threshold_km=threshold_km, hours=hours)

    return {
        "group": group,
        "threshold_km": threshold_km,
        "hours": hours,
        "count": len(conjunctions),
        "conjunctions": conjunctions,
    }


@app.get("/passes")
async def get_passes(
    lat: float = Query(..., ge=-90, le=90, description="Ground station latitude"),
    lon: float = Query(..., ge=-180, le=180, description="Ground station longitude"),
    alt_km: float = Query(default=0.0, ge=0, description="Ground station altitude in km"),
    group: str = Query(default="starlink", description="Satellite group"),
    hours: float = Query(default=24.0, ge=1.0, le=72.0, description="Prediction window in hours"),
    min_elevation: float = Query(default=5.0, ge=0, le=90, description="Minimum elevation above horizon"),
):
    """
    Predicts satellite passes visible from a ground station.
    Returns passes sorted by AOS (Acquisition of Signal) time.
    """
    try:
        raw = await fetch_tle_group(group)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to fetch TLE data: {e}")

    passes = predict_passes_for_group(
        raw[:200],
        station_lat=lat,
        station_lon=lon,
        station_alt_km=alt_km,
        hours=hours,
        min_elevation_deg=min_elevation,
    )

    return {
        "station": {"lat": lat, "lon": lon, "alt_km": alt_km},
        "group": group,
        "hours": hours,
        "count": len(passes),
        "passes": passes,
    }
