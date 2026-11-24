/* CheiloScan frontend logic. Vanilla JS only, no external dependencies. */

"use strict";

/* ---------- Small helpers ---------- */

const $ = (selector) => document.querySelector(selector);

function formatBytes(bytes) {
  if (!bytes || bytes <= 0) return "0 B";
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

function escapeHtml(value) {
  const div = document.createElement("div");
  div.textContent = value === null || value === undefined ? "" : String(value);
  // textContent->innerHTML escapes &, < and > but not quotes; escape those
  // too so the same helper is safe in double- and single-quoted attributes.
  return div.innerHTML.replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

function encodeSegment(value) {
  return encodeURIComponent(value === null || value === undefined ? "" : String(value));
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

function describeError(error) {
  let text = error.message || "request failed";
  if (error.details) {
    if (error.details.existing_sample_code) {
      text += ` (already uploaded as sample ${error.details.existing_sample_code})`;
    }
    if (Array.isArray(error.details.errors)) {
      text += `: ${error.details.errors.join("; ")}`;
    }
  }
  return text;
}

/* ---------- HTTP ---------- */

async function parseError(response) {
  let body = null;
  try {
    body = await response.json();
  } catch (_) {
    /* no JSON body */
  }
  const payload = body && body.error ? body.error : {};
  const error = new Error(payload.message || `HTTP ${response.status}`);
  error.status = response.status;
  error.code = payload.code;
  error.details = payload.details;
  error.body = body;
  return error;
}

async function apiGet(path) {
  const response = await fetch(path, { headers: { Accept: "application/json" } });
  if (!response.ok) throw await parseError(response);
  return response.json();
}

async function apiPostJson(path, payload) {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify(payload || {}),
  });
  if (!response.ok) throw await parseError(response);
  return response.json();
}

async function apiUpload(formData) {
  const response = await fetch("/api/samples/upload", {
    method: "POST",
    headers: { Accept: "application/json" },
    body: formData,
  });
  if (!response.ok) throw await parseError(response);
  return response.json();
}

/* ---------- Dashboard ---------- */

function breakdownText(byStatus) {
  const keys = Object.keys(byStatus || {});
  if (keys.length === 0) return "no runs yet";
  return keys.map((key) => `${key}: ${byStatus[key]}`).join(" · ");
}

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

/* ---------- Samples + upload ---------- */

let selectedFile = null;

function setSelectedFile(file) {
  selectedFile = file || null;
  const label = $("#file-selected");
  const submit = $("#upload-submit");
  if (!label || !submit) return;
  if (selectedFile) {
    label.textContent = `${selectedFile.name} · ${formatBytes(selectedFile.size)}`;
    label.classList.remove("hidden");
  } else {
    label.textContent = "";
    label.classList.add("hidden");
  }
  submit.disabled = !selectedFile;
}

function initUpload() {
  const dropzone = $("#dropzone");
  const input = $("#file-input");
  const form = $("#upload-form");
  if (!dropzone || !input || !form) return;

  dropzone.addEventListener("click", () => input.click());
  dropzone.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      input.click();
    }
  });
  input.addEventListener("change", () => setSelectedFile(input.files[0]));

  for (const type of ["dragenter", "dragover"]) {
    dropzone.addEventListener(type, (event) => {
      event.preventDefault();
      dropzone.classList.add("dragging");
    });
  }
  for (const type of ["dragleave", "drop"]) {
    dropzone.addEventListener(type, (event) => {
      event.preventDefault();
      dropzone.classList.remove("dragging");
    });
  }
  dropzone.addEventListener("drop", (event) => {
    const file = event.dataTransfer && event.dataTransfer.files
      ? event.dataTransfer.files[0]
      : null;
    if (file) setSelectedFile(file);
  });

  form.addEventListener("reset", () => {
    setSelectedFile(null);
    const status = $("#upload-status");
    if (status) status.classList.add("hidden");
  });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!selectedFile) return;
    const submit = $("#upload-submit");
    const status = $("#upload-status");
    submit.disabled = true;
    submit.textContent = "Uploading…";
    if (status) status.classList.add("hidden");

    const data = new FormData();
    data.append("file", selectedFile, selectedFile.name);
    for (const element of form.elements) {
      if (!element.name) continue;
      if (element.type === "checkbox") {
        if (element.checked) data.append(element.name, "true");
      } else if (element.value) {
        data.append(element.name, element.value);
      }
    }

    try {
      const result = await apiUpload(data);
      renderUploadResult(result);
      form.reset();
      setSelectedFile(null);
      await loadSamplesTable();
    } catch (error) {
      if (status) {
        status.className = "alert alert-error";
        status.textContent = describeError(error);
        status.classList.remove("hidden");
      }
    } finally {
      submit.textContent = "Upload";
      submit.disabled = !selectedFile;
    }
  });
}

