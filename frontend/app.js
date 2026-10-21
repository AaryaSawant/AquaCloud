
"use strict";

/* ==========================================================
   AQUACLOUD — WATER INTELLIGENCE DASHBOARD
   File: frontend/app.js

   AWS API:
     GET  /dashboard
     POST /export

   No AWS credentials or API keys are stored in this file.
   ========================================================== */

const API_STORAGE_KEY = "aquacloud_api_url";

const DEFAULT_API_URL =
  "https://t2813qa1jl.execute-api.ap-south-1.amazonaws.com/prod";

const BUILDINGS = [
  {
    id: "ACAD-A",
    name: "Academic Block A",
    type: "Classrooms",
    sensor: "WTR-ACAD-A-01",
    normalMin: 10,
    normalMax: 25,
    maxFlow: 40,
    icon: "⌂"
  },
  {
    id: "LAB-1",
    name: "Computer Lab 1",
    type: "Laboratory",
    sensor: "WTR-LAB-1-01",
    normalMin: 8,
    normalMax: 20,
    maxFlow: 35,
    icon: "⌘"
  },
  {
    id: "LIB",
    name: "Central Library",
    type: "Library",
    sensor: "WTR-LIB-01",
    normalMin: 5,
    normalMax: 15,
    maxFlow: 28,
    icon: "▤"
  },
  {
    id: "HOSTEL-A",
    name: "Hostel A",
    type: "Hostel",
    sensor: "WTR-HOSTEL-A-01",
    normalMin: 20,
    normalMax: 45,
    maxFlow: 70,
    icon: "⌂"
  },
  {
    id: "ADMIN",
    name: "Admin Block",
    type: "Administration",
    sensor: "WTR-ADMIN-01",
    normalMin: 5,
    normalMax: 12,
    maxFlow: 22,
    icon: "▣"
  }
];

const state = {
  apiUrl: localStorage.getItem(API_STORAGE_KEY) || DEFAULT_API_URL,
  mode: "loading",
  selectedBuilding: "LAB-1",
  tableFilter: "all",
  summary: null,
  buildings: [],
  readings: [],
  leaks: [],
  generatedAt: null,
  loading: false,
  exporting: false
};

const $ = (id) => document.getElementById(id);

const escapeHTML = (value) =>
  String(value ?? "").replace(/[&<>"']/g, (character) => {
    const replacements = {
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;"
    };
    return replacements[character];
  });

const number = (value, digits = 1) => {
  const parsed = Number(value);
  return Number.isFinite(parsed)
    ? parsed.toFixed(digits)
    : "—";
};

function parseTimestamp(value) {
  if (!value) return null;

  const date = new Date(value);

  return Number.isNaN(date.getTime())
    ? null
    : date;
}

function formatTime(value) {
  const date = parseTimestamp(value);

  if (!date) return "—";

  return date.toLocaleString("en-IN", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    hour12: true
  });
}

function formatShortTime(value) {
  const date = parseTimestamp(value);

  if (!date) return "—";

  return date.toLocaleTimeString("en-IN", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false
  });
}

function formatRelativeTime(value) {
  const date = parseTimestamp(value);

  if (!date) return "Unknown";

  const difference = Math.max(
    0,
    Date.now() - date.getTime()
  );

  const minutes = Math.floor(difference / 60000);

  if (minutes < 1) return "Just now";
  if (minutes < 60) return `${minutes} min ago`;

  const hours = Math.floor(minutes / 60);

  if (hours < 24) return `${hours} hr ago`;

  const days = Math.floor(hours / 24);

  return `${days} day${days === 1 ? "" : "s"} ago`;
}

function normalizeStatus(value) {
  return String(value || "").toUpperCase();
}

function isLeak(reading) {
  return normalizeStatus(reading?.status).includes("LEAK");
}

function isNormal(reading) {
  return normalizeStatus(reading?.status) === "NORMAL";
}

function getBuilding(id) {
  return (
    state.buildings.find((building) => building.building_id === id) ||
    BUILDINGS.find((building) => building.id === id) ||
    null
  );
}

function buildingName(id) {
  const building = getBuilding(id);

  return building?.name || id || "Unknown building";
}

function buildingLimit(building) {
  return Number(
    building?.max_flow_lpm ??
    building?.maxFlow ??
    0
  );
}

function buildingSensor(building) {
  return building?.sensor_id || building?.sensor || "—";
}

function getLatest(building) {
  return building?.latest || null;
}

