# CheiloScan — Architecture

**Status:** Phase 0 planning document (no implementation yet)
**Date:** 2026-11-11
**Scope:** Automated lip-print analysis and comparison — *experimental research tool*

---

## 1. Purpose and positioning

CheiloScan is a **local-first forensic research application** that ingests lip-print
images, validates and preprocesses them, isolates the lip-print region, enhances
visible groove patterns, extracts measurable texture and directional features,
compares pairs of samples, and produces research reports.

**CheiloScan is not a biometric identification system.** Cheiloscopy (lip-print
analysis) is not a validated method for individual identification in forensic
practice. Every score, report, and UI surface produced by this system must be
treated as a descriptive research measurement, never as evidence of identity.
See `SCIENTIFIC_METHODOLOGY.md` for the scientific constraints behind this.

### Non-goals

- No cloud services, no network calls at runtime, no paid APIs.
- No claim of validated matching accuracy (no error-rate statistics without data).
- No multi-user authentication/authorization in the first iteration (single
  researcher, local machine). Network exposure is explicitly out of scope.
- No modification of original images, ever.
- No fabrication of research data: synthetic imagery exists **only** inside the
  test suite and is labeled as such; it is never stored as or presented as a sample.

---

## 2. Guiding principles

1. **Local-first.** All processing, storage, and reporting happen on the local
   machine. The app runs offline.
2. **Original immutability.** Uploaded files are stored content-addressed and
   byte-frozen. Every later artifact is a *derived* asset recorded with its full
   provenance chain.
3. **Reproducibility.** Every analysis run snapshots the pipeline name, version,
   and exact parameters. Re-running a stored run on the same input must produce
   the same feature set (deterministic algorithms, pinned seeds).
4. **Modular, independently testable services.** Image processing stages are
   pure-ish classes operating on NumPy arrays; they do not touch the database,
   filesystem, or HTTP layer directly.
5. **Honest outputs.** Comparison results are reported as component scores plus a
   clearly-labeled heuristic fused score. No probabilistic "match" language.
6. **Minimal dependencies.** Only the approved stack (Flask, OpenCV, NumPy, SciPy,
   scikit-image, scikit-learn, SQLAlchemy, ReportLab, pytest). No frontend build
   toolchain, no CDNs (offline-capable vanilla HTML/CSS/JS).

---

## 3. System overview

```
┌──────────────────────────────────────────────────────────────────────┐
│                    Web UI  (web/, static, no build step)              │
│     upload samples · view runs/artifacts · compare pairs · reports     │
└───────────────────────────────┬──────────────────────────────────────┘
                                │  HTTP (JSON + multipart uploads)
┌───────────────────────────────▼──────────────────────────────────────┐
│                    Flask application  (app/)                          │
│  application factory · blueprints · JSON error envelope · limits      │
│  /api/v1: health · samples · assets · runs · comparisons · reports    │
└────────┬───────────────────────┬──────────────────────┬───────────────┘
         │                       │                      │
┌────────▼─────────┐  ┌──────────▼──────────┐  ┌────────▼──────────────┐
│ Pipeline engine   │  │ Domain services      │  │ Storage layer          │
│ registry · runner │  │ (cheiloscan/…)       │  │ asset store (content- │
│ stage chaining ·  │  │ validate · preprocess│  │ addressed, append-    │
│ versioning ·      │  │ detect ROI · enhance│  │ only) + SQLAlchemy    │
│ param snapshots   │  │ extract features ·  │  │ repositories           │
│                   │  │ compare · report    │  │                        │
└────────┬─────────┘  └──────────┬──────────┘  └────────┬───────────────┘
         │                       │                       │
         └───────────────┬───────┴───────────────────────┘
                         ▼
     NumPy · OpenCV · SciPy · scikit-image · scikit-learn · ReportLab
                         │
        ┌────────────────▼────────────────┐   ┌────────────────────────┐
        │ SQLite  (data/db/app.sqlite, WAL) │   │ File store (data/)      │
        │ samples · assets · runs · feature │   │ original/ · derived/   │
        │ sets · comparisons · reports      │   │ reports/                │
        └───────────────────────────────────┘   └────────────────────────┘
```

---

## 4. Module map (target layout)

