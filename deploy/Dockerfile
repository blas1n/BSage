FROM python:3.11-slim AS backend

WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

# Install uv + node (for frontend build)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl git \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Copy application code first (needed for package build)
COPY pyproject.toml uv.lock* ./
COPY bsage/ ./bsage/
COPY plugins/ ./plugins/
COPY skills/ ./skills/

# Install Python dependencies
RUN uv pip install --system --no-cache .

# Build frontend
COPY frontend/ ./frontend/
RUN corepack enable && corepack prepare pnpm@10.33.0 --activate \
    && cd frontend && CI=true pnpm install --frozen-lockfile && pnpm run build

ENV PYTHONPATH=/app

# Create non-root user
RUN useradd --create-home --shell /bin/bash appuser \
    && mkdir -p /app/vault /app/tmp /app/.credentials /app/logs \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=5s --retries=3 --start-period=15s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"

CMD ["python", "-m", "uvicorn", "bsage.gateway.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
