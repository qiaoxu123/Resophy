# ============================================================
# Resophy Docker Image
# Multi-stage build: builder -> runtime
# ============================================================

# ------ Stage 1: Builder ------
FROM python:3.11-slim AS builder

WORKDIR /build

# System deps for building Python packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# Install uv (fast Python package manager)
RUN pip install --no-cache-dir uv

# Copy project files
COPY pyproject.toml uv.lock README.md ./
COPY resophy/ ./resophy/

# Install dependencies into a virtual env
RUN uv venv /build/.venv && \
    uv sync --frozen --no-dev

# ------ Stage 2: Runtime ------
FROM python:3.11-slim AS runtime

WORKDIR /app

# Runtime system deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    libmagic1 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy virtual env from builder
COPY --from=builder /build/.venv /app/.venv

# Copy application code
COPY app.py ./
COPY resophy/ ./resophy/
COPY templates/ ./templates/
COPY static/ ./static/
COPY deploy/ ./deploy/

# Ensure venv is on PATH
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Application defaults (overridden by docker-compose env or .env)
ENV RESOPHY_HOST=0.0.0.0
ENV RESOPHY_PORT=7191
ENV PAPERS_DIR=/app/papers_storage

# Healthcheck
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -f http://localhost:${RESOPHY_PORT}/ || exit 1

EXPOSE ${RESOPHY_PORT}

CMD ["python", "app.py", \
     "--host", "0.0.0.0", \
     "--port", "7191", \
     "--papers-dir", "/app/papers_storage"]