```
forensic/                       (repository root — currently empty)
├── pyproject.toml              # metadata + pinned dependencies (uv-managed)
├── run.py                      # dev entrypoint: flask run / app factory boot
├── app/                        # HTTP layer (thin)
│   ├── __init__.py             # create_app() factory
│   ├── config.py               # env-driven config (data dir, DB URL, limits)
│   └── api/                    # blueprints, one per resource
│       ├── health.py
│       ├── samples.py
│       ├── assets.py           # upload, stream, metadata
│       ├── runs.py             # trigger/inspect analysis runs
│       ├── comparisons.py
│       └── reports.py
├── cheiloscan/                 # domain package (no Flask imports allowed)
│   ├── config.py               # typed settings object
│   ├── db/
│   │   ├── models.py           # SQLAlchemy declarative models
│   │   ├── session.py          # engine/session factory (WAL pragmas)
│   │   └── repositories.py     # persistence use-cases per aggregate
│   ├── storage/
│   │   └── asset_store.py      # content-addressed save/load; enforces
│   │                            # save_original() vs save_derived()
│   ├── imaging/
│   │   ├── validation.py       # format, resolution, blur, luminance metrics
│   │   ├── preprocessing.py    # grayscale, denoise, CLAHE, normalization
│   │   ├── roi.py              # lip-print region detection + manual fallback
│   │   └── enhancement.py      # directional/groove enhancement
│   ├── features/
│   │   ├── glcm.py             # gray-level co-occurrence texture stats
│   │   ├── lbp.py              # local binary pattern histograms
│   │   ├── orientation.py      # structure-tensor orientation field + coherence
│   │   ├── ridge_frequency.py  # groove spatial frequency
│   │   └── skeleton_stats.py   # groove topology: density, branching
│   ├── compare/
│   │   ├── registration.py     # alignment (phase correlation / ECC)
│   │   ├── metrics.py          # cosine, Euclidean, NCC/SSIM on ROIs
│   │   └── fusion.py            # fixed-weight heuristic fusion (documented)
│   ├── pipeline/
│   │   ├── registry.py         # named, versioned pipelines
│   │   ├── runner.py            # executes stages, records snapshot
│   │   └── stages/              # thin adapters binding services to runner
│   ├── reporting/
│   │   ├── report_data.py      # assembles neutral report content
│   │   └── pdf.py              # ReportLab rendering (with disclaimers)
│   └── util/
│       ├── imageio.py          # decode/encode, safe formats
│       ├── hashes.py           # sha256, integrity checks
│       └── jsonutil.py         # stable JSON serialization for features
├── web/                        # static frontend served by Flask
│   ├── index.html, app.js, style.css, compare.html, sample.html, report.html
├── tests/
│   ├── unit/                   # pure function tests per module
│   ├── integration/            # Flask test client + temp SQLite + temp store
│   ├── regression/             # golden-file pipeline outputs (pinned seeds)
│   ├── fixtures_gen.py         # clearly-labeled SYNTHETIC image generators
│   └── conftest.py
├── docs/                       # this documentation set
└── data/                       # gitignored runtime data (see §6)
```

**Dependency rule:** `cheiloscan/` must never import `flask` or `app/`. All HTTP
concerns stay in `app/`. This is enforced by an import-linter-style unit test in
Phase 1 (a simple test that walks the package and asserts the import rule).

---

## 5. Core data flow

### 5.1 Ingestion

1. Client `POST /api/v1/samples/{id}/images` (multipart).
2. `ImageValidationService` checks: allowed format (PNG/JPEG initially),
   decodability, byte size limit, minimum resolution, blur metric (variance of
   Laplacian), luminance/contrast sanity. Failures return machine-readable
   reasons; borderline cases pass with recorded warnings.
3. Original bytes are hashed (SHA-256) and written **once** to the
   content-addressed store. A row is recorded in `image_assets`.
4. If the hash already exists, the upload deduplicates and links to the existing
   asset (integrity + storage savings).

### 5.2 Analysis run

1. Client `POST /api/v1/assets/{id}/analyze` with pipeline name + parameter
   overrides.
2. `PipelineRunner` snapshots `{pipeline_name, pipeline_version, params}` into
   `analysis_runs` (status `running`), executes stages in-process:
   `preprocess → roi → enhance → features`.
