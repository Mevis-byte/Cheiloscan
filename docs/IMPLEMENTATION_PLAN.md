# CheiloScan — Implementation Plan

**Status:** Phase 0 planning document (no implementation yet)
**Date:** 2026-11-11

---

## 1. Repository state after Phase 0 (inspection results)

- `/mnt/c/Users/MEVIS/Desktop/forensic` is **completely empty** — no source code,
  no configuration, no dependencies, no git history. Nothing to preserve or
  migrate; the "do not overwrite existing work" constraint is satisfied
  trivially, and no existing functionality exists to integrate.
- Environment (WSL2 / Kali Linux on Windows, working dir on `/mnt/c` drvfs):
  - System Python **3.14.7**, externally managed (PEP 668) → **venv required**.
  - `python3.11` available at `/home/Mevis/.local/bin/python3.11`.
  - `uv` available (venv + fast dependency resolution).
  - `git` 2.53.0 available; repo not yet initialized.
  - System-installed (not usable directly due to PEP 668): flask 3.1.3,
    numpy 2.4.6, scipy 1.17.1, pillow 12.3.0, werkzeug 3.1.9, pytest 9.1.1.
  - **Missing:** opencv-python, scikit-image, scikit-learn, SQLAlchemy, ReportLab.
  - Hardware: 12 CPUs; Windows drive only **8.1 GB free (97% full)** — storage
    monitoring required.
- Dependency set **verified at wheel level** for Python 3.11 and 3.14 via `uv
  pip install --dry-run` in a throwaway venv (nothing installed into the project).
  Full stack resolves with **no conflicts**; see §3.

**Decision: use Python 3.11 in a project venv managed by uv.** Rationale: 3.11
has the broadest historical wheel coverage for the scientific stack; 3.14 also
resolves today but is the newest interpreter (higher regression risk with
native wheels over time). Revisit if needed — both are verified working sets.

---

## 2. Target directory layout

See `ARCHITECTURE.md` §4 for the full module map. The plan below references those
modules. The `data/` directory is gitignored runtime state.

---

## 3. Dependencies (pinned, verified 2026-11-11)

Runtime:

| Package | Pinned | Notes |
|---|---|---|
| flask | 3.1.3 | HTTP layer |
| numpy | 2.4.6 | arrays everywhere |
| scipy | 1.17.1 | filters, stats, optimization |
| opencv-python-headless | 5.0.0.93 | CV core; headless variant for server use |
| scikit-image | 0.26.0 | GLCM, LBP, ridge filters, structure tensor |
| scikit-learn | 1.9.1 | PCA/descriptive stats; ML only with a real dataset |
| sqlalchemy | 2.1.8 | ORM, typed models |
| reportlab | 5.1.0 | PDF reports |

Dev/test: `pytest` 9.2.0 (+ transitive: pillow, werkzeug, jinja2, click,
imageio, tifffile, networkx, lazy-loader, joblib, threadpoolctl).

Conflict rules (must hold at all times):

1. Exactly **one** OpenCV distribution (`opencv-python-headless`). Never add
   `opencv-python` or `opencv-contrib-python` alongside it.
2. Bump the `scipy / scikit-image / scikit-learn` triple together.
3. All pins must remain NumPy-2-compatible.
4. Never install into system Python (`--break-system-packages` prohibited).

Version control: `pyproject.toml` (project metadata + pinned constraints) with a
`uv.lock` committed for reproducibility. Dependencies installed via
`uv pip install -e .` into `.venv`.

---

## 4. Implementation phases

Each phase ends with all tests green and a commit. Sizes are rough effort
estimates for a single experienced developer (S ≤ half day, M ≈ 1–2 days,
L ≈ 3–5 days).

### Phase 1 — Skeleton and environment (S) ← **starting point**

Goal: runnable, tested, empty application shell.

- `git init`, `.gitignore` (venv, `data/`, `__pycache__`, caches).
- `uv venv --python 3.11 .venv`; `pyproject.toml` with pinned deps; `uv pip install -e .`.
- Package skeleton: `app/` (factory, config, health blueprint),
  `cheiloscan/` (empty subpackages), `web/` (placeholder index page), `tests/`.
