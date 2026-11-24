# CheiloScan — Testing Strategy

**Status:** Phase 0 planning document; implementation status updated 2026-11-24
**Date:** 2026-11-11 (planning), 2026-11-24 (deployment hardening)

> **Current suite:** 241 passing tests (`uv run --frozen pytest -q`), including
> integration coverage for the HTTP security controls, health probes, pixel
> budget, upload/processing flows and schema migration. Golden-file regression
> tests for later deterministic feature extraction are still pending.

---

## 1. Principles

1. **No fabricated research data.** Test images are procedurally generated
   synthetic fixtures with known ground truth. They live only in `tests/`,
   are labeled `SYNTHETIC` in metadata, and are never inserted into the sample
   database as real samples or used to make accuracy claims about real lip
   prints. Test docstrings restate this.
2. **Correctness of implementation, not forensic accuracy.** A passing suite
   proves algorithms recover known ground truth on controlled inputs and that
   the system behaves as specified — nothing more. This distinction is stated
   in the test package docstring.
3. **Determinism first.** No test depends on wall-clock, network, or unpinned
   randomness. Any algorithm with stochastic elements must accept a seeded RNG
   provided by the runner/tests.
4. **Immutability is tested, not assumed.** Original asset SHA-256 is re-verified
   after every pipeline-level test.
5. **Layers tested in isolation.** The domain package (`cheiloscan/`) is
   testable without Flask; HTTP tests use Flask's test client with a temp data
   directory and temp SQLite database (no real `data/` is ever touched).

## 2. Test pyramid and categories

| Category | Marker | Scope | Count target |
|---|---|---|---|
| Unit | `@pytest.mark.unit` | Pure functions/modules in `cheiloscan/` | majority of tests |
| Integration | `@pytest.mark.integration` | Flask blueprints + repositories + asset store (temp dirs) | all API paths happy + error |
| Regression | `@pytest.mark.regression` | Golden-file outputs of full pipelines on fixed fixtures | 2+ per pipeline version |
| Import rules | `unit` | architecture constraints (no Flask in domain, no forbidden imports) | few |
| Manual QA | — | UI look-and-feel, PDF visual sanity | checklist (§7) |

Default run: `uv run pytest` executes all markers. Fast loop during development:
`uv run pytest -m unit`.

## 3. Fixtures strategy (synthetic image generation)

`tests/fixtures_gen.py` provides generators, all seeded and parameterized:

| Generator | Ground truth provided |
|---|---|
| `ridge_pattern(angle, frequency, noise, size)` | known orientation & spatial frequency |
| `blob_on_background(...)` | known bbox for ROI tests |
| `blank`, `uniform_gray`, `checkerboard` | degenerate inputs for validation/edge tests |
| `corrupt_bytes(...)` | undecodable file for upload rejection tests |

Every generated fixture is deterministic given its parameters. Fixtures are
created at test time in `tmp_path` (no binary blobs committed to git); only
golden **feature JSON** outputs are committed, keyed by a short fixture ID +
generator parameters.

Golden-file policy: if an algorithm change legitimately alters outputs, the
golden file is regenerated in the same commit, and the commit message must
reference the algorithm change. Silent golden drift fails CI.

## 4. Per-module test inventory (planned)

### Unit

- `imaging/validation.py`
  - rejects: corrupt bytes, wrong format, oversized, undersized
  - warns (not rejects): blurry, dark, low contrast — threshold boundaries tested
- `imaging/preprocessing.py`
  - grayscale conversion values on tiny known arrays; CLAHE output shape/stats
    bounds; parameter snapshot reflects overrides
- `imaging/roi.py`
  - `blob_on_background` → expected bbox within tolerance
  - low-contrast/ambiguous input → low confidence flag
  - manual bbox override recorded as parameter
- `imaging/enhancement.py`
  - `ridge_pattern(θ)` → recovered dominant orientation within ±5°
  - `ridge_pattern(f)` → recovered frequency within 10%
  - determinism: same input+params → identical bytes
- `features/*`
  - GLCM on hand-computable 4×4 quantized array → reference values
  - LBP histogram on known micro-pattern
  - orientation coherence = 1.0 for perfectly aligned pattern, ≈0 for isotropic
  - skeleton stats on drawn shapes (cross → known node/branch counts)
  - feature JSON: key-sorted, version fields present
- `compare/*`
  - cosine/Euclidean identities (vectors known)
  - registration: shifted synthetic pair → recovered shift within 1 px
  - SSIM of identical images = 1.0 (within float tolerance)
  - fusion: fixed weights produce documented linear combination; no
    thresholding function exists (assert via code introspection or by design)
- `storage/asset_store.py`
  - save_original dedupes by hash; overwrite attempt raises
  - save_derived is namespaced under run id
- `db/models.py`
  - relationship wiring; soft delete semantics; JSON round-trip

### Integration (Flask test client, temp SQLite + temp asset store)

- health endpoint: 200, dependency versions present
- samples: create / list / patch / soft-delete / duplicate code → 409
- image upload: happy path; corrupt file → 4xx with reason; duplicate upload →
  dedupe (same asset id); oversize → 413
- analyze: run recorded with param snapshot; derived assets exist; feature set
  stored; **original sha256 unchanged after run** (integrity assertion)
- compare: two runs → component scores + heuristic fusion stored; missing run → 404
- report: PDF created; disclaimer text extractable from PDF; download streams
- error envelope shape on every failure path

### Regression

- pipeline `baseline_v1` on `ridge_pattern` fixture → golden feature JSON
  (float-tolerant compare at fixed decimal rounding)
- full pipeline determinism: run twice in fresh temp stores → identical feature
  JSON bytes

## 5. Determinism and environment

- All random generation seeded (`numpy.random.default_rng(seed)`).
- Float serialization rounded to 6 decimals in feature documents.
- Tests never read/write the repo's `data/` — always `tmp_path` via fixtures.
- Dependency pins + `uv.lock` committed; CI (if later added) runs on the same
  pinned set. OpenCV version is asserted in a smoke test to catch silent
  environment drift.

## 6. Coverage targets

- `cheiloscan/`: ≥ 90% line coverage overall; 100% for `storage/asset_store.py`
  (immutability logic) and `compare/fusion.py` (honesty-critical logic).
- `app/`: all routes hit at least once with success + one failure case.
- Coverage measured with `pytest --cov` (adds `pytest-cov` dev dependency;
  acceptable minimal addition — see dependency rules in `IMPLEMENTATION_PLAN.md`
  §3).

## 7. Manual QA checklist (per phase that ships UI)

- [ ] Upload flow: file picker, progress, error messages meaningful
- [ ] Sample page: thumbnails, provenance visible (hash, timestamps)
- [ ] Compare page: side-by-side view, score table readable, disclaimer visible
- [ ] Report PDF opens, images embedded, disclaimer present, provenance complete
- [ ] Health page reflects real dependency versions
- [ ] App fully functional offline (no CDN/network access)

## 8. Definition of "green"

A phase is done when:

1. `uv run pytest` fully green (all markers),
2. new behavior has both happy-path and failure-path tests,
3. any golden-file changes are justified in the commit,
4. coverage targets for the touched modules hold.
