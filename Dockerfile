# ============================================================
# Builder
# ============================================================
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

# Dependency layer
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project

# Application
COPY . .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen

# Only the Drive v3 descriptor is used (automation_v2/lib/google_drive.py, automation_v2/lib/costing_excel_parse.py).
# The other ~580 bundled API descriptors are ~99MB of dead weight.
RUN find /app/.venv -path "*/googleapiclient/discovery_cache/documents/*" \
    ! -name "drive.*.json" -delete

# ============================================================
# Runtime
# ============================================================
FROM python:3.12-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH" \
    CHROME_PATH=/usr/bin/chromium

WORKDIR /app

# Chromium for Playwright; apt resolves the GTK/X11/ATK/NSS chain itself
RUN apt-get update && apt-get install -y --no-install-recommends \
    chromium \
    fonts-liberation \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Application + venv in a single copy
COPY --from=builder /app /app

# Default worker
CMD ["python", "manage.py", "consume_tender_tasks"]
