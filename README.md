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

Requires Python 3.12 (pinned in `.python-version`; `pyproject.toml` still
permits 3.11+) and [uv](https://docs.astral.sh/uv/). Vercel's Python runtime
supports 3.12–3.14 only, so pinning 3.11 makes its `uv sync --active` build fail
with "No interpreter found for Python 3.11".

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

There are two supported deployment profiles:

- **Local / container (default):** one trusted TLS-terminating reverse proxy,
  a persistent volume for `CHEILOSCAN_DATA_DIR` (SQLite + image store), and one
  application process. SQLite/WAL supports one writer.
- **Vercel (serverless):** a persistent Postgres/Neon database and Vercel Blob
  replace the local disk. Vercel terminates TLS and supplies the trusted
  proxy headers; no long-running local process is required.

Basic credentials must never cross an unencrypted network in either profile.

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

The image installs dependencies from `uv.lock`, stores data in the
`cheiloscan-data` volume mounted at `/data`, and exposes a Docker healthcheck
against the public liveness endpoint. `docker-entrypoint.sh` fixes ownership of
a newly mounted (root-owned) volume and then drops to the non-root
`cheiloscan` user before starting Waitress.

### 3.3 Render (Blueprint)

`render.yaml` deploys the same Docker image with a persistent disk, one instance
and Render's TLS proxy. The Blueprint uses a paid `1c-2g` plan because Render
persistent disks are not available on the free plan.

1. In Render, choose **New → Blueprint** and connect
   `https://github.com/Mevis-byte/Cheiloscan`.
2. During Blueprint creation, supply the three `sync: false` variables:
   - `CHEILOSCAN_ALLOWED_HOSTS` — your Render hostname (for example
     `cheiloscan.onrender.com`) and any custom domain, comma-separated, **no
     scheme**.
   - `CHEILOSCAN_AUTH_USERNAME` — the Basic-auth user.
   - `CHEILOSCAN_AUTH_PASSWORD_HASH` — generate with
     `python -m app.security hash-password`.
   `CHEILOSCAN_SECRET_KEY` is generated automatically by Render.
3. Deploy. Render listens on port `10000` and checks `/api/health/live`, which
   is public and bypasses Host/TLS checks.
4. Verify protected pages prompt for Basic auth and that
   `https://<your-host>/api/health/ready` returns database/storage status.

Do **not** add a second instance: the SQLite/WAL data directory on the disk
supports one writer process only.

### 3.4 Vercel (serverless)

Vercel is supported with durable external services. `vercel.json` points the
Python runtime at `wsgi:app`, `public/` holds the static UI, and `render.yaml`
is ignored by Vercel. The application detects `VERCEL=1` and automatically uses
production settings, trusted-proxy HTTPS handling, Postgres and Vercel Blob.

1. Create a Vercel project from `https://github.com/Mevis-byte/Cheiloscan`
   (`main`). Framework preset **Flask**, Python `3.12`.
2. Add a **Neon Postgres** integration (or any Postgres URL) and set:
   - `CHEILOSCAN_DATABASE_URL` — the pooled connection string. Generic
     `postgresql://` URLs are normalized to the installed `psycopg` driver.
   - `BLOB_READ_WRITE_TOKEN` — from a Vercel Blob store in the same project.
   - `CHEILOSCAN_SECRET_KEY` — ≥32 random characters.
   - `CHEILOSCAN_AUTH_USERNAME` and `CHEILOSCAN_AUTH_PASSWORD_HASH`.
   - `CHEILOSCAN_ALLOWED_HOSTS` — your `*.vercel.app` host and custom domain,
     comma-separated, no scheme. These default to Vercel's advertised hosts if
     omitted, but list custom domains explicitly.
3. Optional: `CHEILOSCAN_BLOB_ACCESS=private` (default) or `public`;
   `CHEILOSCAN_STORAGE_PREFIX` to isolate environments.
4. Deploy. The Build Command runs `scripts/sync_public.py` from
   `[tool.vercel.scripts]`, so `public/` always matches `web/`.
5. Verify `/api/health/live` (public) and `/api/health/ready` (Basic auth).
   Uploads are limited to **4 MB** by default because Vercel Functions accept
   4.5 MB request bodies. To raise it, enable Vercel's 20 MiB large-body beta
   and set `CHEILOSCAN_MAX_UPLOAD_MB=20`.

The schema is initialized under a Postgres advisory lock at cold start, so
concurrent function instances cannot race migrations. Database connections use
`NullPool` (fresh connection per unit of work). Asset bytes are streamed, so
image responses are not subject to Vercel's buffered 4.5 MB response limit.
The in-process failed-login throttle is per function instance, not global;
put a platform-level rate limiter in front if that matters for your threat
model. Daily snapshots are still your responsibility — see §3.7.

### 3.5 Bare metal / Windows service

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

### 3.6 Health checks

| Endpoint | Auth | Purpose |
|---|---|---|
| `GET /api/health/live` | Public | Process liveness only; deliberately bypasses Host/TLS checks so container probes work over loopback HTTP |
| `GET /api/health/ready` | Basic | Database connectivity, schema, storage writability/free space |
| `GET /api/health` | Basic | Detailed versions, database and storage usage |

Only `/api/health/live` bypasses host and HTTPS checks; everything else still
requires the configured public `Host` and a proxy-supplied HTTPS request in
production.

### 3.7 Backups

The data directory contains the SQLite database and both image stores. Never
copy only `app.sqlite` while the app is running: WAL contents may still be
pending. Create a consistent database snapshot and copy the assets:

```bash
python -c "import sqlite3; s=sqlite3.connect('data/db/app.sqlite'); d=sqlite3.connect('backup.sqlite'); s.backup(d); d.close(); s.close()"
cp -a data/original data/derived <backup-location>/
```

Restore with the application stopped, replace the data directory, then start
the app. Migrations are idempotent and run at every startup.

For Vercel deployments, back up the Neon/Postgres database with the provider's
export/snapshot tooling and version the Vercel Blob objects under the
configured prefix; Vercel does not retain uploaded application data for you.

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
