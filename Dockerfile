# Battery Research Workbench — single-port image (built SPA + /api/v1 on one origin).
# Multi-arch (linux/amd64, linux/arm64): all scientific deps ship official wheels.
#
# Python runtime dependencies are resolved by uv.lock and installed frozen.
# data/raw keeps source assets immutable; Compose allows new imports and can
# mount it read-only for analysis-only deployments.

FROM node:24-alpine AS ui
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.13-slim AS python-deps
COPY --from=ghcr.io/astral-sh/uv:0.12.19 /uv /uvx /bin/
WORKDIR /srv/brw
COPY pyproject.toml README.md uv.lock ./
COPY src ./src
COPY configs ./configs
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
RUN uv sync --frozen --no-dev --extra ml --no-install-project

FROM python:3.13-slim AS runtime
WORKDIR /srv/brw
COPY --from=python-deps /srv/brw/.venv /srv/brw/.venv
COPY src ./src
COPY configs ./configs
COPY --from=ui /build/dist /srv/brw/frontend/dist

# non-root; /srv/brw/data is the bind-mounted workdir (processed/artifacts
# must be writable; raw is read by contract). HOST=0.0.0.0 binds all ifaces
# inside the container network namespace; host publishing stays 127.0.0.1 in
# docker run/compose.
RUN useradd -r -u 10001 brw && mkdir -p /srv/brw/data && chown -R brw /srv/brw
USER brw

ENV PATH=/srv/brw/.venv/bin:$PATH \
    PYTHONPATH=/srv/brw/src \
    BRW_STATIC_DIR=/srv/brw/frontend/dist \
    BRW_PROCESSED_ROOT=/srv/brw/data/processed \
    BRW_RAW_ROOT=/srv/brw/data/raw \
    BRW_RUNS_ROOT=/srv/brw/data/artifacts/runs \
    HOST=0.0.0.0 \
    PYTHONUNBUFFERED=1

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=4).status==200 else 1)"

CMD ["python", "-m", "uvicorn", "battery_workbench.api.serve:app", "--host", "0.0.0.0", "--port", "8000"]