3. Each stage may emit **derived assets** (preprocessed image, ROI crop, enhanced
   image, orientation overlay) written under `data/derived/<run_id>/` and recorded
   with `parent_asset_id` + `analysis_run_id`.
4. Final `FeatureSet` row stores a versioned JSON feature document.
5. Run ends `succeeded` (with results) or `failed` (with error). Original asset
   bytes are never mutated (a post-run integrity test re-checks the hash).

### 5.3 Comparison

1. Client `POST /api/v1/comparisons` with `{run_a, run_b, method}`.
2. Comparator aligns ROIs (registration) where applicable, computes component
   scores per feature family + image-similarity scores, then a fixed-weight
   heuristic fusion (weights are constants documented in code, not learned).
3. All components are stored individually; the fused score is labeled
   `heuristic_fusion_v1`. No thresholding into "match/no-match".

### 5.4 Reporting

1. Client `POST /api/v1/comparisons/{id}/report`.
2. `report_data` assembles: methodology summary, run provenance (pipeline
   versions, parameters), component scores, uncertainties, and the mandatory
   research-disclaimer block.
3. ReportLab renders a PDF into `data/reports/`; row recorded in `reports`.

---

## 6. Storage design

### 6.1 File store (data directory)

```
data/
├── db/app.sqlite              # SQLite database (WAL mode)
├── original/<aa>/<sha256>.<ext>   # content-addressed originals (immutable)
├── derived/<run_id>/          # stage outputs, namespaced per run
│   ├── 01_preprocessed.png
│   ├── 02_roi.png
│   ├── 03_enhanced.png
│   └── 04_overlay.png
└── reports/<report_id>.pdf
```

- **Immutability enforcement:** `AssetStore.save_original()` refuses to overwrite;
  `save_derived()` always writes under a run namespace. Services receive only
  read handles to originals.
- **Data directory location** is configurable (`CHEILOSCAN_DATA_DIR`). Default is
  `./data` inside the repository. *Environment note:* the repo lives on a WSL
  drvfs mount (`/mnt/c`, Windows NTFS via 9p). SQLite and many small file writes
  are noticeably slower there; if IO becomes a bottleneck, point
  `CHEILOSCAN_DATA_DIR` at a path on the Linux ext4 filesystem (e.g.
  `~/cheiloscan-data`). Documented, not blocking.
- **Disk headroom warning:** the Windows drive currently has ~8.1 GB free.
  Deriving several artifacts per run means storage grows quickly; a storage-usage
  readout is included in `/api/v1/health` from Phase 2 onward.

### 6.2 Entities and relationships (SQLAlchemy 2.x, typed)

| Entity | Key fields | Relationships |
|---|---|---|
| `Sample` | id (UUID), code (unique label), description, capture_type, medium, collection_method, donor_ref (anonymized, optional), consent_confirmed (bool), created_at, updated_at, deleted_at (soft delete) | 1–N `ImageAsset` (originals), 1–N `Report` |
| `ImageAsset` | id, sample_id, kind (`original`/`derived`), sha256, storage_path, format, width, height, size_bytes, capture_meta (JSON), created_at; derived: `parent_asset_id`, `analysis_run_id` | N–1 `Sample`; N–1 `AnalysisRun` (for derived); 1–N `AnalysisRun` (as input) |
| `AnalysisRun` | id, input_asset_id, pipeline_name, pipeline_version, params (JSON), status, error, started_at, finished_at | N–1 input `ImageAsset`; 1–N derived `ImageAsset`; 1–1 `FeatureSet` |
| `FeatureSet` | id, analysis_run_id (unique), feature_version, features (JSON), created_at | 1–1 `AnalysisRun` |
| `Comparison` | id, run_a_id, run_b_id, method, method_version, params (JSON), component_scores (JSON), fused_score, created_at | N–1 `AnalysisRun` (a), N–1 `AnalysisRun` (b); 1–N `Report` |
| `Report` | id, subject_type (`comparison`/`sample`), comparison_id?, sample_id?, format, storage_path, sha256, created_at | N–1 `Comparison` or `Sample` |

