# CheiloScan

CheiloScan is a **local-first research application** for acquiring lip-print
images, measuring image quality, and running a conservative preprocessing
pipeline with fully provenanced, immutable artifacts.

> **Scope and claim policy.** This is an experimental tool, not a validated
> biometric identification system. It produces descriptive image measurements
> only — no identity verdicts, match probabilities, likelihood ratios, or
> accuracy statistics. See `docs/SCIENTIFIC_METHODOLOGY.md`. The implemented
> release corresponds to phases 0–2 of `docs/IMPLEMENTATION_PLAN.md`;
> feature extraction, comparison scoring, and PDF reports are **not** in this
> release and are not implied by the UI.

---

## 1. What is implemented

| Area | Status |
|---|---|
| Sample registration, JPEG/PNG/WebP upload, SHA-256 deduplication | Implemented |
| EXIF orientation handling, quality warnings (non-blocking) | Implemented |
| Immutable originals + per-run derived artifacts on disk | Implemented |
| Preprocessing pipeline (grayscale → denoise → illumination → contrast → final) | Implemented |
| Analysis history, measured results, image previews, dashboard | Implemented |
| Pairwise comparison engine, feature sets, PDF reports | **Not implemented** |
| `/api/v1` paths from the architecture document | Deviated: endpoints use `/api/*` |

---

## 2. Development quickstart

Requires Python 3.11 and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
uv run python run.py
# open http://127.0.0.1:5000
```

Run the full test suite:

```bash
uv run pytest -q
uv lock --check
```

**Windows note:** if the checkout contains a Linux-created `.venv`
(`pyvenv.cfg` points to `/home/...`), `uv sync` may fail with
`Access is denied` on `.venv\lib64`. Delete that directory or use an
alternative environment path, for example in PowerShell:

```powershell
$env:UV_PROJECT_ENVIRONMENT = '.venv-win'
uv sync --frozen
uv run --frozen pytest -q
```

Configuration is read from environment variables documented in
`.env.example`. `run.py` loads a local `.env` file when present; production
should use real environment variables or container secrets instead.

---

## 3. Production deployment

### 3.1 Requirements

- One trusted TLS-terminating reverse proxy (nginx/Traefik/Caddy) in front of
  the application. Basic credentials must never cross an unencrypted network.
- A persistent volume for `CHEILOSCAN_DATA_DIR` (SQLite database + image store).
- A single application process. SQLite/WAL supports one writer; horizontal
  scaling is not supported by this release.

Production startup **fails fast** unless all of the following are set:

| Variable | Purpose |
|---|---|
| `CHEILOSCAN_ENV=production` | Disables Flask debug mode |
| `CHEILOSCAN_SECRET_KEY` | ≥32 random characters |
| `CHEILOSCAN_AUTH_USERNAME` | Single Basic-auth account name |
| `CHEILOSCAN_AUTH_PASSWORD_HASH` | Werkzeug password hash |
| `CHEILOSCAN_BEHIND_PROXY=1` | Trust `X-Forwarded-*` from exactly one proxy hop |
| `CHEILOSCAN_FORCE_HTTPS=1` | Redirect plain HTTP to HTTPS |
| `CHEILOSCAN_ALLOWED_HOSTS` | Comma-separated public hostnames |

Generate the two secrets:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
python -m app.security hash-password
```

### 3.2 Docker Compose (recommended)

1. Copy `.env.example` to `.env` and set the production values above.
   At minimum: `CHEILOSCAN_SECRET_KEY`, `CHEILOSCAN_AUTH_USERNAME`,
   `CHEILOSCAN_AUTH_PASSWORD_HASH`, `CHEILOSCAN_ALLOWED_HOSTS`.
2. Build and start:

   ```bash
   docker compose up -d --build
   docker compose logs -f cheiloscan
   ```

3. Put a TLS reverse proxy in front of `127.0.0.1:8000` (or an internal Docker
   network). See `deploy/nginx.conf.example`. The proxy must **overwrite**
   incoming `X-Forwarded-*` headers rather than append to them; otherwise a
   client could spoof the trusted proxy hop. The bundled Waitress process
   preserves these headers (`clear_untrusted_proxy_headers=False`), so its port
   must never be exposed directly to clients.
4. Verify: `https://<host>/api/health/live` returns `{"status":"ok"}` without
   credentials; protected pages prompt for Basic auth.

