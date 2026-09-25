# Battery Research Workbench — single-port image (built SPA + /api/v1 on one origin).
# Multi-arch (linux/amd64, linux/arm64): all scientific deps ship official wheels.
#
# build:  docker build -t brw-workbench .
# run:    docker run -p 127.0.0.1:8000:8000 -v "$PWD/data:/srv/brw/data" brw-workbench
# data/raw stays immutable by contract — mount it read-only where possible.

FROM node:24-alpine AS ui
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.13-slim AS runtime
WORKDIR /srv/brw
COPY pyproject.toml README.md ./
COPY src ./src
COPY --from=ui /build/dist /srv/brw/frontend/dist
RUN pip install --no-cache-dir .

# non-root; /srv/brw/data is the bind-mounted workdir (processed/artifacts
# must be writable; raw is read by contract). HOST=0.0.0.0 binds all ifaces
# inside the container network namespace; host publishing stays 127.0.0.1 in
# docker run/compose.
RUN useradd -r -u 10001 brw && mkdir -p /srv/brw/data && chown -R brw /srv/brw
USER brw

ENV BRW_STATIC_DIR=/srv/brw/frontend/dist \
    BRW_PROCESSED_ROOT=/srv/brw/data/processed \
    BRW_RAW_ROOT=/srv/brw/data/raw \
    BRW_RUNS_ROOT=/srv/brw/data/artifacts/runs \
    HOST=0.0.0.0 \
    PYTHONUNBUFFERED=1

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=4).status==200 else 1)"

CMD ["python", "-m", "uvicorn", "battery_workbench.api.serve:app", "--host", "0.0.0.0", "--port", "8000"]