- `GET /api/v1/health` returns versions of every dependency + DB/storage status.
- Smoke test asserting OpenCV imports and `cv2.__version__` (catches the
  classic headless/libGL failure mode immediately).
- Import-rule test: `cheiloscan/` must not import `flask`.
- `pytest` configured (markers: `unit`, `integration`, `regression`).

**Acceptance:** `uv run pytest` green; `flask run` serves `/` and
`/api/v1/health`; dependency versions visible in health output.

### Phase 2 — Persistence and asset store (M)

Goal: durable storage with immutability guarantees.

- SQLAlchemy models for all six entities (`Sample`, `ImageAsset`,
  `AnalysisRun`, `FeatureSet`, `Comparison`, `Report`), typed, with
  `schema_version` table; `create_all` bootstrapping.
- Engine/session factory with WAL + foreign-keys pragmas.
- Repositories per aggregate (create/get/list/update-soft-delete).
- `AssetStore`: content-addressed `save_original` (dedupe, no overwrite),
  `save_derived` (run-namespaced), `open_read`, `sha256` verification.
- Health endpoint extended with storage usage readout.
- Integration tests against a temp data dir + temp SQLite (function-scoped).

**Acceptance:** upload-less CRUD via repositories works under pytest; original
overwrite attempt raises; hash-dedup proven by test.

### Phase 3 — Sample & image intake (M)

Goal: images enter the system safely.

- Validation service: format allowlist (PNG/JPEG), decode check, size/resolution
  floors, blur (Laplacian variance), luminance/contrast metrics; structured
  warnings/failures.
- `util/imageio`: safe decode to NumPy array, EXIF-orientation handling, format
  detection by content.
- Endpoints: `POST /samples`, `GET /samples`, `GET/PATCH/DELETE /samples/{id}`,
  `POST /samples/{id}/images`, `GET /assets/{id}`, `GET /assets/{id}/file`.
- Upload limits + JSON error envelope everywhere.
- Frontend: samples list, sample creation form, upload, thumbnail view.

**Acceptance:** integration tests cover happy path, oversized file, corrupt
image, duplicate upload (dedupe), and metadata validation errors.

### Phase 4 — Preprocessing and ROI detection (M–L)

Goal: normalized working images and a reliable lip-print region.

- Preprocessing service: grayscale, gentle denoise (bilateral), CLAHE,
  resolution normalization; all parameters explicit and overridable per run.
- ROI service with two strategies, chosen by sample `capture_type`:
  - `print_document` (lipstick print on paper/scan): Otsu threshold +
    morphology + largest-contour bbox, confidence score.
  - `photograph` (photo of lips): color-space lip detection (HSV/lab) —
    research-grade, expected to be unreliable; manual ROI fallback endpoint
    (`POST /runs/{id}/roi` accepting user-drawn bbox) is **mandatory** in this
    phase because automatic segmentation cannot be trusted.
- Derived assets recorded per stage (preprocessed, ROI crop, ROI mask overlay).
- Unit tests with synthetic fixtures: known geometric shapes on known
  backgrounds → expected bbox; blank/ambiguous inputs → low confidence flag.

**Acceptance:** a run on a fixture image produces recorded derived assets and
an ROI with confidence; manual override path tested.

### Phase 5 — Groove-pattern enhancement (M)

Goal: make groove lines measurable.

- Directional enhancement bank: Gabor filter bank over orientation set;
  scikit-image ridge filters (sato/frangi) as alternative stages; adaptive
  thresholding; optional skeletonization output.
- Stage results compared quantitatively in tests (synthetic sinusoidal ridge
  pattern at known angle/frequency → post-enhancement orientation and frequency
  recovery within tolerance).
- Derived assets: enhanced image, skeleton image.

**Acceptance:** enhancement stage is deterministic (golden-file regression),
recovers known synthetic ridge angle within ±5° and frequency within 10%.