function renderUploadResult(result) {
  const status = $("#upload-status");
  if (!status) return;
  const warnings = result.warnings || [];
  const warningHtml = warnings.length
    ? `<div class="warnings"><strong>Quality warnings — the image was accepted, not rejected</strong>
         <ul>${warnings
           .map(
             (warning) =>
               `<li><span class="mono">${escapeHtml(warning.code)}</span> — ${escapeHtml(
                 warning.message
               )} <span class="hint">measured ${warning.measured} ${escapeHtml(
                 warning.unit
               )}, threshold ${warning.threshold}</span></li>`
           )
           .join("")}</ul></div>`
    : `<p class="hint">No quality warnings were raised for this image.</p>`;

  status.className = "upload-result";
  status.classList.remove("hidden");
  status.innerHTML = `
    <div class="upload-result-head">
      <img class="thumb" src="${result.asset.file_url}" alt="Uploaded original image">
      <div>
        <div><strong>${escapeHtml(result.sample.code)}</strong> uploaded</div>
        <div class="hint">${result.asset.width}×${result.asset.height} px ·
          ${escapeHtml(result.asset.format)} · ${formatBytes(result.asset.size_bytes)}</div>
        <div class="hint mono">sha256 ${escapeHtml(result.asset.sha256)}</div>
      </div>
    </div>
    ${warningHtml}
    <div class="actions">
      <button type="button" class="button button-primary" id="process-uploaded">
        Process this image
      </button>
    </div>`;

  const button = $("#process-uploaded");
  if (button) {
    button.addEventListener("click", () => processSample(result.sample.id, button));
  }
}

async function loadSamplesTable() {
  let data;
  try {
    data = await apiGet("/api/samples");
  } catch (error) {
    showLoadError(error.message);
    return;
  }

  const tbody = $("#samples-tbody");
  if (!tbody) return;
  tbody.innerHTML = "";
  for (const sample of data.items) {
    const originals = (sample.images || []).filter((image) => image.kind === "original");
    const image = originals.length ? originals[originals.length - 1] : null;
    const row = document.createElement("tr");
    row.innerHTML = `
      <td>${image
        ? `<img class="thumb-sm" src="${image.file_url}" alt="Original image for ${escapeHtml(sample.code)}" loading="lazy">`
        : "—"}</td>
      <td class="mono">${escapeHtml(sample.code)}</td>
      <td>${escapeHtml(sample.capture_type ?? "—")}</td>
      <td>${sample.consent_confirmed ? "confirmed" : "no"}</td>
      <td>${sample.image_count}</td>
      <td>${sample.analyses_count}</td>
      <td>${formatTimestamp(sample.created_at)}</td>
      <td><button type="button" class="button button-sm" data-process="${escapeHtml(sample.id)}"
        ${image ? "" : "disabled"}>Process</button></td>`;
    tbody.appendChild(row);
  }

  tbody.querySelectorAll("[data-process]").forEach((button) => {
    button.addEventListener("click", () => processSample(button.dataset.process, button));
  });
  setEmptyState(data.total === 0);
}

async function processSample(sampleId, button) {
  if (!sampleId) return;
  const originalLabel = button ? button.textContent : "";
  if (button) {
    button.disabled = true;
    button.textContent = "Processing…";
  }
  try {
    const result = await apiPostJson(`/api/analysis/${encodeSegment(sampleId)}/process`, {});
    window.location.href = `/analysis/${encodeSegment(result.analysis.id)}`;
  } catch (error) {
    const analysisId = error.details && error.details.analysis_id;
    if (analysisId) {
      window.location.href = `/analysis/${encodeSegment(analysisId)}`;
      return;
    }
    if (button) {
      button.disabled = false;
      button.textContent = originalLabel;
    }
    showLoadError(describeError(error));
  }
}