```
Sample 1──N ImageAsset(original)
ImageAsset 1──N AnalysisRun          (input side)
AnalysisRun 1──N ImageAsset(derived) (output side, via parent_asset_id/run_id)
AnalysisRun 1──1 FeatureSet
Comparison ──> AnalysisRun (a) and AnalysisRun (b)
Comparison 1──N Report
Sample 1──N Report
```

Notes:
- UUIDs as primary keys so assets/runs/reports have stable, non-enumerable
  identifiers (also avoids SQLite rowid-churn issues with soft deletes).
- JSON columns via SQLAlchemy `JSON` type; feature documents carry their own
  `feature_version` because feature definitions evolve independently of the
  pipeline.
- Schema evolution: start with `metadata.create_all()` plus an explicit
  `schema_version` table. Migrate to Alembic when schema churn makes hand
  migration risky (decision recorded; see `DEVELOPMENT_LOG.md`).
- SQLite pragmas: WAL, `foreign_keys=ON`, `busy_timeout` — set at engine connect.

### 6.3 Reproducibility guarantees

- `analysis_runs.params` is a complete JSON snapshot (defaults resolved), not a
  reference to "current defaults".
- All algorithms that involve randomness (none are planned; if any are added,
  e.g. RANSAC-based registration) must accept a seeded RNG from the runner.
- Feature JSON serialization is key-sorted and float-rounded to a fixed precision
  so golden-file regression tests are byte-stable across platforms.

---

## 7. API surface (v1)

All endpoints under `/api/v1`, JSON in/out (except multipart upload and file
streaming). Uniform error envelope:

```json
{ "error": { "code": "validation_failed", "message": "...", "details": {...} } }
```

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Liveness, DB reachable, storage usage, dependency versions |
| POST | `/samples` | Create sample (metadata: code, capture_type, medium, …) |
| GET | `/samples` | List samples (pagination, filter) |
| GET | `/samples/{id}` | Sample detail incl. original + derived assets |
| PATCH | `/samples/{id}` | Update metadata |
| DELETE | `/samples/{id}` | Soft delete |
| POST | `/samples/{id}/images` | Upload original image (multipart, `role=original`) |
| GET | `/assets/{id}` | Asset metadata + provenance chain |
| GET | `/assets/{id}/file` | Stream image bytes (with correct MIME) |
| POST | `/assets/{id}/analyze` | Run pipeline on asset → creates `AnalysisRun` (synchronous in early phases; response includes run result or failure) |
| GET | `/runs/{id}` | Run status, params snapshot, derived assets, feature set |
| GET | `/runs/{id}/features` | FeatureSet JSON |
| POST | `/comparisons` | `{run_a, run_b, method, params?}` → component + fused scores |
| GET | `/comparisons/{id}` | Comparison detail |
| GET | `/comparisons` | History (pagination) |
| POST | `/comparisons/{id}/report` | Generate PDF report |
| GET | `/reports/{id}` / `GET /reports/{id}/download` | Report metadata / PDF bytes |

Frontend: `GET /` serves the static single-page UI which talks to `/api/v1`
via `fetch`. No template logic in Flask beyond serving static files (keeps the
HTTP layer thin; the UI is fully offline-capable).

**Upload limits:** max request body and per-file size configurable
(`CHEILOSCAN_MAX_UPLOAD_MB`, default 25 MB). Accepted: PNG, JPEG. Other formats
(TIFF) deferred — see unresolved questions.

---

## 8. Technology decisions and rationale