### Phase 6 — Feature extraction (L)

Goal: measurable, versioned feature vectors.

- Feature families, each an independently tested module with a `feature_version`:
  - `orientation`: structure-tensor orientation histogram + mean coherence.
  - `ridge_frequency`: mean groove spatial frequency (FFT/autocorrelation).
  - `glcm`: contrast, correlation, energy, homogeneity (scikit-image
    graycomatrix) at set distances/angles.
  - `lbp`: rotation-invariant LBP histograms (uniform patterns).
  - `skeleton_stats`: groove density, node/branch counts, segment length stats.
- `FeatureSet` JSON document = {family: {metric: value}} + normalization
  metadata (which metrics are scale-normalized, and how).
- Runner integration: pipeline `baseline_v1` = preprocess → roi → enhance →
  features; runs recorded end-to-end.
- scikit-learn PCA endpoint for *descriptive* feature-space exploration
  (labeled as exploratory, no classifier).

**Acceptance:** golden-file feature JSON for two fixed synthetic fixtures;
per-family unit tests against hand-computable small arrays (e.g., 4×4 GLCM
reference values).

### Phase 7 — Comparison engine (M)

Goal: pairwise scoring with honest semantics.

- Registration: phase correlation (translation) and ECC refinement on enhanced
  ROIs; quality/confidence output; graceful failure recorded.
- Metrics: cosine similarity and normalized Euclidean on standardized feature
  vectors; NCC and SSIM on aligned enhanced ROIs.
- Fusion `heuristic_fusion_v1`: fixed, documented weights over normalized
  components (weights in code constants, cited in report). No learned weights,
  no thresholds, no "match" verdicts.
- Endpoint `POST /comparisons`, `GET /comparisons{,/{id}}`.
- Frontend: compare page — pick two runs, side-by-side images, component score
  table, fused score with disclaimer.

**Acceptance:** identical-input comparison scores high; two distinct synthetic
fixtures score lower (sanity only, **not** an accuracy claim — documented as
such in the test docstrings); all scores stored with method version.

### Phase 8 — Reporting (M)

Goal: research-grade PDF outputs.

- `report_data`: assembles provenance (pipeline versions, params, asset hashes),
  component scores, feature summaries, methodology summary, disclaimer block.
- ReportLab renderer: A4, tables, embedded images (original, ROI, enhanced),
  footer with CheiloScan version + "experimental research tool" statement.
- Endpoints: `POST /comparisons/{id}/report`, `GET /reports/{id}`, download.
- Frontend: reports list + download links.

**Acceptance:** generated PDF exists, contains required sections, sha256 stored;
test asserts the disclaimer text is present in the PDF (text extraction).

### Phase 9 — Hardening and release prep (M)

Goal: research-usable v0.1.

- Storage housekeeping: usage readout, orphaned-derived-asset check, optional
  sample export (archive of originals + reports).
- Regression suite finalized; documentation pass (README, run instructions).
- Config audit; security review of upload path; final risk review against
  `SCIENTIFIC_METHODOLOGY.md`.

**Acceptance:** fresh-clone bootstrap (venv → install → run → smoke test) works
from documentation alone.

---

## 5. Phase 1 — exact starting point

The first implementation session should execute, in order:

```bash
cd /mnt/c/Users/MEVIS/Desktop/forensic
git init
# write .gitignore (see below)
uv venv --python 3.11 .venv
# write pyproject.toml (pinned deps from §3)
uv pip install --python .venv/bin/python -e .
```

Files created in Phase 1 (contents specified in `ARCHITECTURE.md`):

1. `.gitignore` — `.venv/`, `data/`, `__pycache__/`, `*.pyc`, `.pytest_cache/`,
   `dist/`, `uv.lock` **kept** (committed for reproducibility).
2. `pyproject.toml` — project metadata, pinned dependencies, pytest config
   (markers `unit`, `integration`, `regression`).