async function initSamples() {
  initUpload();
  await loadSamplesTable();
}

/* ---------- Analyses list ---------- */

async function initAnalyses() {
  let data;
  try {
    data = await apiGet("/api/analyses");
  } catch (error) {
    showLoadError(error.message);
    return;
  }

  const tbody = $("#analyses-tbody");
  for (const run of data.items) {
    const row = document.createElement("tr");
    row.innerHTML = `
      <td class="mono">${escapeHtml(run.sample ? run.sample.code : "—")}</td>
      <td><span class="status status-${escapeHtml(run.status)}">${escapeHtml(run.status)}</span></td>
      <td>${escapeHtml(run.pipeline_name)} v${escapeHtml(run.pipeline_version)}</td>
      <td>${run.artifact_count}</td>
      <td>${formatTimestamp(run.created_at)}</td>
      <td><a class="button button-sm" href="/analysis/${encodeSegment(run.id)}">Open</a></td>`;
    tbody.appendChild(row);
  }
  setEmptyState(data.total === 0);
}

/* ---------- Analysis detail ---------- */

const STAGE_LABELS = {
  original: "Original",
  grayscale: "Grayscale",
  denoised: "Denoised",
  illumination_corrected: "Illumination corrected",
  contrast_enhanced: "Enhanced",
  final: "Final",
};

function renderPreviewCard(label, fileUrl, stage, extra) {
  const note = stage && stage.skipped
    ? `<div class="hint">passthrough (operation disabled)</div>`
    : stage
      ? `<div class="hint mono">${escapeHtml(stage.operation)}</div>`
      : "";
  return `
    <figure class="preview-card">
      <img src="${fileUrl}" alt="${escapeHtml(label)} image" loading="lazy">
      <figcaption>
        <strong>${escapeHtml(label)}</strong>
        ${extra ? `<div class="hint">${extra}</div>` : ""}
        ${note}
      </figcaption>
    </figure>`;
}

function qualityRows(quality) {
  if (!quality) return "";
  const exposure = quality.exposure || {};
  return `
    <tr><td>Resolution</td><td>${quality.width}×${quality.height} px (${quality.megapixels} MP)</td></tr>
    <tr><td>Blur (Laplacian variance)</td><td>${quality.blur.laplacian_variance}</td></tr>
    <tr><td>Brightness (mean)</td><td>${quality.brightness.mean}</td></tr>
    <tr><td>Contrast (std)</td><td>${quality.contrast.std}</td></tr>
    <tr><td>Clipped exposure</td><td>${(exposure.clipped_fraction * 100).toFixed(2)}%
      (low ${(exposure.clipped_low_fraction * 100).toFixed(2)}%,
       high ${(exposure.clipped_high_fraction * 100).toFixed(2)}%)</td></tr>`;
}

function warningsBlock(warnings) {
  if (!warnings || warnings.length === 0) {
    return `<p class="hint">No warnings.</p>`;
  }
  return `<ul class="warning-list">${warnings
    .map(
      (warning) =>
        `<li><span class="mono">${escapeHtml(warning.code)}</span> — ${escapeHtml(
          warning.message
        )}</li>`
    )
    .join("")}</ul>`;
}