| Decision | Choice | Rationale | Alternatives rejected |
|---|---|---|---|
| Web framework | Flask 3.x | Thin, synchronous, mature; no async need for single-user local processing | FastAPI (extra paradigm + pydantic dep for no benefit here) |
| CV core | OpenCV (headless) + scikit-image | OpenCV: filtering, morphology, registration. scikit-image: validated texture (GLCM), LBP, ridge filters (sato/frangi), structure tensor | opencv-contrib-python (extra weight; ridge filters available in scikit-image) |
| OpenCV variant | `opencv-python-headless` | Server app never uses `cv2.imshow`; headless avoids libGL/libgthread runtime deps in minimal environments | non-headless `opencv-python` (would work here — libGL present — but headless is portable) |
| Numerics | NumPy 2.x + SciPy | Required by all CV/ML libs; all pinned versions verified numpy-2-compatible | numpy<2 legacy pins (unneeded) |
| ML utilities | scikit-learn | PCA/descriptive exploration of feature space; optional future supervised experiments **only if a real dataset is supplied** — never trained on synthetic data | deep learning stack (torch/tf: heavy, unjustified) |
| Persistence | SQLite + SQLAlchemy 2.x (typed ORM) | Local-first, zero admin, WAL suffices for single writer; ORM keeps schema in code | Postgres (violates local-first simplicity), raw SQL (maintenance cost) |
| Asset integrity | SHA-256 content addressing | Dedup, tamper detection, immutability enforcement for free | sequential filenames |
| Reports | ReportLab | Pure-Python PDF, no external binaries/LaTeX | wkhtmltopdf/weasyprint (system deps, heavier) |
| Frontend | Vanilla HTML/CSS/JS served by Flask | Offline-capable, no npm/build pipeline, no CDN | React/Vite (toolchain overhead for a research UI) |
| Env/packaging | `uv` + venv (Python 3.11) + `pyproject.toml` | PEP 668 forbids system installs on this Kali host; 3.11 has the broadest wheel coverage; uv is installed and fast | system pip (`--break-system-packages` is prohibited) |
| Testing | pytest 9.x | Already available; markers for unit/integration/regression | unittest (less ergonomic) |

**Verified dependency set** (resolved at wheel level for Python 3.11 and 3.14 on
2026-11-11; see `DEVELOPMENT_LOG.md`):

```
flask==3.1.3            numpy==2.4.6          scipy==1.17.1
opencv-python-headless  scikit-image==0.26.0   scikit-learn==1.9.1
sqlalchemy==2.1.8       reportlab==5.1.0      pytest==9.2.0
(pillow, werkzeug, jinja2, click, … as transitive dependencies)
```

### Known dependency-conflict hazards

1. **`opencv-python` vs `opencv-contrib-python`** — both install the `cv2`
   package and clobber each other's files. Install exactly one. We use
   `opencv-python-headless`.
2. **Headless vs GUI OpenCV variants** — same conflict class; never mix.
3. **NumPy 2.x ABI** — any package compiled against numpy<2 will break; the
   pinned set above is verified compatible.
4. **System site-packages** — this Kali host has system-level flask/numpy/scipy
   under Python 3.14 (PEP 668 externally-managed). The project venv must stay
   isolated; never install with `--break-system-packages`.
5. **scikit-learn ↔ scipy ↔ scikit-image version triple** — these have tight
   mutual compatibility windows; the resolved triple above is verified together
   and must be bumped together, not individually.

---

## 9. Cross-cutting concerns

- **Logging:** structured-ish plain logging via Python `logging`; request-scoped
  correlation IDs. No third-party logging framework.
- **Errors:** HTTP exceptions mapped to the JSON envelope; unexpected exceptions
  logged with stack trace, run status set to `failed` with stored error string.
- **Security (local threat model):** file-type allowlist + real decode check (not
  extension trust), upload size caps, no path traversal (content-addressed
  names only), no eval/dynamic code from parameters, no network listeners beyond
  localhost by default (`flask run --host 127.0.0.1`). Lip prints are
  biometric-adjacent personal data: storage stays local, donor references are
  anonymized, and a `consent_confirmed` flag is required on samples.
- **Performance:** single-user workloads; images processed synchronously
  (seconds each). If runs exceed ~10 s, move to a background worker thread pool
  with run status polling (API already shaped for it: runs are first-class
  resources with `status`).
- **Concurrency:** SQLite WAL + busy timeout; the pipeline runner uses one
  session per run. Multi-process (gunicorn) deployment is explicitly *not* a
  target.

---

## 10. Coherence checklist (Phase 0 self-review)

- [x] Every derived artifact traces to an `AnalysisRun` with a parameter snapshot.
- [x] Originals have no write path anywhere in the design.
- [x] API resources map 1:1 onto entities; no entity lacks an access path.
- [x] The domain package (`cheiloscan/`) is free of HTTP/Flask concerns.
- [x] Comparison outputs carry component scores; fusion is labeled heuristic.
- [x] Reports always embed provenance + research disclaimer.
- [x] No claims of validated accuracy anywhere in the design.