3. `app/__init__.py` (factory), `app/config.py`, `app/api/health.py`.
4. `cheiloscan/__init__.py` + empty subpackage inits.
5. `web/index.html` placeholder.
6. `tests/conftest.py`, `tests/unit/test_health.py`,
   `tests/unit/test_import_rules.py`, `tests/unit/test_opencv_smoke.py`.
7. `run.py` (dev entrypoint).

First commit message convention: conventional commits, e.g.
`feat: phase 1 - project skeleton, environment, health endpoint`.

**Exit criteria for Phase 1** (verify before declaring done):
`uv run pytest` passes; `flask --app app run` (or `run.py`) serves `/` and
`/api/v1/health` on 127.0.0.1; health lists actual dependency versions; git
history initialized with initial commit.

---

## 6. Risk register (engineering)

| # | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| R1 | Automatic lip-region segmentation is unreliable on real prints (porous paper, uneven lipstick) | High | Feature quality garbage-in | Mandatory manual-ROI fallback (Phase 4); confidence scores; ROI stored as derived asset for audit |
| R2 | No dataset → no accuracy validation possible | Certain | Over-claiming risk | Language guards in code/UI/reports; component scores only; no thresholds; documented in methodology |
| R3 | Disk exhaustion on `/mnt/c` (~8.1 GB free) | Medium | Data loss/service failure | Storage usage in health endpoint; compressed derived artifacts; documented ext4 relocation option |
| R4 | drvfs (9p) IO slowness for SQLite + many files | Medium | Poor UX | Configurable data dir; benchmark in Phase 2; move to ext4 if needed |
| R5 | OpenCV 5.x API drift vs 4.x documentation habits | Medium | Rework | Smoke test in Phase 1; pin exact version; verify each API at first use |
| R6 | numpy 2.x incompatibility creeping in via later bumps | Low | Import errors | Version pins + lockfile; upgrade discipline (§3 rules) |
| R7 | Lip prints = biometric-adjacent personal data | — | Privacy | Local-only storage, anonymized donor refs, consent flag, no network |
| R8 | Sync processing blocking Flask requests if images grow | Low | Timeouts | Runs are first-class with status; background thread pool is a drop-in later; API shape unchanged |
| R9 | WSL/Windows path interop surprises (`C:` access, file locks) | Low | File store errors | Content-addressed naming; no file locking relied upon beyond SQLite WAL |

---

## 7. Unresolved technical questions (open before/at Phase 1)

1. **Primary capture modality** — lipstick prints on paper (scans/photos) vs
   photographs of lips? Affects ROI strategy priority and validation thresholds.
   Default plan: support both via `capture_type` with manual fallback; confirm
   with researcher in Phase 3–4.
2. **Image formats** — PNG/JPEG first; is TIFF (scanner output) needed early?
3. **Background of expected images** — controlled (scanner, dark background) vs
   uncontrolled (phone photos on random surfaces)? Drives validation thresholds.
4. **Async processing** — keep synchronous until measured run times exceed
   ~10 s (unlikely for single ROI crops); agree threshold.
5. **Alembic now vs later** — plan defers it; revisit at first schema change.
6. **1:N screening** (one sample vs many) — deferred by design; only 1:1 in
   scope. Confirm this remains acceptable.
7. **UI depth** — vanilla JS pages as planned, or add a lightweight lib (htmx)
   if the compare/report UX becomes unwieldy? Default: stay dependency-free.
8. **Where the data directory should live** (`./data` on drvfs vs ext4) —
   benchmark in Phase 2, decide with data.

---

## 8. Realism self-check

- Phases 1–3 (skeleton, persistence, intake) are conventional and low-risk.
- Phases 4–6 carry the research uncertainty (segmentation, enhancement, features);
  each has a manual/explicit fallback and synthetic-fixture tests so failure is
  measurable, not silent.
- Phase 7's fusion is deliberately trivial (fixed weights) — the honest
  alternative to ML with no dataset.
- Phase 8–9 are mechanical.
- Total rough effort: ~2.5–4 weeks of focused single-developer time, with
  Phases 4–6 dominating the uncertainty.