function getReadingTime(reading) {
  return reading?.sensor_ts || reading?.ts || null;
}

function normalizeApiUrl(value) {
  const trimmed = String(value || "").trim();

  if (!trimmed) return "";

  const url = new URL(trimmed);

  if (!["https:", "http:"].includes(url.protocol)) {
    throw new Error("API URL must use HTTP or HTTPS.");
  }

  return url.href.replace(/\/+$/, "");
}

function setText(id, value) {
  const element = $(id);

  if (element) element.textContent = value;
}

/* ==========================================================
   NOTIFICATIONS
   ========================================================== */

let toastTimeout = null;

function showToast(message, isError = false) {
  const toast = $("toast");

  if (!toast) return;

  clearTimeout(toastTimeout);

  toast.textContent = message;
  toast.className = `toast show${isError ? " error" : ""}`;

  toastTimeout = setTimeout(() => {
    toast.classList.remove("show");
  }, 4200);
}

/* ==========================================================
   API REQUESTS
   ========================================================== */

async function apiRequest(path, options = {}) {
  if (!state.apiUrl) {
    throw new Error("No API URL configured.");
  }

  const authHeaders = AquaAuth.headers(state.apiUrl);
  const controller = new AbortController();

  const timeout = setTimeout(() => {
    controller.abort();
  }, 15000);

  try {
    const response = await fetch(
      `${state.apiUrl}${path}`,
      {
        ...options,
        signal: controller.signal,
        redirect: "error",
        credentials: "omit",
        cache: "no-store",
        headers: {
          "Content-Type": "application/json",
          ...(options.headers || {}),
          ...authHeaders
        }
      }
    );

    const rawText = await response.text();

    let payload;

    try {
      payload = rawText ? JSON.parse(rawText) : {};
    } catch {
      payload = { message: rawText };
    }

    if (response.status === 401) { AquaAuth.clear(); updateAuthUI(); clearCloudData(); }
    if (!response.ok) {
      const message =
        payload?.message ||
        payload?.error ||
        response.statusText ||
        "Request failed";

      throw new Error(
        `HTTP ${response.status}: ${message}`
      );
    }

    return payload;
  } catch (error) {
    if (error.name === "AbortError") {
      throw new Error("The API request timed out.");
    }

    throw error;
  } finally {
    clearTimeout(timeout);
  }
}

/* ==========================================================
   DASHBOARD DATA NORMALIZATION
   ========================================================== */

function normalizeDashboard(payload) {
  if (!payload || typeof payload !== "object") {
    throw new Error("Invalid dashboard response.");
  }

  if (
    !payload.summary ||
    !Array.isArray(payload.buildings) ||
    !Array.isArray(payload.recent_readings) ||
    !Array.isArray(payload.leaks)
  ) {
    throw new Error(
      "The API response is missing required dashboard fields."
    );
  }

  const buildingMap = new Map(
    payload.buildings.map((building) => [
      building.building_id,
      building
    ])
  );

  const buildings = BUILDINGS.map((fallback) => {
    const cloud = buildingMap.get(fallback.id) || {};

    return {
      building_id: fallback.id,
      name: cloud.name || fallback.name,
      type: cloud.type || fallback.type,
      sensor_id: cloud.sensor_id || fallback.sensor,
      normal_min_lpm:
        cloud.normal_min_lpm ?? fallback.normalMin,
      normal_max_lpm:
        cloud.normal_max_lpm ?? fallback.normalMax,
      max_flow_lpm:
        cloud.max_flow_lpm ?? fallback.maxFlow,
      latest: cloud.latest || null
    };
  });

  const sortNewest = (a, b) => {
    const aTime =
      parseTimestamp(a.ts)?.getTime() || 0;

    const bTime =
      parseTimestamp(b.ts)?.getTime() || 0;

    return bTime - aTime;
  };

  return {
    summary: payload.summary,
    buildings,
    readings: [...payload.recent_readings].sort(sortNewest),
    leaks: [...payload.leaks].sort(sortNewest),
    generatedAt: payload.generated_at || null
  };
}

/* ==========================================================
   DEMO MODE

   Only used when the user explicitly clears the API URL.
   Live API failures never silently switch to demo mode.
   ========================================================== */

