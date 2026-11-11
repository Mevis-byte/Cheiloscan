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
