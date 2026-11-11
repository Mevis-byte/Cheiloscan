/* CheiloScan frontend logic. Vanilla JS only, no external dependencies. */

"use strict";

/* ---------- Small helpers ---------- */

const $ = (selector) => document.querySelector(selector);

function formatBytes(bytes) {
  if (bytes === 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  const value = bytes / Math.pow(1024, index);
  return `${value.toFixed(value >= 10 || index === 0 ? 0 : 1)} ${units[index]}`;
}

function formatTimestamp(iso) {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleString();
}

async function apiGet(path) {
  const response = await fetch(path, { headers: { Accept: "application/json" } });
  if (!response.ok) {
    let message = `HTTP ${response.status}`;
    try {
      const body = await response.json();
      if (body && body.error && body.error.message) message = body.error.message;
    } catch (_) { /* envelope absent; keep status message */ }
    throw new Error(message);
  }
  return response.json();
}

function showLoadError(message) {
  const el = $("#load-error");
  if (!el) return;
  el.textContent = `Failed to load data: ${message}`;
  el.classList.remove("hidden");
}

function setEmptyState(visible) {
  const el = $("#empty-state");
  if (el) el.classList.toggle("hidden", !visible);
}

/* ---------- Pages ---------- */

async function initDashboard() {
  let stats;
  try {
    stats = await apiGet("/api/dashboard/stats");
  } catch (error) {
    showLoadError(error.message);
    return;
  }

  $("#stat-samples").textContent = String(stats.samples.total);
  $("#stat-samples-active").textContent = `active: ${stats.samples.active}`;
  $("#stat-images").textContent = String(stats.images.total);
  $("#stat-analyses").textContent = String(stats.analyses.total);
  $("#stat-analyses-breakdown").textContent = breakdownText(stats.analyses.by_status);
  $("#stat-comparisons").textContent = String(stats.comparisons.total);
  $("#stat-comparisons-breakdown").textContent = breakdownText(stats.comparisons.by_status);
  $("#stat-storage").textContent = formatBytes(stats.storage.bytes);

  const generated = $("#generated-at");
  if (generated) generated.textContent = `Updated ${formatTimestamp(stats.generated_at)}.`;

  const nothingRecorded =
    stats.samples.total === 0 &&
    stats.images.total === 0 &&
    stats.analyses.total === 0 &&
    stats.comparisons.total === 0;
  setEmptyState(nothingRecorded);
}

function breakdownText(byStatus) {
  const keys = Object.keys(byStatus);
  if (keys.length === 0) return "no runs yet";
  return keys.map((key) => `${key}: ${byStatus[key]}`).join(" · ");
}

async function initSamples() {
  let data;
  try {
    data = await apiGet("/api/samples");
  } catch (error) {
    showLoadError(error.message);
    return;
  }

  const tbody = $("#samples-tbody");
  for (const sample of data.items) {
    const row = document.createElement("tr");
    row.innerHTML = `
      <td class="mono">${escapeHtml(sample.code)}</td>
      <td>${escapeHtml(sample.capture_type ?? "—")}</td>
      <td>${escapeHtml(sample.medium ?? "—")}</td>
      <td>${sample.consent_confirmed ? "confirmed" : "no"}</td>
      <td>${sample.image_count}</td>
      <td>${sample.analyses_count}</td>
      <td>${formatTimestamp(sample.created_at)}</td>`;
    tbody.appendChild(row);
  }
  setEmptyState(data.total === 0);
}

async function initComparisons() {
  let data;
  try {
    data = await apiGet("/api/comparisons");
  } catch (error) {
    showLoadError(error.message);
    return;
  }

  const tbody = $("#comparisons-tbody");
  for (const comparison of data.items) {
    const row = document.createElement("tr");
    row.innerHTML = `
      <td class="mono">${escapeHtml(comparison.sample_a ? comparison.sample_a.code : "—")}</td>
      <td class="mono">${escapeHtml(comparison.sample_b ? comparison.sample_b.code : "—")}</td>
      <td>${escapeHtml(comparison.method)}</td>
      <td>${escapeHtml(comparison.status)}</td>
      <td>${formatTimestamp(comparison.created_at)}</td>`;
    tbody.appendChild(row);
  }
  setEmptyState(data.total === 0);
}

function escapeHtml(value) {
  const div = document.createElement("div");
  div.textContent = String(value);
  return div.innerHTML;
}

/* ---------- Boot ---------- */

const PAGES = {
  dashboard: initDashboard,
  samples: initSamples,
  comparisons: initComparisons,
  analyses: null, // honest placeholder; analysis listing arrives with the pipeline
};

document.addEventListener("DOMContentLoaded", () => {
  const init = PAGES[document.body.dataset.page];
  if (init) init();
});