function createDemoData() {
  const now = Date.now();

  const readings = [];

  BUILDINGS.forEach((building, buildingIndex) => {
    const midpoint =
      (building.normalMin + building.normalMax) / 2;

    for (let i = 0; i < 8; i++) {
      const timestamp = new Date(
        now - (7 - i) * 60000 - buildingIndex * 300
      ).toISOString();

      const variation =
        Math.sin(i * 1.7 + buildingIndex) * 1.8;

      let flow = midpoint + variation;

      let status = "NORMAL";
      let reasons = [];

      if (building.id === "LAB-1" && i === 5) {
        flow = 52.02;
        status = "LEAK DETECTED";
        reasons = [
          "THRESHOLD: Flow exceeded configured limit."
        ];
      }

      readings.push({
        building_id: building.id,
        sensor_id: building.sensor,
        ts: timestamp,
        sensor_ts: timestamp,
        flow_lpm: Number(flow.toFixed(2)),
        status,
        reasons,
        baseline_lpm: Number(midpoint.toFixed(2))
      });
    }
  });

  readings.sort(
    (a, b) =>
      new Date(b.ts).getTime() -
      new Date(a.ts).getTime()
  );

  const buildings = BUILDINGS.map((building) => ({
    building_id: building.id,
    name: building.name,
    type: building.type,
    sensor_id: building.sensor,
    normal_min_lpm: building.normalMin,
    normal_max_lpm: building.normalMax,
    max_flow_lpm: building.maxFlow,
    latest:
      readings.find(
        (reading) => reading.building_id === building.id
      ) || null
  }));

  const leaks = readings.filter(isLeak);

  const totalFlow = buildings.reduce(
    (sum, building) =>
      sum + Number(building.latest?.flow_lpm || 0),
    0
  );

  return {
    summary: {
      total_buildings: buildings.length,
      active_sensors: buildings.filter(
        (building) => building.latest
      ).length,
      total_flow_lpm: totalFlow,
      leak_count: leaks.length,
      readings_count: readings.length
    },
    buildings,
    readings,
    leaks,
    generatedAt: new Date().toISOString()
  };
}

function applyDashboard(data) {
  state.summary = data.summary;
  state.buildings = data.buildings;
  state.readings = data.readings;
  state.leaks = data.leaks;
  state.generatedAt = data.generatedAt;

  renderDashboard();
}

function loadDemo() {
  state.mode = "demo";

  applyDashboard(createDemoData());

  updateConnectionStatus();
}

/* ==========================================================
   LIVE REFRESH
   ========================================================== */

async function refreshDashboard(showSuccess = false) {
  if (state.loading) return;
  if (state.apiUrl && !AquaAuth.signedIn()) {
    clearCloudData();
    updateAuthUI();
    return;
  }

  if (!state.apiUrl) {
    loadDemo();
    return;
  }

  state.loading = true;

  const refreshButton = $("refresh-button");

  if (refreshButton) {
    refreshButton.disabled = true;
    refreshButton.querySelector("span").textContent =
      "Refreshing...";
  }

  try {
    const payload = await apiRequest("/dashboard");

    // A request may finish after the user signs out or the token expires.
    if (!AquaAuth.signedIn()) { clearCloudData(); updateAuthUI(); return; }
    const normalized = normalizeDashboard(payload);

    state.mode = "live";

    applyDashboard(normalized);

    updateConnectionStatus();

    if (showSuccess) {
      showToast("Live cloud readings refreshed.");
    }
  } catch (error) {
    console.error("AquaCloud API error:", error);

    state.mode = "error";

    updateConnectionStatus();

    showToast(
      `Cloud connection failed: ${error.message}`,
      true
    );
  } finally {
    state.loading = false;

    if (refreshButton) {
      refreshButton.disabled = false;
      refreshButton.querySelector("span").textContent =
        "Refresh";
    }
  }
}

/* ==========================================================
   CONNECTION STATUS
   ========================================================== */

