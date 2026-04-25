/**
 * PREDICTA – Chart Initialization Module
 * All Chart.js chart configurations for the industrial dashboard.
 */

Chart.defaults.color = "#6b7280";
Chart.defaults.borderColor = "rgba(255,255,255,0.06)";
Chart.defaults.font.family = "'Inter', sans-serif";

const ACCENT  = "#00d4ff";
const GREEN   = "#00ff88";
const YELLOW  = "#ffd700";
const RED     = "#ff4444";
const ORANGE  = "#ff8c00";
const PURPLE  = "#a855f7";

function makeGradient(ctx, colorTop, colorBottom) {
  const g = ctx.createLinearGradient(0, 0, 0, 300);
  g.addColorStop(0, colorTop);
  g.addColorStop(1, colorBottom);
  return g;
}

function initCharts() {
  // ── Current & Voltage Trend ─────────────────────────────────────────────
  const cvCtx = document.getElementById("chart-current-voltage").getContext("2d");
  chartCV = new Chart(cvCtx, {
    type: "line",
    data: {
      labels: [],
      datasets: [
        {
          label: "Current (A)",
          data: [], yAxisID: "yA",
          borderColor: ACCENT,
          backgroundColor: makeGradient(cvCtx, "rgba(0,212,255,0.2)", "rgba(0,212,255,0)"),
          tension: 0.4, fill: true, pointRadius: 0, borderWidth: 2,
        },
        {
          label: "Voltage /100 (V)",
          data: [], yAxisID: "yV",
          borderColor: PURPLE,
          backgroundColor: "rgba(168,85,247,0)",
          tension: 0.4, fill: false, pointRadius: 0, borderWidth: 1.5,
          borderDash: [4, 4],
        }
      ]
    },
    options: {
      animation: false,
      responsive: true,
      interaction: { mode: "index", intersect: false },
      scales: {
        x:  { grid: { display: false }, ticks: { maxTicksLimit: 8, font: { size: 10 } } },
        yA: {
          position: "left", title: { display: true, text: "Current (A)", font: { size: 10 } },
          ticks: { font: { size: 10 } }
        },
        yV: {
          position: "right", title: { display: true, text: "V/100", font: { size: 10 } },
          grid: { drawOnChartArea: false }, ticks: { font: { size: 10 } }
        }
      },
      plugins: { legend: { labels: { font: { size: 11 }, boxWidth: 12 } } }
    }
  });

  // ── Temperature Trend ───────────────────────────────────────────────────
  const tCtx = document.getElementById("chart-temperature").getContext("2d");
  chartTemp = new Chart(tCtx, {
    type: "line",
    data: {
      labels: [],
      datasets: [
        {
          label: "Motor Temp °C",
          data: [], borderColor: ORANGE,
          backgroundColor: makeGradient(tCtx, "rgba(255,140,0,0.25)", "rgba(255,140,0,0)"),
          tension: 0.4, fill: true, pointRadius: 0, borderWidth: 2,
        },
        {
          label: "Bearing Temp °C",
          data: [], borderColor: RED,
          backgroundColor: "rgba(255,68,68,0)",
          tension: 0.4, fill: false, pointRadius: 0, borderWidth: 1.5,
        }
      ]
    },
    options: {
      animation: false, responsive: true,
      plugins: { legend: { labels: { font: { size: 10 }, boxWidth: 10 } } },
      scales: {
        x: { grid: { display: false }, ticks: { maxTicksLimit: 6, font: { size: 9 } } },
        y: { ticks: { font: { size: 10 } } }
      }
    }
  });

  // ── Vibration Chart ─────────────────────────────────────────────────────
  const vCtx = document.getElementById("chart-vibration").getContext("2d");
  chartVib = new Chart(vCtx, {
    type: "line",
    data: {
      labels: [],
      datasets: [{
        label: "Vibration (g RMS)",
        data: [], borderColor: GREEN,
        backgroundColor: makeGradient(vCtx, "rgba(0,255,136,0.2)", "rgba(0,255,136,0)"),
        tension: 0.3, fill: true, pointRadius: 0, borderWidth: 2,
      }]
    },
    options: {
      animation: false, responsive: true,
      plugins: { legend: { labels: { font: { size: 10 }, boxWidth: 10 } } },
      scales: {
        x: { grid: { display: false }, ticks: { maxTicksLimit: 6, font: { size: 9 } } },
        y: { min: 0, ticks: { font: { size: 10 } } }
      }
    }
  });

  // ── Radar / Spider Chart (Parameter Health) ─────────────────────────────
  const rCtx = document.getElementById("chart-radar").getContext("2d");
  chartRadar = new Chart(rCtx, {
    type: "radar",
    data: {
      labels: ["Voltage", "Current", "Temp", "Vibration", "RPM", "Efficiency"],
      datasets: [{
        label: "Health %",
        data: [90, 85, 88, 92, 95, 87],
        borderColor: ACCENT,
        backgroundColor: "rgba(0,212,255,0.15)",
        pointBackgroundColor: ACCENT,
        pointRadius: 4,
        borderWidth: 2,
      }]
    },
    options: {
      responsive: true,
      scales: {
        r: {
          beginAtZero: true, max: 100,
          ticks: { stepSize: 25, font: { size: 9 }, backdropColor: "transparent" },
          grid: { color: "rgba(255,255,255,0.08)" },
          pointLabels: { font: { size: 10 } },
          angleLines: { color: "rgba(255,255,255,0.08)" }
        }
      },
      plugins: { legend: { display: false } }
    }
  });

  // ── Fault Probability Bar Chart ─────────────────────────────────────────
  const fpCtx = document.getElementById("chart-fault-prob").getContext("2d");
  chartFaultProb = new Chart(fpCtx, {
    type: "bar",
    data: {
      labels: ["Normal", "Bearing", "Overheat", "Overcurrent", "Vibration", "Cooling", "Power"],
      datasets: [{
        label: "Probability (%)",
        data: [92, 2, 1.5, 1, 1.5, 1, 1],
        backgroundColor: [GREEN, ORANGE, RED, ORANGE, YELLOW, ACCENT, PURPLE],
        borderRadius: 6,
        borderWidth: 0,
      }]
    },
    options: {
      responsive: true, indexAxis: "y",
      plugins: { legend: { display: false } },
      scales: {
        x: { max: 100, ticks: { font: { size: 9 } } },
        y: { ticks: { font: { size: 9 } } }
      }
    }
  });
}
