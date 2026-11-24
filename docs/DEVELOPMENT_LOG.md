# CheiloScan — Development Log

Chronological record of inspection findings, decisions, and open questions.
Newest entries at the bottom.

---

## 2026-11-11 — Phase 0: Repository inspection and project planning

### Inspection performed

| # | Step | Result |
|---|---|---|
| 1 | Full directory listing of `/mnt/c/Users/MEVIS/Desktop/forensic` (incl. hidden files) | **Completely empty.** No source code, no config, no dependencies, no git history. Greenfield project. |
| 2 | Python interpreter check | System Python **3.14.7** (`/usr/bin/python3`) on Kali Linux (WSL2). Externally managed (PEP 668) — system-wide pip installs are blocked by policy. `python3.11` also available at `/home/Mevis/.local/bin/python3.11`. |
| 3 | Tooling check | `uv` present (venv + resolver), `pip` 26.1.2, `git` 2.53.0 (repo **not yet initialized**), `pytest` 9.1.1 system-installed. 12 CPUs. |
| 4 | Installed-package audit | Present system-wide: flask 3.1.3, numpy 2.4.6, scipy 1.17.1, pillow 12.3.0, werkzeug 3.1.9. **Missing:** opencv-python, scikit-image, scikit-learn, sqlalchemy, reportlab. |
| 5 | Dependency resolution dry-run (`uv pip compile` / `uv pip install --dry-run` in throwaway `/tmp` venvs — nothing installed into the project) | Full proposed stack resolves at **wheel level** for both Python 3.11 and 3.14 with **no conflicts**. Resolved set: flask 3.1.3, numpy 2.4.6/2.5.4, scipy 1.17.1/1.18.1, opencv-python 5.0.0.93, scikit-image 0.26.0, scikit-learn 1.9.1, sqlalchemy 2.1.8, reportlab 5.1.0, pytest 9.2.0. Scratch venvs cleaned up afterward. |
| 6 | System library check for OpenCV | `libGL.so.1` present (non-headless OpenCV would import), but headless variant chosen anyway (decision D5). |
| 7 | Disk/headroom check | Windows `C:` drive: **8.1 GB free (97% full)**. Repo lives on drvfs (`/mnt/c`) via 9p — SQLite + many-small-file IO expected to be slow. Documented as risks R3/R4 with mitigations. |

### Decisions made (ADR summary)

| ID | Decision | Rationale |
|---|---|---|
| D1 | Python **3.11** in a project venv managed by `uv`; `pyproject.toml` + committed `uv.lock` | PEP 668 forbids system installs; 3.11 has broadest wheel coverage for the scientific stack; both 3.11 and 3.14 verified resolvable — 3.11 chosen as the conservative option. |
| D2 | **Flask 3.x** (synchronous) | Thin HTTP layer; single-user local processing; no async benefit justifying FastAPI. |
| D3 | **SQLite + SQLAlchemy 2.x typed ORM**, WAL mode, `schema_version` table; Alembic deferred | Local-first, zero-admin; migrate tooling when schema churn justifies it. |
| D4 | **Content-addressed original asset store** (SHA-256) + run-namespaced derived artifacts | Enforces original immutability by construction; gives dedup and integrity verification for free. |
| D5 | `opencv-python-headless` (exactly one OpenCV distribution) | Server app has no GUI usage; avoids libGL runtime deps in minimal environments; prevents cv2 clobber conflicts with contrib/non-headless variants. |
| D6 | Feature families as **independently versioned modules** (GLCM, LBP, orientation, ridge frequency, skeleton topology) | Features evolve independently of pipelines; versioned JSON enables golden-file regression and honest provenance in reports. |
| D7 | Comparison = **component scores + fixed-weight heuristic fusion, no thresholds, no verdicts** | No dataset exists to calibrate or validate any classifier; honest alternative is descriptive scoring only (see `SCIENTIFIC_METHODOLOGY.md` §2). |
| D8 | **Mandatory manual ROI fallback** alongside automatic detection | Automatic lip-region segmentation on real prints is expected to be unreliable (risk R1); the manual path guarantees the pipeline remains usable and auditable. |
| D9 | Frontend = **vanilla HTML/CSS/JS** served by Flask; no npm, no CDN | Offline-capable, minimal maintenance, fits a research tool. |
| D10 | Synthetic fixtures only inside `tests/`, labeled as such | Upholds the no-fabricated-data constraint; correctness testing ≠ accuracy claims. |
| D11 | Documentation-first Phase 0; no code written | Per project constraints (planning only). |