function updateConnectionStatus() {
  const dot = $("cloud-dot");
  const pill = document.querySelector(".live-pill");

  dot?.classList.remove("connected");
  pill?.classList.remove("demo");

  if (state.mode === "live") {
    dot?.classList.add("connected");

    setText("connection-label", "API connected");
    setText(
      "connection-description",
      "Connected to AWS API Gateway and receiving dashboard data."
    );
    setText("top-status", "LIVE CLOUD");
    setText("footer-mode", "AWS cloud data");
  } else if (state.mode === "demo") {
    pill?.classList.add("demo");

    setText("connection-label", "Demo mode");
    setText(
      "connection-description",
      "Displaying simulated sample data. Configure your API to use AWS."
    );
    setText("top-status", "DEMO DATA");
    setText("footer-mode", "Simulated demo data");
  } else if (state.mode === "error") {
    setText("connection-label", "Connection error");
    setText(
      "connection-description",
      "Unable to refresh cloud data. Previously loaded readings are retained."
    );
    setText("top-status", "API ERROR");
    setText("footer-mode", "Connection error");
  } else if (state.mode === "signed-out") {
    setText("connection-label", "Sign-in required");
    setText("connection-description", "Sign in with your AquaCloud account to load cloud readings.");
    setText("top-status", "SIGNED OUT");
    setText("footer-mode", "Sign-in required");
  } else {
    setText("connection-label", "Connecting...");
    setText(
      "connection-description",
      "Checking AWS API Gateway."
    );
    setText("top-status", "CONNECTING");
  }
}

/* ==========================================================
   KPI METRICS
   ========================================================== */

function renderMetrics() {
  const summary = state.summary || {};

  setText(
    "metric-buildings",
    String(summary.total_buildings ?? state.buildings.length)
      .padStart(2, "0")
  );

  setText(
    "metric-sensors",
    String(summary.active_sensors ?? 0).padStart(2, "0")
  );

  setText(
    "metric-flow",
    number(summary.total_flow_lpm ?? 0, 1)
  );

  setText(
    "metric-alerts",
    String(summary.leak_count ?? state.leaks.length)
      .padStart(2, "0")
  );

  setText(
    "nav-alert-count",
    String(summary.leak_count ?? state.leaks.length)
  );

  setText(
    "alert-count-tag",
    `${summary.leak_count ?? state.leaks.length} EVENTS`
  );

  $("alert-count-tag")?.classList.toggle(
    "has-alerts",
    (summary.leak_count ?? state.leaks.length) > 0
  );

  setText(
    "alert-foot",
    "Historical detections returned by API"
  );

  setText(
    "sensor-foot",
    "Buildings with reported readings"
  );
}

/* ==========================================================
   BUILDING SELECTION
   ========================================================== */

function renderBuildingOptions() {
  const chartSelect = $("chart-building");
  const tableSelect = $("building-filter");

  if (chartSelect) {
    chartSelect.innerHTML = state.buildings
      .map(
        (building) => `
          <option value="${escapeHTML(building.building_id)}">
            ${escapeHTML(building.name)}
          </option>
        `
      )
      .join("");

    if (
      !state.buildings.some(
        (building) =>
          building.building_id === state.selectedBuilding
      )
    ) {
      state.selectedBuilding =
        state.buildings[0]?.building_id || "LAB-1";
    }

    chartSelect.value = state.selectedBuilding;
  }

  if (tableSelect) {
    tableSelect.innerHTML = `
      <option value="all">All buildings</option>
      ${state.buildings
        .map(
          (building) => `
            <option value="${escapeHTML(building.building_id)}">
              ${escapeHTML(building.name)}
            </option>
          `
        )
        .join("")}
    `;

    tableSelect.value = state.tableFilter;
  }
}

function selectBuilding(id) {
  state.selectedBuilding = id;

  const select = $("chart-building");

  if (select) select.value = id;

  renderBuildingCards();
  renderChart();

  document.querySelector(".flow-panel")?.scrollIntoView({
    behavior: "smooth",
    block: "start"
  });
}

/* ==========================================================
   BUILDING CARDS
   ========================================================== */

