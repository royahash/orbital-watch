/**
 * app.js — OrbitalWatch Frontend
 *
 * This file wires together:
 *   1. Cesium.js  — the 3D globe with satellite markers and orbit paths
 *   2. D3.js      — the telemetry charts (altitude and speed over time)
 *   3. Fetch API  — HTTP calls to our FastAPI backend
 *
 * How data flows:
 *   User picks a constellation
 *     → fetch /satellites from backend
 *     → place colored dots on Cesium globe
 *   User clicks a satellite
 *     → fetch /satellite/{id}/orbit → draw orbit path on globe
 *     → fetch /satellite/{id}/telemetry → draw D3 charts + status badge
 */

// ─────────────────────────────────────────────────────
// CONFIGURATION
// ─────────────────────────────────────────────────────

const API_BASE = "https://orbital-watch.onrender.com";

Cesium.Ion.defaultAccessToken = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJqdGkiOiI3MmQzNWExMC1jNjNmLTRiNGItOWVkNS03YWZjNjY2NjVmZWQiLCJpZCI6NDU2OTQzLCJpc3MiOiJodHRwczovL2FwaS5jZXNpdW0uY29tIiwiYXVkIjoidW5kZWZpbmVkX2RlZmF1bHQiLCJpYXQiOjE3ODQxNjczNTR9.bgQW5ssAv06LQti8KUTTOWYUJRhKMXc6Q2jMaKNyg1s";


// ─────────────────────────────────────────────────────
// CESIUM GLOBE SETUP
// ─────────────────────────────────────────────────────

/**
 * Cesium.Viewer creates the interactive 3D globe.
 * We disable UI controls we don't need to keep the interface clean.
 * The globe is rendered via WebGL — your GPU does the heavy lifting.
 */
const viewer = new Cesium.Viewer("cesium-container", {
  animation: false,             // hide the timeline animation clock
  baseLayerPicker: false,       // hide the imagery selector
  fullscreenButton: false,
  geocoder: false,              // hide the search bar
  homeButton: false,
  infoBox: false,               // we use our own side panel
  sceneModePicker: false,
  selectionIndicator: false,
  timeline: false,
  navigationHelpButton: false,
  skyAtmosphere: new Cesium.SkyAtmosphere(),  // realistic atmosphere glow
});

// Dark space background
viewer.scene.backgroundColor = Cesium.Color.fromCssColorString("#0a0e1a");
viewer.scene.globe.enableLighting = true;

// Set initial camera to view Earth from space
viewer.camera.setView({
  destination: Cesium.Cartesian3.fromDegrees(0, 20, 20000000),  // lon, lat, altitude (meters)
  orientation: { heading: 0, pitch: -Cesium.Math.PI_OVER_TWO, roll: 0 },
});


// ─────────────────────────────────────────────────────
// STATE
// ─────────────────────────────────────────────────────

let allSatellites = [];
let filteredSatellites = [];
let selectedNoradId = null;
let orbitPathEntity = null;
let satelliteEntities = [];
let conjunctionEntities = [];
let groundStationEntity = null;
let visibilityConeEntity = null;
let passTrackEntities = [];
let placingGroundStation = false;


// ─────────────────────────────────────────────────────
// MAIN LOAD FUNCTION
// ─────────────────────────────────────────────────────

async function loadSatellites() {
  const group = document.getElementById("group-select").value;
  showLoading(true);
  clearGlobe();

  try {
    const res = await fetch(`${API_BASE}/satellites?group=${group}`);
    if (!res.ok) throw new Error(`API error: ${res.status}`);
    const data = await res.json();

    allSatellites = data.satellites;
    filteredSatellites = [...allSatellites];

    renderSatelliteList(filteredSatellites);
    renderSatellitesOnGlobe(filteredSatellites);

    const now = new Date().toLocaleTimeString();
    document.getElementById("last-updated").textContent = `Updated ${now}`;
    document.getElementById("sat-count").textContent = `(${allSatellites.length})`;

  } catch (err) {
    console.error("Failed to load satellites:", err);
    alert(`Could not connect to the OrbitalWatch API.\n\nMake sure the backend is running:\n  cd backend && uvicorn main:app --reload`);
  } finally {
    showLoading(false);
  }
}