### Documents created (this phase)

- `docs/ARCHITECTURE.md` — system design, module map, storage, data model, API, tech decisions.
- `docs/IMPLEMENTATION_PLAN.md` — phased plan, pinned dependencies, risks, Phase 1 starting point.
- `docs/SCIENTIFIC_METHODOLOGY.md` — domain background, claim policy, pipeline algorithms, limitations.
- `docs/TESTING_STRATEGY.md` — test categories, synthetic fixture policy, coverage targets.
- `docs/DEVELOPMENT_LOG.md` — this file.

### Verification performed at close of Phase 0

- Architecture coherence: every derived artifact traces to a recorded run; API
  resources map 1:1 to entities; domain package isolated from HTTP. ✔
- Phase realism: effort-estimated phases with acceptance criteria and fallbacks
  for the risky ones (4–6). ✔
- Dependencies: pinned, wheel-verified for 3.11/3.14, conflict rules written. ✔
- Scientific honesty: no accuracy claims, no thresholds, mandatory disclaimers,
  synthetic-data policy. ✔
- Phase 1 starting point defined exactly (commands + file list + exit criteria). ✔

### Open questions carried forward

1. Primary capture modality (print-on-document vs photograph) — affects ROI
   strategy priorities; confirm during Phases 3–4.
2. TIFF support needed? (scanner workflows)
3. Expected background control level — drives validation thresholds.
4. Sync vs background processing threshold (~10 s proposal).
5. Alembic adoption timing (first schema change trigger).
6. 1:N screening permanently out of scope? (currently yes)
7. Data directory location: repo `./data` on drvfs vs ext4 — benchmark in Phase 2.
8. UI: stay vanilla JS or add htmx if compare/report UX demands it.

### Next action

**Phase 1 — project skeleton and environment**, exactly as specified in
`IMPLEMENTATION_PLAN.md` §5: `git init`, `.gitignore`, `uv venv --python 3.11`,
`pyproject.toml` with pinned dependencies, package skeleton
(`app/`, `cheiloscan/`, `web/`, `tests/`), `/api/v1/health` endpoint, import-rule
and OpenCV smoke tests, first commit. No application features before that
skeleton is green.

---

## 2026-11-11 — Phase 1: Backend foundation (implemented)

### What was built

| Area | Contents |
|---|---|
| Project structure | `app/` (factory, config, routes, errors, logging, extensions), `app/api/` (health, dashboard, samples, comparisons blueprints), `cheiloscan/` domain package (`db/` models + session + repositories, `services/stats.py`, `storage/`), `web/` static frontend shell, `tests/` (unit + integration), `run.py`, `pyproject.toml`, `.env.example`, `.python-version` |
| Configuration | Env-driven with fail-fast validation (`CHEILOSCAN_*` vars), dev/production modes, ephemeral dev secret, data-dir resolution, SQLite URL default, upload size MB→bytes, log level/format validation; `.env.example` documents every variable |
| Database | `Sample`, `ImageAsset`, `AnalysisRun`, `Comparison`, `SchemaVersion` models (SQLAlchemy 2.x typed, UUID PKs, UTC timestamps, soft delete, `validate_strings` enums, partial unique index on original-asset hashes); WAL + foreign_keys + busy_timeout pragmas; idempotent `init_schema` with downgrade/upgrade guards; repositories for samples/analyses/comparisons |
| API | `GET /api/health` (liveness, DB, dependency versions), `GET /api/dashboard/stats` (real counts only), `GET /api/samples` (pagination, soft-delete filtering), `GET /api/comparisons`; uniform JSON error envelope; `X-Request-ID` header |
| Frontend shell | Sidebar nav + header + content + footer layout; dashboard with real stats cards and honest empty states; samples/comparisons list pages; analyses page is an explicit not-implemented-yet placeholder; disclaimer text in every page footer |
| Logging/errors | JSON-lines structured logging (or plain), request correlation IDs, centralized handlers for HTTPException (proper status codes), SQLAlchemyError (500 `database_error`, no internals leaked), unexpected exceptions (500 `internal_error`) |
| Tests | 79 tests, all green: startup, config, logging, import rules, schema init/safety, models + constraints, relationships + repositories, all four API endpoints, persistence across engine disposal, error envelopes |