function renderBuildingCards() {
  const container = $("building-grid");

  if (!container) return;

  setText(
    "building-count",
    `${String(state.buildings.length).padStart(2, "0")} LOCATIONS`
  );

  container.innerHTML = state.buildings
    .map((building) => {
      const latest = getLatest(building);

      const leak = latest && isLeak(latest);

      const limit = buildingLimit(building);

      const flow = latest
        ? Number(latest.flow_lpm)
        : null;

      const percentage =
        flow !== null && limit > 0
          ? Math.min(100, (flow / limit) * 100)
          : 0;

      const selected =
        building.building_id === state.selectedBuilding;

      const statusClass = !latest
        ? "no-data"
        : leak
          ? "leak"
          : "normal";

      const statusText = !latest
        ? "NO DATA"
        : leak
          ? "LEAK"
          : "NORMAL";

      const icon =
        BUILDINGS.find(
          (item) => item.id === building.building_id
        )?.icon || "⌂";

      return `
        <button
          type="button"
          class="building-card
            ${leak ? "leaking" : ""}
            ${selected ? "selected" : ""}"
          data-building="${escapeHTML(building.building_id)}"
          aria-label="View ${escapeHTML(building.name)} analytics"
        >
          <div class="building-top">
            <span class="building-symbol">${icon}</span>
            <span class="status-badge ${statusClass}">
              ${statusText}
            </span>
          </div>

          <h3>${escapeHTML(building.name)}</h3>

          <div class="building-id">
            ${escapeHTML(building.building_id)}
          </div>

          <div class="building-flow">
            ${flow === null ? "—" : number(flow, 1)}
            <small>L/min</small>
          </div>

          <div class="building-caption">
            Latest reported flow
          </div>

          <div class="mini-track">
            <span style="width:${percentage}%"></span>
          </div>

          <div class="building-details">
            <span>
              Limit:
              <strong>${number(limit, 1)} L/min</strong>
            </span>
            <span>
              Sensor:
              <strong>${escapeHTML(buildingSensor(building))}</strong>
            </span>
            <span>
              Updated:
              <strong>
                ${latest
                  ? escapeHTML(formatRelativeTime(latest.ts))
                  : "No readings"}
              </strong>
            </span>
          </div>
        </button>
      `;
    })
    .join("");

  container.querySelectorAll("[data-building]").forEach(
    (button) => {
      button.addEventListener("click", () => {
        selectBuilding(button.dataset.building);
      });
    }
  );
}

/* ==========================================================
   BUILDING-SPECIFIC FLOW CHART
   ========================================================== */

function getBuildingReadings(id) {
  return state.readings
    .filter((reading) => reading.building_id === id)
    .sort(
      (a, b) =>
        (parseTimestamp(a.ts)?.getTime() || 0) -
        (parseTimestamp(b.ts)?.getTime() || 0)
    );
}

function svgElement(tag, attributes = {}, text = null) {
  const namespace = "http://www.w3.org/2000/svg";

  const element = document.createElementNS(
    namespace,
    tag
  );

  Object.entries(attributes).forEach(([key, value]) => {
    element.setAttribute(key, String(value));
  });

  if (text !== null) {
    element.textContent = String(text);
  }

  return element;
}