// ─────────────────────────────────────────────────────
// SATELLITE LIST (left panel)
// ─────────────────────────────────────────────────────

function renderSatelliteList(satellites) {
  const ul = document.getElementById("satellite-list");
  ul.innerHTML = "";

  satellites.forEach(sat => {
    const li = document.createElement("li");
    if (sat.norad_id === selectedNoradId) li.classList.add("active");

    li.innerHTML = `
      <div class="sat-name">${sat.name}</div>
      <div class="sat-alt">${sat.alt_km.toFixed(0)} km</div>
    `;

    li.addEventListener("click", () => selectSatellite(sat));
    ul.appendChild(li);
  });
}

// Filter as user types in the search box
document.getElementById("sat-search").addEventListener("input", function () {
  const query = this.value.toLowerCase();
  filteredSatellites = allSatellites.filter(s => s.name.toLowerCase().includes(query));
  renderSatelliteList(filteredSatellites);
});


// ─────────────────────────────────────────────────────
// CESIUM — SATELLITE MARKERS
// ─────────────────────────────────────────────────────

/**
 * Places a glowing dot for each satellite on the 3D globe.
 *
 * Cesium.Cartesian3.fromDegrees() converts lat/lon/alt to
 * the ECEF coordinate system Cesium uses internally.
 *
 * We color-code by altitude:
 *   Blue  = LEO (< 600 km)   — Starlink, most commercial
 *   Cyan  = MEO (600–2000 km)
 *   Green = HEO (> 2000 km)  — GPS, Galileo
 */
function renderSatellitesOnGlobe(satellites) {
  satellites.forEach(sat => {
    const color = altitudeColor(sat.alt_km);

    const entity = viewer.entities.add({
      name: sat.name,
      position: Cesium.Cartesian3.fromDegrees(sat.lon, sat.lat, sat.alt_km * 1000),  // alt in meters
      point: {
        pixelSize: 4,
        color: color,
        outlineColor: color.withAlpha(0.3),
        outlineWidth: 2,
        scaleByDistance: new Cesium.NearFarScalar(1e6, 1.5, 2e7, 0.3),
      },
      properties: { norad_id: sat.norad_id, data: sat },
    });

    entity.description = sat.name;
    satelliteEntities.push(entity);
  });

  // Click a satellite dot on the globe to select it
  viewer.screenSpaceEventHandler.setInputAction(click => {
    const picked = viewer.scene.pick(click.position);
    if (Cesium.defined(picked) && picked.id && picked.id.properties) {
      const sat = picked.id.properties.data.getValue();
      selectSatellite(sat);
    }
  }, Cesium.ScreenSpaceEventType.LEFT_CLICK);
}

function altitudeColor(alt_km) {
  if (alt_km < 600)  return Cesium.Color.fromCssColorString("#2979ff");  // blue — LEO
  if (alt_km < 2000) return Cesium.Color.fromCssColorString("#00e5ff");  // cyan — MEO
  return Cesium.Color.fromCssColorString("#00e676");                      // green — HEO
}

function clearGlobe() {
  viewer.entities.removeAll();
  satelliteEntities = [];
  orbitPathEntity = null;
}


// ─────────────────────────────────────────────────────
// SELECT A SATELLITE
// ─────────────────────────────────────────────────────