### Decisions and deviations from Phase 0 documentation (justified)

| ID | Decision | Rationale |
|---|---|---|
| P1-1 | API served under `/api/*` (instruction-specified paths), not `/api/v1/*` as sketched in Phase 0 | The Phase 1 instruction explicitly lists `GET /api/health`, `/api/dashboard/stats`, `/api/samples`, `/api/comparisons`. Versioning can be introduced later via alias without breaking clients. |
| P1-2 | Only Phase 1 dependencies installed (flask 3.1.3, sqlalchemy 2.1.8, python-dotenv 1.2.4; pytest 9.2.0 dev) | "No unnecessary packages" rule; the imaging/scientific stack lands in its implementing phase (opencv smoke test deferred accordingly). `uv.lock` pins the full resolved set. |
| P1-3 | Instruction's three models mapped onto the documented entities: SAMPLE→`Sample`+`ImageAsset` (image path/format/dimensions live on the asset, per Phase 0 normalization), ANALYSIS→`AnalysisRun` (+`sample_id` per instruction), COMPARISON→`Comparison` (+`sample_a_id`/`sample_b_id` per instruction, `run_a_id`/`run_b_id` nullable for Phase 7) | Honors both the instruction's field list and the documented schema without later schema churn. |
| P1-4 | `FeatureSet` and `Report` models deferred to Phases 6/8; `ImageAsset.analysis_run_id` deferred to Phase 4 | No placeholder code for unused tables; the reverse run-link cannot coexist with `AnalysisRun.input_asset_id` as mutual FKs on SQLite (no `ALTER TABLE ADD CONSTRAINT`), so it needs a proper migration when derived assets exist. `captured_at` added to `Sample` per the instruction's "capture date" field. |
| P1-5 | SQLAlchemy `Enum(validate_strings=True)` everywhere | Unknown status values fail fast at the application layer instead of silently reaching SQLite. |
| P1-6 | `uv sync` + committed `uv.lock` + `.python-version` (3.11) instead of manual venv + `pip install -e .` | Same result (editable install of `cheiloscan`), plus reproducible lockfile. |
| P1-7 | Git initial branch renamed to `main`; Phase 0 docs committed first as their own commit | Clean history separation. |

### Verification performed

- `uv run pytest`: **79 passed** (unit + integration; every test isolated in a throwaway data dir + SQLite file).
- Live server run (`uv run python run.py`, 127.0.0.1:5000): `/`, `/samples`, `/analyses`, `/comparisons`, `/css/style.css`, `/js/app.js` → 200; `/api/health` reports `flask 3.1.3`, `sqlalchemy 2.1.8`, DB connected, schema_version 1; `/api/dashboard/stats` returns honest zeros + measured storage bytes; JSON request logging observed on stdout with request IDs.
- End-to-end record flow: a sample row inserted externally appeared immediately via `GET /api/samples` (WAL concurrency confirmed); the row was a live connectivity check (`LIVE-CHECK-001`) and was **removed afterwards** — the database is empty of test data.
- `data/` runtime tree created and gitignored (`db/`, `original/`, `derived/`, `reports/`).

### Completion criteria status

1. Starts successfully — verified (dev server boots, health OK).
2. Initializes SQLite — verified (tables + schema_version + WAL pragmas, idempotent).
3. Creates database records — verified (repositories + live insert/read-back).
4. Responds to API requests — verified (all four endpoints, JSON envelopes, correct status codes incl. 400/404/405/500/503 paths under test).
5. Passes automated tests — 79/79 green.

### Carried-forward notes

- Dashboard/UI pages fetch only real data; no fabricated statistics anywhere.
- `storage_path` is internal and never serialized (guarded by tests).
- Next phase per plan: **Phase 2 — asset store (content-addressed save_original/save_derived with immutability tests) and Phase 3 intake endpoints**; the imaging stack arrives with preprocessing work.

---