function renderChart() {
  const svg = $("flow-chart");

  if (!svg) return;

  svg.replaceChildren();

  const building = getBuilding(state.selectedBuilding);

  const readings = getBuildingReadings(
    state.selectedBuilding
  ).slice(-30);

  const latest = building?.latest || null;

  const limit = buildingLimit(building);

  const baselineValue = latest?.baseline_lpm;

  const baseline =
    baselineValue !== null &&
    baselineValue !== undefined &&
    Number.isFinite(Number(baselineValue))
      ? Number(baselineValue)
      : null;

  const values = readings
    .map((reading) => Number(reading.flow_lpm))
    .filter(Number.isFinite);

  const peak = values.length
    ? Math.max(...values)
    : null;

  setText(
    "chart-current",
    latest
      ? `${number(latest.flow_lpm, 2)} L/min`
      : "No reading"
  );

  setText(
    "chart-subtitle",
    `${building?.name || "Selected building"} · Latest reading`
  );

  setText(
    "chart-limit",
    limit > 0 ? `${number(limit, 1)} L/min` : "—"
  );

  setText(
    "chart-baseline",
    baseline !== null
      ? `${number(baseline, 2)} L/min`
      : "Not established"
  );

  setText(
    "chart-peak",
    peak !== null
      ? `${number(peak, 2)} L/min`
      : "—"
  );

  setText(
    "chart-samples",
    String(readings.length)
  );

  if (!readings.length) {
    svg.appendChild(
      svgElement(
        "text",
        {
          x: 350,
          y: 125,
          fill: "#90a5b8",
          "text-anchor": "middle",
          "font-size": 13
        },
        "No recent readings for this building"
      )
    );

    return;
  }

  const width = 700;
  const height = 250;

  const margin = {
    top: 18,
    right: 20,
    bottom: 35,
    left: 46
  };

  const chartWidth =
    width - margin.left - margin.right;

  const chartHeight =
    height - margin.top - margin.bottom;

  const maxValue = Math.max(
    10,
    limit,
    baseline || 0,
    ...values
  );

  const yMax = Math.ceil(maxValue * 1.2 / 10) * 10;

  const x = (index) => {
    if (readings.length === 1) {
      return margin.left + chartWidth / 2;
    }

    return (
      margin.left +
      (index / (readings.length - 1)) * chartWidth
    );
  };

  const y = (value) =>
    margin.top +
    chartHeight -
    (value / yMax) * chartHeight;

  /* Grid and Y-axis labels */

  for (let i = 0; i <= 4; i++) {
    const value = (yMax / 4) * i;
    const position = y(value);

    svg.appendChild(
      svgElement("line", {
        x1: margin.left,
        y1: position,
        x2: width - margin.right,
        y2: position,
        stroke: "#294056",
        "stroke-width": 1,
        "stroke-dasharray": "3 5"
      })
    );

    svg.appendChild(
      svgElement(
        "text",
        {
          x: margin.left - 10,
          y: position + 4,
          fill: "#90a5b8",
          "font-size": 10,
          "text-anchor": "end"
        },
        number(value, 0)
      )
    );
  }

  /* Configured flow limit */

  if (limit > 0) {
    svg.appendChild(
      svgElement("line", {
        x1: margin.left,
        y1: y(limit),
        x2: width - margin.right,
        y2: y(limit),
        stroke: "#ff727e",
        "stroke-width": 1.7,
        "stroke-dasharray": "7 5"
      })
    );
  }

  /* Baseline */

  if (baseline !== null) {
    svg.appendChild(
      svgElement("line", {
        x1: margin.left,
        y1: y(baseline),
        x2: width - margin.right,
        y2: y(baseline),
        stroke: "#ffbc70",
        "stroke-width": 1.5,
        "stroke-dasharray": "4 5"
      })
    );
  }

  /* Main flow line */

  const points = readings.map((reading, index) => ({
    x: x(index),
    y: y(Number(reading.flow_lpm)),
    reading
  }));

  const linePath = points
    .map(
      (point, index) =>
        `${index === 0 ? "M" : "L"} ${point.x} ${point.y}`
    )
    .join(" ");

  if (points.length > 1) {
    const areaPath = [
      linePath,
      `L ${points[points.length - 1].x} ${y(0)}`,
      `L ${points[0].x} ${y(0)}`,
      "Z"
    ].join(" ");

    const defs = svgElement("defs");

    const gradient = svgElement(
      "linearGradient",
      {
        id: "flowGradient",
        x1: "0",
        y1: "0",
        x2: "0",
        y2: "1"
      }
    );

    gradient.appendChild(
      svgElement("stop", {
        offset: "0%",
        "stop-color": "#50e1cc",
        "stop-opacity": 0.24
      })
    );

    gradient.appendChild(
      svgElement("stop", {
        offset: "100%",
        "stop-color": "#50e1cc",
        "stop-opacity": 0
      })
    );

    defs.appendChild(gradient);
    svg.appendChild(defs);

    svg.appendChild(
      svgElement("path", {
        d: areaPath,
        fill: "url(#flowGradient)"
      })
    );

    svg.appendChild(
      svgElement("path", {
        d: linePath,
        fill: "none",
        stroke: "#50e1cc",
        "stroke-width": 2.5,
        "stroke-linecap": "round",
        "stroke-linejoin": "round"
      })
    );
  }

  /* Reading markers */

  points.forEach((point) => {
    const leak = isLeak(point.reading);

    const circle = svgElement("circle", {
      cx: point.x,
      cy: point.y,
      r: leak ? 5 : 3.2,
      fill: leak ? "#ff727e" : "#50e1cc",
      stroke: "#102235",
      "stroke-width": 2
    });

    circle.appendChild(
      svgElement(
        "title",
        {},
        `${formatTime(point.reading.ts)}
${number(point.reading.flow_lpm, 2)} L/min
${point.reading.status}`
      )
    );

    svg.appendChild(circle);
  });

  /* Time labels */

  const labelIndices = [
    0,
    Math.floor((readings.length - 1) / 2),
    readings.length - 1
  ];

  [...new Set(labelIndices)].forEach((index) => {
    svg.appendChild(
      svgElement(
        "text",
        {
          x: x(index),
          y: height - 10,
          fill: "#90a5b8",
          "font-size": 10,
          "text-anchor": "middle"
        },
        formatShortTime(readings[index].ts)
      )
    );
  });
}

/* ==========================================================
   LEAK ALERT HISTORY
   ========================================================== */