async function selectSatellite(sat) {
  selectedNoradId = sat.norad_id;

  // Highlight in list
  document.querySelectorAll("#satellite-list li").forEach(li => li.classList.remove("active"));
  const listItems = document.querySelectorAll("#satellite-list li .sat-name");
  listItems.forEach(el => {
    if (el.textContent === sat.name) el.closest("li").classList.add("active");
  });

  // Fly camera to the satellite
  viewer.camera.flyTo({
    destination: Cesium.Cartesian3.fromDegrees(sat.lon, sat.lat, sat.alt_km * 1000 + 3000000),
    duration: 2,
    orientation: { heading: 0, pitch: -Cesium.Math.PI_OVER_FOUR, roll: 0 },
  });

  // Show panel with basic stats immediately
  showTelemetryPanel(sat);

  // Load orbit path and telemetry in parallel (faster than sequential)
  const group = document.getElementById("group-select").value;
  const [orbitData, telemetryData] = await Promise.all([
    fetch(`${API_BASE}/satellite/${sat.norad_id}/orbit?group=${group}`).then(r => r.json()),
    fetch(`${API_BASE}/satellite/${sat.norad_id}/telemetry?group=${group}&hours=24`).then(r => r.json()),
  ]);

  drawOrbitPath(orbitData.orbit_path);
  updateTelemetryPanel(telemetryData);
}


// ─────────────────────────────────────────────────────
// ORBIT PATH (Cesium polyline)
// ─────────────────────────────────────────────────────

/**
 * Draws the satellite's orbit as a polyline on the globe.
 *
 * We remove the previous orbit before drawing the new one.
 * Cesium.Cartesian3.fromDegreesArrayHeights() takes a flat array of
 * [lon, lat, alt, lon, lat, alt, ...] — we build that from our path data.
 */
function drawOrbitPath(path) {
  if (orbitPathEntity) viewer.entities.remove(orbitPathEntity);

  const positions = [];
  path.forEach(pt => {
    positions.push(pt.lon, pt.lat, pt.alt_km * 1000);  // Cesium needs meters
  });

  orbitPathEntity = viewer.entities.add({
    polyline: {
      positions: Cesium.Cartesian3.fromDegreesArrayHeights(positions),
      width: 1.5,
      material: new Cesium.PolylineGlowMaterialProperty({
        glowPower: 0.15,
        color: Cesium.Color.fromCssColorString("#00e5ff").withAlpha(0.7),
      }),
    },
  });
}


// ─────────────────────────────────────────────────────
// TELEMETRY PANEL
// ─────────────────────────────────────────────────────

function showTelemetryPanel(sat) {
  document.getElementById("no-selection-msg").style.display = "none";
  document.getElementById("telemetry-content").style.display = "block";
  document.getElementById("selected-sat-name").textContent = sat.name;

  document.getElementById("stat-alt").textContent = sat.alt_km.toFixed(1);
  document.getElementById("stat-lat").textContent = sat.lat.toFixed(3);
  document.getElementById("stat-lon").textContent = sat.lon.toFixed(3);
  document.getElementById("stat-inc").textContent = sat.inclination_deg
    ? parseFloat(sat.inclination_deg).toFixed(2)
    : "—";

  // Clear charts while loading
  document.getElementById("altitude-chart").innerHTML = "";
  document.getElementById("speed-chart").innerHTML = "";
}

function updateTelemetryPanel(data) {
  const { summary, telemetry } = data;

  // Status badge
  const dot = document.getElementById("status-dot");
  const text = document.getElementById("status-text");
  dot.className = summary.status;
  text.className = summary.status;
  text.textContent = summary.status.toUpperCase();
  document.getElementById("status-message").textContent = summary.message;

  // Anomaly summary
  document.getElementById("anomaly-count-text").textContent =
    summary.anomaly_count === 0
      ? "No anomalies detected in the last 24 hours."
      : `${summary.anomaly_count} anomalous readings detected. Worst score: ${summary.worst_score}.`;

  // Draw D3 charts
  drawAltitudeChart(telemetry, "#altitude-chart", "alt_km", "Altitude (km)", "altitude");
  drawAltitudeChart(telemetry, "#speed-chart", "speed_km_s", "Speed (km/s)", "speed");
}


// ─────────────────────────────────────────────────────
// D3 CHARTS
// ─────────────────────────────────────────────────────

/**
 * Draws a time-series line chart using D3.
 *
 * Key D3 concepts used here:
 *   - Scales: map data values to pixel positions (d3.scaleTime, d3.scaleLinear)
 *   - Line generator: converts an array of data points to an SVG path string
 *   - Axes: rendered using d3.axisBottom / d3.axisLeft
 *   - Data binding: d3.selectAll().data().enter() creates elements from data
 *
 * Anomalous points are drawn as red circles on top of the line.
 */
