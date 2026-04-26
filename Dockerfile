# syntax=docker/dockerfile:1.7

# Multi-stage: builder uses uv to assemble a frozen .venv, then we copy that
# venv (and the source) into a slim runtime image.

FROM python:3.12-slim-bookworm AS builder

# uv is a single static binary — pull it from the official image
COPY --from=ghcr.io/astral-sh/uv:0.8 /uv /uvx /bin/

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Install deps in their own layer (cache-friendly)
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

# Now copy the project itself and install it into the venv
COPY src ./src
COPY README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev


# ---------- runtime ----------
FROM python:3.12-slim-bookworm AS runtime

# Required runtime libs only (no build toolchain)
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl ca-certificates tini \
    && rm -rf /var/lib/apt/lists/*

# Non-root user
RUN useradd --create-home --shell /bin/bash --uid 1000 app

WORKDIR /app

# Copy the venv and the source from the builder
COPY --from=builder --chown=app:app /app /app
COPY --chown=app:app .streamlit ./.streamlit

# Activate the venv on PATH
ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONPATH=/app/src \
    PYTHONUNBUFFERED=1 \
    OPTIONSMINER_DATA_DIR=/app/data

# Persistent volume mount-point — Coolify will bind a host path here
RUN mkdir -p /app/data && chown app:app /app/data
VOLUME ["/app/data"]

USER app
EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:8501/_stcore/health || exit 1

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["streamlit", "run", "src/optionsminer/ui/app.py", \
     "--server.port=8501", "--server.address=0.0.0.0", "--server.headless=true"]