function classifySeverity(reading) {
  const building = getBuilding(reading.building_id);

  const limit = buildingLimit(building);

  const flow = Number(reading.flow_lpm);

  if (!limit || !Number.isFinite(flow)) {
    return "DETECTED";
  }

  const ratio = flow / limit;

  if (ratio >= 1.5) return "HIGH";
  if (ratio >= 1.2) return "ELEVATED";

  return "DETECTED";
}

function renderLeaks() {
  const container = $("leak-list");

  if (!container) return;

  if (!state.leaks.length) {
    container.innerHTML = `
      <div class="empty-state">
        <strong>No leak events in the returned history</strong>
        New detected leaks will appear here when reported
        by the cloud API.
      </div>
    `;
    return;
  }

  container.innerHTML = state.leaks
    .slice(0, 20)
    .map((reading) => {
      const reasons = Array.isArray(reading.reasons)
        ? reading.reasons
        : [];

      const explanation = reasons.length
        ? reasons.join(" · ")
        : "Abnormal flow detected by the cloud processor.";

      return `
        <article class="leak-card">
          <div class="leak-symbol">!</div>

          <div class="leak-info">
            <h3>
              ${escapeHTML(buildingName(reading.building_id))}
              <span class="severity-tag">
                ${escapeHTML(classifySeverity(reading))}
              </span>
            </h3>

            <p>${escapeHTML(explanation)}</p>

            <div class="leak-meta">
              <span>
                FLOW: ${number(reading.flow_lpm, 2)} L/min
              </span>

              <span>
                SENSOR: ${escapeHTML(reading.sensor_id)}
              </span>

              <span>
                ${escapeHTML(formatTime(reading.ts))}
              </span>
            </div>
          </div>
        </article>
      `;
    })
    .join("");
}

/* ==========================================================
   RECENT SENSOR READINGS
   ========================================================== */

function renderReadings() {
  const tbody = $("readings-body");

  if (!tbody) return;

  const filtered = state.readings.filter(
    (reading) =>
      state.tableFilter === "all" ||
      reading.building_id === state.tableFilter
  );

  setText(
    "table-count",
    `${filtered.length} reading${filtered.length === 1 ? "" : "s"} shown`
  );

  if (!filtered.length) {
    tbody.innerHTML = `
      <tr>
        <td colspan="6" class="muted-cell">
          No readings available for this selection.
        </td>
      </tr>
    `;
    return;
  }

  tbody.innerHTML = filtered
    .slice(0, 100)
    .map((reading) => {
      const leak = isLeak(reading);

      const baseline =
        reading.baseline_lpm === null ||
        reading.baseline_lpm === undefined
          ? "—"
          : number(reading.baseline_lpm, 2);

      return `
        <tr>
          <td>
            <strong>
              ${escapeHTML(buildingName(reading.building_id))}
            </strong>
          </td>

          <td class="sensor-id">
            ${escapeHTML(reading.sensor_id)}
          </td>

          <td class="flow-cell">
            ${number(reading.flow_lpm, 2)} L/min
          </td>

          <td>${baseline}</td>

          <td>
            <span class="status-badge ${leak ? "leak" : ""}">
              ${leak ? "LEAK DETECTED" : "NORMAL"}
            </span>
          </td>

          <td class="timestamp">
            ${escapeHTML(formatTime(reading.ts))}
          </td>
        </tr>
      `;
    })
    .join("");
}

/* ==========================================================
   DASHBOARD RENDER
   ========================================================== */

function renderDashboard() {
  renderMetrics();
  renderBuildingOptions();
  renderBuildingCards();
  renderChart();
  renderLeaks();
  renderReadings();

  setText(
    "last-updated",
    state.generatedAt
      ? formatTime(state.generatedAt)
      : "—"
  );

  setText(
    "current-date",
    new Date().toLocaleDateString("en-IN", {
      day: "2-digit",
      month: "short",
      year: "numeric"
    }).toUpperCase()
  );
}

/* ==========================================================
   S3 REPORT EXPORT
   ========================================================== */

async function exportReport() {
  if (state.exporting) return;
  if (!AquaAuth.canExport()) { showToast("Operator or Admin access is required to export.", true); return; }

  if (!state.apiUrl || state.mode === "demo") {
    showToast(
      "S3 export requires a live AWS API connection.",
      true
    );
    return;
  }

  const button = $("export-button");

  state.exporting = true;

  if (button) {
    button.disabled = true;
    button.querySelector("span").textContent =
      "Exporting...";
  }

  try {
    const response = await apiRequest("/export", {
      method: "POST",
      body: JSON.stringify({})
    });

    // The response contains object paths only. No public object URLs are created.

    showToast(
      "Report export completed. Check your AquaCloud S3 bucket."
    );
  } catch (error) {
    console.error("Export failed:", error);

    showToast(
      `Report export failed: ${error.message}`,
      true
    );
  } finally {
    state.exporting = false;

    if (button) {
      button.disabled = !AquaAuth.canExport();
      button.querySelector("span").textContent =
        "Export report";
    }
  }
}