function drawAltitudeChart(telemetry, selector, field, yLabel, lineClass) {
  const container = document.querySelector(selector);
  container.innerHTML = "";

  const W = container.clientWidth || 240;
  const H = 120;
  const margin = { top: 8, right: 8, bottom: 24, left: 42 };
  const innerW = W - margin.left - margin.right;
  const innerH = H - margin.top - margin.bottom;

  const svg = d3.select(selector)
    .append("svg")
    .attr("width", W)
    .attr("height", H);

  const g = svg.append("g")
    .attr("transform", `translate(${margin.left},${margin.top})`);

  // Parse timestamps
  const parseTime = d3.isoParse;
  const data = telemetry.map(d => ({ ...d, ts: parseTime(d.timestamp) }));

  // X scale: time axis
  const xScale = d3.scaleTime()
    .domain(d3.extent(data, d => d.ts))
    .range([0, innerW]);

  // Y scale: data value axis
  const extent = d3.extent(data, d => d[field]);
  const padding = (extent[1] - extent[0]) * 0.1 || 0.01;
  const yScale = d3.scaleLinear()
    .domain([extent[0] - padding, extent[1] + padding])
    .range([innerH, 0]);

  // Grid lines (horizontal) for readability
  g.append("g").attr("class", "chart-grid")
    .call(d3.axisLeft(yScale).ticks(4).tickSize(-innerW).tickFormat(""));

  // X Axis
  g.append("g")
    .attr("class", "axis")
    .attr("transform", `translate(0,${innerH})`)
    .call(d3.axisBottom(xScale).ticks(4).tickFormat(d3.timeFormat("%H:%M")));

  // Y Axis
  g.append("g")
    .attr("class", "axis")
    .call(d3.axisLeft(yScale).ticks(4).tickFormat(d3.format(".1f")));

  // Line
  const line = d3.line()
    .x(d => xScale(d.ts))
    .y(d => yScale(d[field]))
    .curve(d3.curveCatmullRom.alpha(0.5));  // smooth curve

  g.append("path")
    .datum(data)
    .attr("class", `chart-line ${lineClass}`)
    .attr("d", line);

  // Anomaly dots (red circles on flagged points)
  g.selectAll(".chart-dot")
    .data(data.filter(d => d.anomaly))
    .enter()
    .append("circle")
    .attr("class", "chart-dot anomaly")
    .attr("cx", d => xScale(d.ts))
    .attr("cy", d => yScale(d[field]))
    .attr("r", 4);
}


// ─────────────────────────────────────────────────────
// UTILITIES
// ─────────────────────────────────────────────────────

function showLoading(visible) {
  document.getElementById("loading-overlay").style.display = visible ? "flex" : "none";
}


// ─────────────────────────────────────────────────────
// TAB SYSTEM
// ─────────────────────────────────────────────────────

document.querySelectorAll(".tab-btn").forEach(btn => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active"));
    document.querySelectorAll(".tab-content").forEach(c => c.style.display = "none");
    btn.classList.add("active");
    document.getElementById(btn.dataset.tab).style.display = "block";
  });
});


// ─────────────────────────────────────────────────────
// CONJUNCTION ASSESSMENT
// ─────────────────────────────────────────────────────

async function loadConjunctions() {
  const group = document.getElementById("group-select").value;
  const threshold = document.getElementById("conj-threshold").value;

  document.getElementById("conjunction-loading").style.display = "flex";
  document.getElementById("conjunction-results").style.display = "none";
  clearConjunctions();

  try {
    const res = await fetch(`${API_BASE}/conjunctions?group=${group}&threshold_km=${threshold}&hours=24`);
    if (!res.ok) throw new Error(`API error: ${res.status}`);
    const data = await res.json();

    document.getElementById("conjunction-count-text").textContent =
      data.count === 0
        ? "No close approaches detected in the next 24 hours."
        : `${data.count} conjunction event(s) found within ${threshold} km.`;

    renderConjunctionList(data.conjunctions);
    renderConjunctionsOnGlobe(data.conjunctions);
    document.getElementById("conjunction-results").style.display = "block";
  } catch (err) {
    console.error("Conjunction screening failed:", err);
    document.getElementById("conjunction-count-text").textContent = "Screening failed. Is the backend running?";
    document.getElementById("conjunction-results").style.display = "block";
  } finally {
    document.getElementById("conjunction-loading").style.display = "none";
  }
}

