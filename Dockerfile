# CheiloScan production image: single Waitress process, non-root, persistent /data.
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    CHEILOSCAN_ENV=production \
    CHEILOSCAN_DATA_DIR=/data \
    CHEILOSCAN_HOST=0.0.0.0 \
    CHEILOSCAN_PORT=8000

WORKDIR /app

# Install exactly the versions recorded in uv.lock, then the project itself.
COPY pyproject.toml uv.lock ./
RUN pip install --no-cache-dir uv==0.11.26 \
    && uv export --frozen --no-dev --no-emit-project --format requirements.txt -o /tmp/requirements.txt \
    && pip install --no-cache-dir -r /tmp/requirements.txt \
    && rm /tmp/requirements.txt

COPY app ./app
COPY cheiloscan ./cheiloscan
COPY web ./web
COPY wsgi.py serve.py ./

RUN pip install --no-cache-dir --no-deps . \
    && groupadd --gid 10001 cheiloscan \
    && useradd --uid 10001 --gid 10001 --create-home cheiloscan \
    && mkdir -p /data \
    && chown -R cheiloscan:cheiloscan /data /app

VOLUME ["/data"]
USER 10001:10001
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health/live', timeout=3).status == 200 else 1)"]

CMD ["python", "serve.py"]