## 2026-11-11 — Phase 2: Image acquisition and preprocessing (implemented)

### What was built

| Area | Contents |
|---|---|
| Dependencies | `numpy 2.4.6`, `opencv-python-headless 5.0.0.93`, `pillow 13.0.0` added to the pinned set (`uv sync`, committed `uv.lock`). OpenCV 5's API surface was smoke-tested before use (`imdecode`, filters, CLAHE, Laplacian, `normalize`, encode/decode flags). |
| Image I/O | `cheiloscan/util/imageio.py`: magic-byte format detection (JPEG/PNG/WebP), decode with `IMREAD_IGNORE_ORIENTATION`, explicit EXIF-orientation transform for working copies, EXIF subset extraction via Pillow, safe display-filename sanitisation, content hashing, encoding for derived assets. |
| Asset storage | `cheiloscan/storage/asset_store.py`: content-addressed immutable originals at `data/original/<aa>/<sha256>.<ext>` (atomic write, re-hash before accepting an existing file, best-effort read-only), per-run derived files at `data/derived/<run_id>/<role>.<ext>`, path-containment guard and strict path-component validation. |
| Quality assessment | `cheiloscan/imaging/quality.py`: resolution, Laplacian-variance blur, mean brightness, intensity standard deviation (contrast), clipped shadow/highlight fractions, and non-blocking warnings. Every threshold is configurable; warnings never reject an image. |
| Preprocessing | `cheiloscan/imaging/preprocess.py`: BGR↔RGB, grayscale, Gaussian/median/bilateral denoising, CLAHE, gamma, illumination correction, min-max normalisation, unsharp-mask sharpening. Pure functions, strict validation, no automatic application. |
| Pipeline | `cheiloscan/imaging/pipeline.py`: strict parameter validation, five recorded stages (`grayscale → denoised → illumination_corrected → contrast_enhanced → final`), disabled stages pass through and are flagged `skipped`, real per-stage images, before/after quality, timings and notes. |
| Intake service | `cheiloscan/services/intake.py`: size → format (magic bytes) → decode → absolute dimension limits → sample metadata → code uniqueness → content-hash dedupe; stores the original unmodified, records EXIF/quality/provenance in `capture_meta`, auto-generates `S-XXXXXXXX` codes. |
| Processing service | `cheiloscan/services/processing.py`: creates a `running` run with a full parameter snapshot, encodes and persists one derived asset per stage, records measured results, and turns execution failures into a persisted `failed` run with a client-safe error (no paths). Invalid parameters abort before a run exists. |
| Database | Schema v2: `analysis_runs.results` (JSON outputs, separate from `params` inputs) and `analysis_artifacts` `(analysis_run_id, image_asset_id, role)` with `UNIQUE(run_id, role)`. `cheiloscan/db/migrations.py` applies ordered migrations; `init_schema` creates missing tables then migrates instead of refusing older databases. |
| API | `POST /api/samples/upload`, `POST /api/analysis/<sample_id>/process`, `GET /api/analysis/<analysis_id>`, plus UI-support endpoints `GET /api/analyses` and `GET /api/assets/<asset_id>/file`. Stable domain error codes → 400/404/409/413/415/422/500. |
| Frontend | Drag-and-drop upload with optional metadata, real upload result (thumbnail, dimensions, hash, quality warnings), sample list with thumbnails and per-sample **Process**, analyses list, and an analysis detail page showing Original / Grayscale / Denoised / Illumination-corrected / Enhanced / Final images served from the store, before/after quality tables, parameters, timings and notes. |
| Configuration | `CHEILOSCAN_MIN_IMAGE_DIMENSION`, `CHEILOSCAN_MAX_IMAGE_DIMENSION`, and six `CHEILOSCAN_QUALITY_*` thresholds (documented in `.env.example`, validated at startup). |
| Tests | 222 tests, all green: 119 unit (image I/O, preprocessing, quality, pipeline, asset store) + integration upload/processing/migration cases, on top of the unchanged Phase 1 suite. |

### Decisions and deviations (justified)

