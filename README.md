# OrbitalWatch — Real-Time Satellite Telemetry Platform

A full-stack aerospace data visualization platform that ingests live TLE data, propagates satellite orbits using the SGP4 algorithm, renders a real-time 3D constellation on a WebGL globe, and applies machine learning anomaly detection to orbital telemetry.

Built to demonstrate the intersection of data visualization engineering and aerospace domain knowledge.

---

## What It Does

- **Live data** — Fetches Two-Line Element (TLE) sets from CelesTrak's public catalog (Starlink, GPS, ISS)
- **Orbital propagation** — Implements SGP4/SDP4 via the `sgp4` library to predict satellite positions at any time
- **3D visualization** — Renders 200+ satellites on a Cesium.js WebGL globe with real-time orbit path tracing
- **Telemetry analysis** — D3.js time-series charts showing altitude and speed over 24–72 hours
- **Anomaly detection** — Isolation Forest (scikit-learn) flags abnormal orbital parameter changes without requiring labeled training data

---

## Tech Stack

| Layer | Technology | Why |
|---|---|---|
| Backend | Python + FastAPI | Async-native, auto-generates API docs |
| Orbital math | sgp4 (Python) | Industry-standard NORAD algorithm |
| ML | scikit-learn Isolation Forest | Unsupervised — works without labeled anomaly data |
| 3D Globe | Cesium.js | Used by NASA, ESA, and commercial aerospace |
| Charts | D3.js | Full control over visualization primitives |
| Data source | CelesTrak GP API | Standard free public TLE source |

---

## Aerospace Concepts Implemented

**TLE (Two-Line Element Set)**
The NORAD standard format encoding a satellite's orbital state. Each satellite has two 69-character lines encoding inclination, RAAN, eccentricity, argument of perigee, mean anomaly, and mean motion.

**SGP4 Propagation**
Simplified General Perturbations 4 — the algorithm used by NORAD and every serious orbital mechanics tool. Accounts for Earth's oblateness (J2), atmospheric drag, and third-body perturbations.

**ECI → Geodetic Conversion**
Positions from SGP4 are in the Earth-Centered Inertial (ECI) frame. We apply a GMST rotation to convert to ECEF, then use iterative Bowring's method to convert to geodetic lat/lon/alt using the WGS84 ellipsoid.

**Orbital Period**
Derived from mean motion (rev/day): `T = 2π / n_kozai` in minutes. Used to trace one complete orbit for the path visualization.

---

## Running Locally

### Backend
```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```
API docs auto-generated at: http://localhost:8000/docs

### Frontend
1. Get a free Cesium Ion token at https://ion.cesium.com
2. Paste it into `frontend/js/app.js` where it says `YOUR_CESIUM_ION_TOKEN_HERE`
3. Open `frontend/index.html` in a browser (use Live Server in VS Code or similar)

---

## API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| GET | `/satellites?group=starlink` | Current positions of up to 200 satellites |
| GET | `/satellite/{norad_id}/orbit` | Lat/lon/alt path for one full orbit |
| GET | `/satellite/{norad_id}/telemetry?hours=24` | Time-series with anomaly scores |

---

## Project Structure

```
orbital-watch/
├── backend/
│   ├── main.py              # FastAPI app and API routes
│   ├── tle_fetcher.py       # CelesTrak data ingestion
│   ├── orbital_math.py      # SGP4 propagation + coordinate transforms
│   ├── anomaly_detector.py  # Isolation Forest ML model
│   └── requirements.txt
└── frontend/
    ├── index.html           # App shell
    ├── css/style.css        # Dark mission-control theme
    └── js/app.js            # Cesium globe + D3 charts + API calls
```

---

## Why This Project

My background is in Data Visualization (B.S.) and Computer Science (minor). Aerospace companies — Boeing, Starlink, NASA — all run software teams that build mission operations tooling: telemetry dashboards, conjunction screening tools, ground station pass predictors. This project demonstrates I can contribute to that work on day one, using the same data sources (CelesTrak, NORAD TLEs), the same visualization tools (Cesium.js), and the same orbital mechanics (SGP4) that production systems use.

---

*Roya Hashimi — royahashimi005@gmail.com*