function renderConjunctionList(conjunctions) {
  const ul = document.getElementById("conjunction-list");
  ul.innerHTML = "";

  conjunctions.forEach(conj => {
    const li = document.createElement("li");
    li.className = `severity-${conj.severity}`;

    const tcaDate = new Date(conj.tca);
    const tcaStr = tcaDate.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

    li.innerHTML = `
      <div class="conj-pair">
        <span>${conj.sat1_name}</span>
        <span class="conj-arrow">↔</span>
        <span>${conj.sat2_name}</span>
      </div>
      <div class="conj-details">
        <span class="conj-dca ${conj.severity}">${conj.dca_km.toFixed(2)} km</span>
        <span>TCA ${tcaStr}</span>
      </div>
    `;

    li.addEventListener("click", () => selectConjunction(conj));
    ul.appendChild(li);
  });
}

function renderConjunctionsOnGlobe(conjunctions) {
  conjunctions.forEach(conj => {
    const color = conj.severity === "critical"
      ? Cesium.Color.fromCssColorString("#ff1744")
      : conj.severity === "warning"
        ? Cesium.Color.fromCssColorString("#ffab00")
        : Cesium.Color.fromCssColorString("#ffd600");

    const p1 = conj.sat1_position;
    const p2 = conj.sat2_position;

    // Line between the two satellites at TCA
    const line = viewer.entities.add({
      polyline: {
        positions: Cesium.Cartesian3.fromDegreesArrayHeights([
          p1.lon, p1.lat, p1.alt_km * 1000,
          p2.lon, p2.lat, p2.alt_km * 1000,
        ]),
        width: 2,
        material: new Cesium.PolylineGlowMaterialProperty({
          glowPower: 0.3,
          color: color.withAlpha(0.8),
        }),
      },
    });
    conjunctionEntities.push(line);

    // Pulsing midpoint
    const midLat = (p1.lat + p2.lat) / 2;
    const midLon = (p1.lon + p2.lon) / 2;
    const midAlt = ((p1.alt_km + p2.alt_km) / 2) * 1000;

    const midpoint = viewer.entities.add({
      position: Cesium.Cartesian3.fromDegrees(midLon, midLat, midAlt),
      point: {
        pixelSize: 8,
        color: color,
        outlineColor: color.withAlpha(0.3),
        outlineWidth: 4,
      },
    });
    conjunctionEntities.push(midpoint);
  });
}

function selectConjunction(conj) {
  const midLat = (conj.sat1_position.lat + conj.sat2_position.lat) / 2;
  const midLon = (conj.sat1_position.lon + conj.sat2_position.lon) / 2;
  const midAlt = (conj.sat1_position.alt_km + conj.sat2_position.alt_km) / 2;

  viewer.camera.flyTo({
    destination: Cesium.Cartesian3.fromDegrees(midLon, midLat, midAlt * 1000 + 2000000),
    duration: 2,
    orientation: { heading: 0, pitch: -Cesium.Math.PI_OVER_FOUR, roll: 0 },
  });
}

function clearConjunctions() {
  conjunctionEntities.forEach(e => viewer.entities.remove(e));
  conjunctionEntities = [];
}

document.getElementById("run-conjunction-btn").addEventListener("click", loadConjunctions);


// ─────────────────────────────────────────────────────
// GROUND STATION & PASS PREDICTION
// ─────────────────────────────────────────────────────