The image installs dependencies from `uv.lock`, runs as a non-root user, stores
data in the `cheiloscan-data` volume mounted at `/data`, and exposes a Docker
healthcheck against the public liveness endpoint.

### 3.3 Bare metal / Windows service

```bash
uv sync --frozen --no-dev
# set production environment variables, then:
uv run --no-dev python serve.py
```

`serve.py` starts Waitress with one process and at most four threads. A
Gunicorn-style WSGI server can import `wsgi.py:app`, but it **must be run with
one worker**; multiple workers race on SQLite schema initialization and writes.

For Windows, run `serve.py` under a service manager (for example NSSM or Task
Scheduler) and terminate TLS at a proxy on the same host. Do not use `run.py`
in production — it starts the Werkzeug development server.

### 3.4 Health checks

| Endpoint | Auth | Purpose |
|---|---|---|
| `GET /api/health/live` | Public | Process liveness only; deliberately bypasses Host/TLS checks so container probes work over loopback HTTP |
| `GET /api/health/ready` | Basic | Database connectivity, schema, storage writability/free space |
| `GET /api/health` | Basic | Detailed versions, database and storage usage |

Only `/api/health/live` bypasses host and HTTPS checks; everything else still
requires the configured public `Host` and a proxy-supplied HTTPS request in
production.

### 3.5 Backups

The data directory contains the SQLite database and both image stores. Never
copy only `app.sqlite` while the app is running: WAL contents may still be
pending. Create a consistent database snapshot and copy the assets:

```bash
python -c "import sqlite3; s=sqlite3.connect('data/db/app.sqlite'); d=sqlite3.connect('backup.sqlite'); s.backup(d); d.close(); s.close()"
cp -a data/original data/derived <backup-location>/
```

Restore with the application stopped, replace the data directory, then start
the app. Migrations are idempotent and run at every startup.

---

## 4. Security model

- Single Basic-auth account; no sessions, cookies, or user roles. Put
  per-user access control and rate limiting at the reverse proxy if more than
  one researcher needs access.
- Failed logins are throttled in-process (`CHEILOSCAN_AUTH_MAX_FAILURES`,
  `CHEILOSCAN_AUTH_LOCKOUT_SECONDS`); this counter is per process and resets
  on restart.
- Uploads are checked by magic bytes, real decoding, header dimensions, a
  pixel budget, and absolute size/dimension limits **before** pixel buffers
  are allocated.
- Stored paths are content-addressed and confined to the data directory;
  symlinks escaping that directory are rejected.
- Security headers, host allowlisting, same-origin checks for unsafe methods,
  HSTS on HTTPS responses, and conservative cache policies are enabled. Asset
  responses use `Cache-Control: private, no-store` so images are not retained by
  shared browsers.
- Logs can contain exception details, SQL parameters and local paths. Treat
  logs as sensitive research data and restrict access to them.
- `/api/assets/<id>/file` serves images to any authenticated caller. There is
  no per-sample authorization in this release.

---

## 5. API summary

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health/live`, `/api/health/ready`, `/api/health` | Health |
| GET | `/api/dashboard/stats` | Real counts and measured storage usage |
| GET | `/api/samples` | Paginated sample list |
| POST | `/api/samples/upload` | Multipart image intake (`file` field) |
| POST | `/api/analysis/<sample_id>/process` | Run preprocessing (JSON params) |
| GET | `/api/analysis/<analysis_id>` | Run detail + artifacts + measured results |
| GET | `/api/analyses` | Paginated run history |
| GET | `/api/comparisons` | Paginated comparison history (empty in this release) |
| GET | `/api/assets/<asset_id>/file` | Stored image bytes |

All JSON errors use `{"error": {"code", "message", "details"}, "request_id"}`.

---

## 6. Repository layout

- `app/` — Flask HTTP layer: config, factory, routes, serializers, security.
- `cheiloscan/` — domain layer (no Flask imports): DB models/repositories,
  image intake/quality/preprocessing, storage, services.
- `web/` — dependency-free HTML/CSS/JS frontend, packaged as a static package.
- `tests/` — unit and integration suites (241 tests in this release).
- `docs/` — architecture, methodology, implementation plan, testing strategy,
  development log.
- `serve.py`, `wsgi.py`, `Dockerfile`, `docker-compose.yml`, `deploy/` —
  deployment artifacts.

See `docs/DEVELOPMENT_LOG.md` for design decisions and phase history.