/* ==========================================================
   API CONFIGURATION
   ========================================================== */

function openApiDialog() {
  const dialog = $("api-dialog");

  if (!dialog) return;

  $("api-url").value = state.apiUrl || "";

  dialog.showModal();
}

async function saveApiConfiguration(event) {
  event.preventDefault();

  const dialog = $("api-dialog");

  const raw = $("api-url").value.trim();

  try {
    const normalized = normalizeApiUrl(raw);

    state.apiUrl = normalized;

    if (normalized) {
      localStorage.setItem(
        API_STORAGE_KEY,
        normalized
      );
    } else {
      localStorage.removeItem(API_STORAGE_KEY);
    }

    dialog.close();

    if (normalized) {
      await refreshDashboard(true);
    } else {
      loadDemo();

      showToast(
        "Demo mode enabled. Data is simulated."
      );
    }
  } catch (error) {
    showToast(
      `Invalid API URL: ${error.message}`,
      true
    );
  }
}

/* ==========================================================
   EVENT LISTENERS
   ========================================================== */

function initializeEvents() {
  $("cancel-api")?.addEventListener("click", () => $("api-dialog").close());
  $("refresh-button")?.addEventListener(
    "click",
    () => refreshDashboard(true)
  );

  $("export-button")?.addEventListener(
    "click",
    exportReport
  );

  $("configure-api")?.addEventListener(
    "click",
    openApiDialog
  );

  $("api-form")?.addEventListener(
    "submit",
    saveApiConfiguration
  );

  $("chart-building")?.addEventListener(
    "change",
    (event) => {
      state.selectedBuilding = event.target.value;

      renderBuildingCards();
      renderChart();
    }
  );

  $("building-filter")?.addEventListener(
    "change",
    (event) => {
      state.tableFilter = event.target.value;

      renderReadings();
    }
  );

  document.querySelectorAll(".nav-link").forEach(
    (link) => {
      link.addEventListener("click", () => {
        document.querySelectorAll(".nav-link").forEach(
          (item) => item.classList.remove("active")
        );

        link.classList.add("active");
      });
    }
  );
}

/* ==========================================================
   INITIALIZATION
   ========================================================== */

async function initializeApp() {
  initializeEvents();
  $("login-button").addEventListener("click", () => AquaAuth.login().catch(error => showToast(error.message, true)));
  $("logout-button").addEventListener("click", () => { clearCloudData(); AquaAuth.logout(); });
  try { await AquaAuth.initialize(); } catch (error) { showToast(error.message, true); }
  updateAuthUI();

  updateConnectionStatus();

  if (state.apiUrl) {
    await refreshDashboard();
  } else {
    loadDemo();
  }

  // Refresh live data every 30 seconds.
  // Does not replace live data with demo data on failure.

  setInterval(() => {
    if (
      AquaAuth.signedIn() &&
      state.apiUrl &&
      state.mode !== "demo" &&
      !state.loading
    ) {
      refreshDashboard(false);
    }
  }, 30000);
}

document.addEventListener(
  "DOMContentLoaded",
  initializeApp
);


function clearCloudData() {
  state.summary = null;
  state.buildings = [];
  state.readings = [];
  state.leaks = [];
  state.generatedAt = null;
  state.mode = "signed-out";
  renderDashboard();
  updateConnectionStatus();
}
function updateAuthUI() {
  const signedIn = AquaAuth.signedIn();
  $("auth-status").textContent = signedIn ? `Signed in: ${AquaAuth.role()}` : AquaAuth.configured() ? "Sign in to view cloud data" : "Cognito setup pending";
  $("login-button").hidden = signedIn;
  $("login-button").disabled = !AquaAuth.configured();
  $("logout-button").hidden = !signedIn;
  $("export-button").disabled = !AquaAuth.canExport();
}
setInterval(() => {
  if (!AquaAuth.signedIn()) {
    updateAuthUI();
    if (state.mode !== "demo" && state.mode !== "signed-out") clearCloudData();
  }
}, 1000);