| ID | Decision | Rationale |
|---|---|---|
| P2-1 | Schema v2 adds `analysis_runs.results` and an `analysis_artifacts` association table, replacing the Phase 1 deferred `ImageAsset.analysis_run_id` | SQLite cannot add a mutually-referencing foreign key pair after the fact. The association table models "one derived asset per run stage" directly and carries the `UNIQUE(run_id, role)` invariant. Inputs (`params`) and measured outputs (`results`) stay in separate columns. |
| P2-2 | Originals are content-addressed and never rewritten; EXIF orientation is applied only to the in-memory working copy | Guarantees byte-for-byte preservation (verified by re-hashing after processing) while still processing and displaying the image the right way up. |
| P2-3 | Format detection uses magic bytes, not filename/MIME; OpenCV does all pixel work, Pillow only reads EXIF | A mislabelled upload cannot smuggle an unsupported format, and pixel behaviour stays in one library. Pillow is not used to decode or re-encode pixels. |
| P2-4 | Quality thresholds are experimental and produce warnings only; separate absolute dimension limits reject only unusable images | Matches the scientific-honesty constraint: the tool must not claim an image is unusable for identification, and thresholds must be tuned per capture setup. |
| P2-5 | Pipeline stages are independently switchable; disabled stages pass through unchanged and are marked `skipped` | Prevents silently doing something different from what the stored parameters say, keeping runs reproducible. Grayscale is the only unconditional stage because groove enhancement is luminance-based. |
| P2-6 | A failed execution is persisted as a `failed` run with a sanitised error, returned as HTTP 500 with its `analysis_id`; invalid parameters are rejected with 400 before any run is created | Failures remain visible in history for auditing, while invalid requests do not pollute the run table. No filesystem paths or exception internals reach clients. |
| P2-7 | Extra endpoints/pages for listing runs, serving assets and opening a run (`/api/analyses`, `/api/assets/<id>/file`, `/analysis/<id>`) | Required to show real previews and real results in the UI without exposing storage paths. Not a scope expansion into later phases. |
| P2-8 | Derived output defaults to lossless PNG (configurable per run to JPEG/WebP) | Avoids adding a second generation of lossy compression to already-compressed uploads; the researcher can choose otherwise explicitly. |

### Verification performed

- `uv run pytest`: **222 passed** (Phase 1 suite still green after the schema-v2 update).
- Migration dry-run on a copy of the real v1 database: version 1→2, `results` added, `analysis_artifacts` created with its unique constraint, second run idempotent.
- Live server (`uv run python run.py`, isolated data dir): upload → process → read run → fetch each artifact; original SHA-256 and bytes unchanged after processing; every preview URL returned a real decodable image; no `storage_path`/`derived/`/`original/` string in any API payload.
- Error-path checks: empty/corrupt/unsupported/too-small/oversized uploads, duplicate content, duplicate code, invalid parameters, unknown sample/analysis, sample without image, and a deliberately corrupted original producing a persisted `failed` run.

### Completion criteria status

1. Accept JPEG/PNG/WebP with drag-and-drop — verified.
2. Validate file, decode, size and dimensions — verified (hard rejections only for unusable content).
3. Unique sample IDs and safe filenames — verified (auto/explicit codes, sanitised display names).
4. Metadata extraction and immutable originals — verified (EXIF subset recorded, SHA-256 re-checked).
5. Quality assessment with configurable warnings — verified (blur, brightness, contrast, resolution, exposure).
6. Reusable preprocessing functions — verified (unit tests for every function and invalid inputs).
7. Pipeline returns real stage images, quality and params — verified (persisted artifacts + results JSON).
8. Preview UI shows real Original/Grayscale/Denoised/Enhanced images — verified live.
9. Automated tests cover the required cases — 222 green.

### Carried-forward notes

- The real `data/db/app.sqlite` (v1) will migrate automatically on the next application start; no manual step is required.
- Quality thresholds are placeholders for experimentation, not validated forensic criteria; any change must be recorded here.
- Next phase per plan: facial/lip-print region-of-interest work and feature extraction; no identification or match-accuracy claims are made by this phase.

---

## 2026-11-24 — Production hardening and deployment readiness

### Scope

Full project audit with a security/deployment review and a functional-correctness
review, followed by hardening of the existing Phase 0–2 application. No scientific
scope was added: comparison scoring, feature extraction and reports remain future
phases. The baseline was **222 passing tests**; the hardened tree has **241**.

