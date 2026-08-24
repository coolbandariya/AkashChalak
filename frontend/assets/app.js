const API_BASE = "http://localhost:8000";
const { useEffect, useMemo, useState } = React;

function aqiColor(aqi) {
  if (aqi <= 50) return "#2e7d32";
  if (aqi <= 100) return "#8a9a22";
  if (aqi <= 200) return "#d7a100";
  if (aqi <= 300) return "#c45616";
  if (aqi <= 400) return "#b42318";
  return "#6d3fc0";
}

function App() {
  const [datasets, setDatasets] = useState([]);
  const [aqi, setAqi] = useState({ features: [] });
  const [hotspots, setHotspots] = useState({ features: [] });
  const [recommendations, setRecommendations] = useState([]);
  const [actionPlan, setActionPlan] = useState({ steps: [] });
  const [status, setStatus] = useState({ mode: "loading", sources: [] });
  const [layer, setLayer] = useState("aqi");

  useEffect(() => {
    Promise.all([
      fetch(`${API_BASE}/api/datasets`).then((res) => res.json()),
      fetch(`${API_BASE}/api/aqi/grid`).then((res) => res.json()),
      fetch(`${API_BASE}/api/hotspots`).then((res) => res.json()),
      fetch(`${API_BASE}/api/recommendations`).then((res) => res.json()),
      fetch(`${API_BASE}/api/live/status`).then((res) => res.json()),
      fetch(`${API_BASE}/api/action-plan`).then((res) => res.json()),
    ]).then(([datasetPayload, aqiPayload, hotspotPayload, recPayload, statusPayload, actionPayload]) => {
      setDatasets(datasetPayload);
      setAqi(aqiPayload);
      setHotspots(hotspotPayload);
      setRecommendations(recPayload);
      setStatus(statusPayload);
      setActionPlan(actionPayload);
    });
  }, []);

  const metrics = useMemo(() => {
    const values = aqi.features.map((feature) => feature.properties.predicted_aqi);
    const max = values.length ? Math.max(...values) : 0;
    const avg = values.length ? Math.round(values.reduce((sum, value) => sum + value, 0) / values.length) : 0;
    return { max, avg, hotspots: hotspots.features.length, sources: datasets.length };
  }, [aqi, hotspots, datasets]);

  return React.createElement(
    "div",
    { className: "app" },
    React.createElement(Sidebar, { datasets, recommendations, metrics, status, actionPlan }),
    React.createElement(
      "main",
      { className: "main" },
      React.createElement(
        "div",
        { className: "toolbar" },
        React.createElement("h2", null, "Surface NAQI and HCHO hotspot map"),
        React.createElement(
          "div",
          { className: "segmented", role: "tablist", "aria-label": "Map layers" },
          React.createElement("button", { className: layer === "aqi" ? "active" : "", onClick: () => setLayer("aqi") }, "NAQI"),
          React.createElement("button", { className: layer === "hotspots" ? "active" : "", onClick: () => setLayer("hotspots") }, "HCHO"),
        ),
      ),
      React.createElement(MapView, { aqi, hotspots, layer }),
    ),
  );
}

function Sidebar({ datasets, recommendations, metrics, status, actionPlan }) {
  return React.createElement(
    "aside",
    { className: "sidebar" },
    React.createElement(
      "div",
      { className: "brand" },
      React.createElement("h1", null, "AkashChalak"),
      React.createElement("span", null, "Satellite-assisted air quality decision support for India"),
    ),
    React.createElement(
      "div",
      { className: "metric-grid" },
      React.createElement(Metric, { label: "Avg NAQI", value: metrics.avg }),
      React.createElement(Metric, { label: "Peak NAQI", value: metrics.max }),
      React.createElement(Metric, { label: "Hotspots", value: metrics.hotspots }),
      React.createElement(Metric, { label: "Sources", value: metrics.sources }),
    ),
    React.createElement(
      "section",
      { className: "section" },
      React.createElement("h2", null, "Live Data Status"),
      React.createElement("div", { className: `live-mode ${status.mode}` }, status.mode.replaceAll("_", " ")),
      status.sources.map((source) =>
        React.createElement(
          "div",
          { className: "dataset", key: source.dataset_id },
          React.createElement("strong", null, source.dataset_id),
          React.createElement("div", { className: "muted" }, source.message),
          React.createElement("span", { className: "status" }, `${source.mode} - ${source.records} records`),
        ),
      ),
    ),
    React.createElement(
      "section",
      { className: "section" },
      React.createElement("h2", null, "Required Data Sources"),
      datasets.map((dataset) =>
        React.createElement(
          "div",
          { className: "dataset", key: dataset.id },
          React.createElement("strong", null, dataset.name),
          React.createElement("div", { className: "muted" }, `${dataset.provider} - ${dataset.variables.join(", ")}`),
          React.createElement("span", { className: "status" }, dataset.prototype_status),
        ),
      ),
    ),
    React.createElement(
      "section",
      { className: "section" },
      React.createElement("h2", null, "NAQI Reduction Action Plan"),
      React.createElement("div", { className: "muted" }, actionPlan.summary || "Waiting for live data."),
      actionPlan.steps && actionPlan.steps.length
        ? actionPlan.steps.slice(0, 8).map((item, index) =>
            React.createElement(
              "div",
              { className: "recommendation", key: `${item.region}-${item.timeframe}-${index}` },
              React.createElement("strong", null, `${item.timeframe} - ${item.region}`),
              React.createElement("div", { className: "muted" }, item.step),
              React.createElement("div", { className: "driver-list" }, item.trigger),
            ),
          )
        : null,
    ),
    React.createElement(
      "section",
      { className: "section" },
      React.createElement("h2", null, "Recommended Actions"),
      recommendations.length
        ? recommendations.slice(0, 6).map((item, index) =>
        React.createElement(
          "div",
          { className: "recommendation", key: `${item.region}-${index}` },
          React.createElement("strong", null, item.region),
          React.createElement("div", { className: "muted" }, item.action),
          React.createElement("div", { className: "driver-list" }, item.drivers.join(" / ")),
        ),
          )
        : React.createElement("div", { className: "muted" }, "No live NAQI records are available yet. Add API keys and refresh."),
    ),
  );
}