function placeGroundStation(lat, lon) {
  if (groundStationEntity) viewer.entities.remove(groundStationEntity);
  if (visibilityConeEntity) viewer.entities.remove(visibilityConeEntity);

  groundStationEntity = viewer.entities.add({
    position: Cesium.Cartesian3.fromDegrees(lon, lat, 0),
    point: {
      pixelSize: 10,
      color: Cesium.Color.fromCssColorString("#ffab00"),
      outlineColor: Cesium.Color.fromCssColorString("#ffab00").withAlpha(0.3),
      outlineWidth: 6,
    },
    label: {
      text: "GS",
      font: "bold 10px monospace",
      fillColor: Cesium.Color.fromCssColorString("#ffab00"),
      style: Cesium.LabelStyle.FILL,
      verticalOrigin: Cesium.VerticalOrigin.BOTTOM,
      pixelOffset: new Cesium.Cartesian2(0, -14),
    },
  });

  // Visibility cone — approximate 5-degree minimum elevation circle (~2000km radius at LEO)
  visibilityConeEntity = viewer.entities.add({
    position: Cesium.Cartesian3.fromDegrees(lon, lat, 0),
    ellipse: {
      semiMajorAxis: 2200000,
      semiMinorAxis: 2200000,
      material: Cesium.Color.fromCssColorString("#ffab00").withAlpha(0.06),
      outline: true,
      outlineColor: Cesium.Color.fromCssColorString("#ffab00").withAlpha(0.25),
      outlineWidth: 1,
    },
  });
}

document.getElementById("place-gs-btn").addEventListener("click", () => {
  placingGroundStation = !placingGroundStation;
  document.getElementById("place-gs-btn").classList.toggle("placing", placingGroundStation);
  document.getElementById("place-gs-btn").textContent = placingGroundStation ? "Click Globe..." : "Place on Globe";

  if (placingGroundStation) {
    viewer.screenSpaceEventHandler.setInputAction(click => {
      if (!placingGroundStation) return;

      const cartesian = viewer.camera.pickEllipsoid(click.position, viewer.scene.globe.ellipsoid);
      if (!cartesian) return;

      const carto = Cesium.Cartographic.fromCartesian(cartesian);
      const lat = Cesium.Math.toDegrees(carto.latitude);
      const lon = Cesium.Math.toDegrees(carto.longitude);

      document.getElementById("gs-lat").value = lat.toFixed(4);
      document.getElementById("gs-lon").value = lon.toFixed(4);
      placeGroundStation(lat, lon);

      placingGroundStation = false;
      document.getElementById("place-gs-btn").classList.remove("placing");
      document.getElementById("place-gs-btn").textContent = "Place on Globe";
    }, Cesium.ScreenSpaceEventType.LEFT_CLICK);
  }
});

async function loadPasses() {
  const lat = parseFloat(document.getElementById("gs-lat").value);
  const lon = parseFloat(document.getElementById("gs-lon").value);
  const group = document.getElementById("group-select").value;

  if (isNaN(lat) || isNaN(lon)) return;

  placeGroundStation(lat, lon);

  document.getElementById("passes-loading").style.display = "flex";
  document.getElementById("passes-results").style.display = "none";
  clearPassTracks();

  try {
    const res = await fetch(`${API_BASE}/passes?lat=${lat}&lon=${lon}&group=${group}&hours=24&min_elevation=5`);
    if (!res.ok) throw new Error(`API error: ${res.status}`);
    const data = await res.json();

    document.getElementById("passes-count-text").textContent =
      data.count === 0
        ? "No passes predicted in the next 24 hours."
        : `${data.count} pass(es) predicted in the next 24 hours.`;

    renderPassTimeline(data.passes);
    renderPassList(data.passes);
    document.getElementById("passes-results").style.display = "block";
  } catch (err) {
    console.error("Pass prediction failed:", err);
    document.getElementById("passes-count-text").textContent = "Prediction failed. Is the backend running?";
    document.getElementById("passes-results").style.display = "block";
  } finally {
    document.getElementById("passes-loading").style.display = "none";
  }
}