### Decisions and changes

| ID | Decision | Rationale |
|---|---|---|
| H1 | Production now fails fast unless `SECRET_KEY` (≥32 chars), Basic-auth credentials, a trusted proxy hop, HTTPS enforcement and an allowed-host list are configured; development refuses a non-loopback bind | The previous `production` mode only disabled DEBUG, leaving an unauthenticated service that could transmit Basic credentials in cleartext or expose the Werkzeug debugger. |
| H2 | Added `app/security.py`: HTTP Basic against a Werkzeug hash, per-process failed-login throttle, Host allowlist, strict `(scheme, host, port)` Origin checks, `Sec-Fetch-Site` checks, `ProxyFix`, HSTS, security headers and cache policies | The app holds biometric-adjacent research data and has no session layer; a single account is honest about the threat model while making accidental network exposure safe by default. |
| H3 | `/api/health/live` is public and deliberately bypasses Host/TLS checks; `/api/health/ready` and `/api/health` remain authenticated and report real DB/schema/storage state | Container orchestrators probe over plain loopback HTTP before a public hostname or TLS proxy exists. Detailed state should not be public. |
| H4 | Header dimensions and a configurable pixel budget are checked **before** `cv2.imdecode`; upload size/dimension/thread bounds are capped | A tiny highly-compressible image can declare a multi-gigapixel buffer; decoding first would allocate it before any limit could reject it. |
| H5 | Processing decodes/processes/encodes outside the DB transaction and persists the run in one short write; upload uniqueness races map to 409; list endpoints use `selectinload` | A CPU-heavy run previously held a SQLite write lock for its whole duration, blocking other writers until `busy_timeout`, and DB constraint races surfaced as 500s. |
| H6 | Added `serve.py` (Waitress, one process, 1–4 threads), `wsgi.py`, `Dockerfile` (non-root, locked deps), `docker-compose.yml`, `.dockerignore`, `deploy/nginx.conf.example`, CI workflow and README | No deployable entrypoint or reproducible operator path existed. `uv.lock` was regenerated after adding Waitress. |
| H7 | Waitress is configured with `clear_untrusted_proxy_headers=False` | Waitress 3 clears `X-Forwarded-*` by default, which silently broke `ProxyFix`/`FORCE_HTTPS` in the first live smoke test. The app port must therefore remain reachable only from the trusted proxy that overwrites those headers. |
| H8 | Reconciled status text in docs, documented `/api/*` vs planned `/api/v1/*`, WebP support, optional `consent_confirmed`, sensitive logs, single-worker constraint and deployment/backups | The planning documents still read as if nothing were implemented and contradicted the shipped behaviour. |
| H9 | Frontend escaping now covers quotes, ID path segments are URL-encoded, stale "later phase" UI copy was corrected | CSP limits script execution but attribute-unsafe escaping could still corrupt markup or URLs. |

### Verification performed

- `uv lock --check`: clean; `uv sync --frozen` with `.venv-win`: clean.
- `uv run --frozen pytest -q`: **241 passed** (222 baseline + 19 new hardening/regression cases).
- Live production smoke via `serve.py` on a temporary data directory with simulated
  trusted-proxy headers: `/api/health/live` → 200 without credentials; plain-HTTP
  protected route → 308; authenticated `/api/health/ready` → 200; protected route
  without credentials → 401; bad `Host` → 400; cross-origin `Origin` → 403;
  upload → 201; preprocessing → 201 `succeeded` with five real artifacts; asset
  download → 200 with a valid PNG signature; run detail → 200; HSTS/CSP/no-store
  headers present. Temporary data and credentials were discarded afterwards.
- The first smoke run exposed the Waitress 3 proxy-header clearing issue; it was
  fixed and covered by `tests/unit/test_serve.py` before the final green run.

### Carried forward

- `README.md` is now the deployment source of truth; `docs/ARCHITECTURE.md` §7
  distinguishes implemented endpoints from the phase 3–8 target surface.
- Background processing, per-user authorization, orphan-asset reconciliation,
  storage export and golden-file regression tests remain open work.
- Multi-process WSGI workers against one SQLite/WAL data directory remain
  explicitly unsupported; scaling requires a different database.