function Metric({ label, value }) {
  return React.createElement("div", { className: "metric" }, React.createElement("strong", null, value), React.createElement("span", { className: "muted" }, label));
}

function MapView({ aqi, hotspots, layer }) {
  const mapRef = React.useRef(null);
  const layerRef = React.useRef(null);

  useEffect(() => {
    if (mapRef.current) return;
    const map = L.map("map", { zoomControl: true }).setView([22.8, 80.5], 5);
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 18,
      attribution: "&copy; OpenStreetMap contributors",
    }).addTo(map);
    const legend = L.control({ position: "bottomright" });
    legend.onAdd = () => {
      const div = L.DomUtil.create("div", "legend");
      div.innerHTML = `
        <strong>NAQI</strong>
        <div><span class="swatch" style="background:#2e7d32"></span>Good (0-50)</div>
        <div><span class="swatch" style="background:#8a9a22"></span>Satisfactory (51-100)</div>
        <div><span class="swatch" style="background:#d7a100"></span>Moderate (101-200)</div>
        <div><span class="swatch" style="background:#c45616"></span>Poor (201-300)</div>
        <div><span class="swatch" style="background:#b42318"></span>Very Poor (301-400)</div>
        <div><span class="swatch" style="background:#6d3fc0"></span>Severe (401-500)</div>
      `;
      return div;
    };
    legend.addTo(map);
    mapRef.current = map;
  }, []);

  useEffect(() => {
    if (!mapRef.current) return;
    if (layerRef.current) layerRef.current.remove();
    const group = L.layerGroup();
    if (layer === "aqi") {
      aqi.features.forEach((feature) => {
        const p = feature.properties;
        const [lon, lat] = feature.geometry.coordinates;
        L.circleMarker([lat, lon], {
          radius: Math.max(8, Math.min(22, p.predicted_aqi / 14)),
          fillColor: aqiColor(p.predicted_aqi),
          color: "#1c2430",
          weight: 1,
          fillOpacity: 0.82,
        })
          .bindPopup(`<strong>${p.station || p.city}</strong><br>${p.city}<br>NAQI ${p.predicted_aqi} - ${p.category}<br>Dominant ${p.dominant_pollutant || "multi-source"}<br>Updated ${p.last_update || "demo"}`)
          .addTo(group);
      });
    } else {
      hotspots.features.forEach((feature) => {
        const p = feature.properties || {};
        const [lon, lat] = feature.geometry.coordinates || [];
        if (!Number.isFinite(lat) || !Number.isFinite(lon)) return;
        const locations = Array.isArray(p.locations) && p.locations.length ? p.locations.join(", ") : "Unknown location";
        const meanHcho = Number.isFinite(p.mean_hcho) ? p.mean_hcho : "N/A";
        const fireCount = Number.isFinite(p.fire_count) ? p.fire_count : "N/A";
        const marker = L.circleMarker([lat, lon], {
          radius: 18,
          fillColor: "#6d3fc0",
          color: "#1c2430",
          weight: 1,
          fillOpacity: 0.75,
        }).bindPopup(`<strong>${locations}</strong><br>HCHO ${meanHcho}<br>Fire count ${fireCount}<br>${p.likely_source || "source unknown"}`);
        marker.addTo(group);
        if (Number.isFinite(p.wind_u) && Number.isFinite(p.wind_v)) {
          L.polyline(
            [
              [lat, lon],
              [lat + p.wind_v * 0.25, lon + p.wind_u * 0.25],
            ],
            { color: "#6d3fc0", weight: 3 },
          ).addTo(group);
        }
      });
    }
    group.addTo(mapRef.current);
    layerRef.current = group;
  }, [aqi, hotspots, layer]);

  return React.createElement("div", { id: "map" });
}

ReactDOM.createRoot(document.getElementById("root")).render(React.createElement(App));