function renderPassList(passes) {
  const ul = document.getElementById("passes-list");
  ul.innerHTML = "";

  passes.forEach(pass => {
    const li = document.createElement("li");

    if (pass.max_elevation_deg >= 60) li.className = "high-pass";
    else if (pass.max_elevation_deg >= 30) li.className = "mid-pass";
    else li.className = "low-pass";

    const aos = new Date(pass.aos);
    const los = new Date(pass.los);
    const aosStr = aos.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    const losStr = los.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    const durMin = Math.round(pass.duration_seconds / 60);

    li.innerHTML = `
      <div class="pass-sat-name">${pass.satellite_name}</div>
      <div class="pass-details">
        <span>${aosStr} → ${losStr} (${durMin}m)</span>
        <span class="pass-elevation">${pass.max_elevation_deg}°</span>
      </div>
    `;

    li.addEventListener("click", () => selectPass(pass));
    ul.appendChild(li);
  });
}

function renderPassTimeline(passes) {
  const container = document.getElementById("pass-timeline");
  container.innerHTML = "";

  if (passes.length === 0) return;

  const W = container.clientWidth || 248;
  const H = 60;
  const margin = { top: 4, right: 4, bottom: 18, left: 4 };
  const innerW = W - margin.left - margin.right;
  const innerH = H - margin.top - margin.bottom;

  const svg = d3.select("#pass-timeline")
    .append("svg")
    .attr("width", W)
    .attr("height", H);

  const g = svg.append("g")
    .attr("transform", `translate(${margin.left},${margin.top})`);

  const now = new Date();
  const end = new Date(now.getTime() + 24 * 60 * 60 * 1000);

  const xScale = d3.scaleTime()
    .domain([now, end])
    .range([0, innerW]);

  g.append("g")
    .attr("class", "axis")
    .attr("transform", `translate(0,${innerH})`)
    .call(d3.axisBottom(xScale).ticks(6).tickFormat(d3.timeFormat("%H:%M")));

  passes.forEach((pass, i) => {
    const aos = new Date(pass.aos);
    const los = new Date(pass.los);
    const x = xScale(aos);
    const w = Math.max(xScale(los) - xScale(aos), 2);
    const y = (i % 3) * (innerH / 3);

    const alpha = Math.min(pass.max_elevation_deg / 90, 1);
    const color = pass.max_elevation_deg >= 60 ? "#00e676"
      : pass.max_elevation_deg >= 30 ? "#00e5ff" : "#2979ff";

    g.append("rect")
      .attr("class", "pass-bar")
      .attr("x", x)
      .attr("y", y)
      .attr("width", w)
      .attr("height", innerH / 3 - 2)
      .attr("rx", 2)
      .attr("fill", color)
      .attr("opacity", 0.5 + alpha * 0.5)
      .on("click", () => selectPass(pass));
  });
}

function selectPass(pass) {
  clearPassTracks();

  if (pass.ground_track && pass.ground_track.length > 1) {
    const positions = [];
    pass.ground_track.forEach(pt => {
      positions.push(pt.lon, pt.lat, 0);
    });

    const trackEntity = viewer.entities.add({
      polyline: {
        positions: Cesium.Cartesian3.fromDegreesArrayHeights(positions),
        width: 2,
        material: Cesium.Color.fromCssColorString("#00e5ff").withAlpha(0.6),
        clampToGround: true,
      },
    });
    passTrackEntities.push(trackEntity);
  }

  const mid = pass.ground_track[Math.floor(pass.ground_track.length / 2)];
  if (mid) {
    viewer.camera.flyTo({
      destination: Cesium.Cartesian3.fromDegrees(mid.lon, mid.lat, 3000000),
      duration: 2,
    });
  }
}

function clearPassTracks() {
  passTrackEntities.forEach(e => viewer.entities.remove(e));
  passTrackEntities = [];
}

document.getElementById("predict-passes-btn").addEventListener("click", loadPasses);


// ─────────────────────────────────────────────────────
// INIT
// ─────────────────────────────────────────────────────

document.getElementById("refresh-btn").addEventListener("click", loadSatellites);
document.getElementById("group-select").addEventListener("change", loadSatellites);

loadSatellites();