async function initAnalysis() {
  const id = window.location.pathname.split("/").filter(Boolean).pop();
  if (!id) {
    showLoadError("missing analysis id in URL");
    return;
  }

  let data;
  try {
    data = await apiGet(`/api/analysis/${encodeSegment(id)}`);
  } catch (error) {
    showLoadError(describeError(error));
    return;
  }

  const run = data.analysis;
  const results = run.results || null;

  const statusEl = $("#run-status");
  statusEl.textContent = run.status;
  statusEl.className = `badge status status-${run.status}`;

  const meta = $("#run-meta");
  meta.innerHTML = `
    <div class="meta-grid">
      <div><span class="hint">Sample</span><div class="mono">${escapeHtml(
        data.sample ? data.sample.code : run.sample_id
      )}</div></div>
      <div><span class="hint">Run id</span><div class="mono">${escapeHtml(run.id)}</div></div>
      <div><span class="hint">Pipeline</span><div>${escapeHtml(
        run.pipeline_name
      )} v${escapeHtml(run.pipeline_version)}</div></div>
      <div><span class="hint">Started</span><div>${formatTimestamp(run.started_at)}</div></div>
      <div><span class="hint">Finished</span><div>${formatTimestamp(run.finished_at)}</div></div>
    </div>`;

  if (run.error) {
    const errorEl = $("#run-error");
    errorEl.textContent = `Run failed: ${run.error}`;
    errorEl.classList.remove("hidden");
  }

  const stageByRole = {};
  for (const stage of (results && results.stages) || []) {
    stageByRole[stage.role] = stage;
  }
  const artifactByRole = {};
  for (const artifact of data.artifacts || []) {
    artifactByRole[artifact.role] = artifact;
  }

  const cards = [];
  if (run.input_asset_id) {
    cards.push(
      renderPreviewCard(
        STAGE_LABELS.original,
        `/api/assets/${run.input_asset_id}/file`,
        null,
        results && results.input
          ? `${results.input.width}×${results.input.height} px · ${escapeHtml(results.input.format)}`
          : ""
      )
    );
  }
  for (const role of ["grayscale", "denoised", "illumination_corrected", "contrast_enhanced", "final"]) {
    const artifact = artifactByRole[role];
    if (!artifact) continue;
    cards.push(
      renderPreviewCard(
        STAGE_LABELS[role] || role,
        artifact.file_url,
        stageByRole[role],
        `${artifact.width}×${artifact.height} px · ${escapeHtml(artifact.format)}`
      )
    );
  }
  $("#preview-grid").innerHTML = cards.length
    ? cards.join("")
    : `<p class="hint">No preview images were produced for this run.</p>`;

  const qualityPanel = $("#quality-panel");
  if (results && results.quality_before) {
    qualityPanel.innerHTML = `
      <div class="quality-columns">
        <div>
          <h3>Before processing</h3>
          <table class="data-table compact"><tbody>${qualityRows(
            results.quality_before
          )}</tbody></table>
          ${warningsBlock(results.quality_before.warnings)}
        </div>
        <div>
          <h3>After processing</h3>
          <table class="data-table compact"><tbody>${qualityRows(
            results.quality_after
          )}</tbody></table>
          ${warningsBlock(results.quality_after.warnings)}
        </div>
      </div>
      <p class="hint">
        Thresholds are experimental and configurable; warnings describe image
        quality, not identity or match confidence.
      </p>`;
  } else {
    qualityPanel.innerHTML = `<p class="hint">No quality measurements were recorded for this run.</p>`;
  }

  const paramsPanel = $("#params-panel");
  if (results) {
    const timings = Object.entries(results.timings_ms || {})
      .map(([key, value]) => `<tr><td>${escapeHtml(key)}</td><td>${value} ms</td></tr>`)
      .join("");
    const notes = (results.notes || [])
      .map((note) => `<li>${escapeHtml(note)}</li>`)
      .join("");
    paramsPanel.innerHTML = `
      <div class="quality-columns">
        <div>
          <h3>Parameters used</h3>
          <pre class="code-block">${escapeHtml(JSON.stringify(results.params, null, 2))}</pre>
        </div>
        <div>
          <h3>Stage timing</h3>
          <table class="data-table compact"><tbody>${timings}</tbody></table>
          ${notes ? `<h3>Notes</h3><ul>${notes}</ul>` : ""}
        </div>
      </div>`;
  } else {
    paramsPanel.innerHTML = `<pre class="code-block">${escapeHtml(
      JSON.stringify(run.params || {}, null, 2)
    )}</pre>`;
  }
}

/* ---------- Comparisons ---------- */

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

/* ---------- Boot ---------- */

const PAGES = {
  dashboard: initDashboard,
  samples: initSamples,
  analyses: initAnalyses,
  analysis: initAnalysis,
  comparisons: initComparisons,
};

document.addEventListener("DOMContentLoaded", () => {
  const init = PAGES[document.body.dataset.page];
  if (init) init();
});
