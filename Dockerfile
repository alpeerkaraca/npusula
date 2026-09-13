# Production image for the EnPusula API.
# Dependencies are installed from the uv lockfile; the CPU-only PyTorch build
# is added separately because the Windows DirectML variant cannot install on
# Linux (the device manager degrades to CPU when DirectML is unavailable).
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# Dependency layer (cached unless pyproject.toml / uv.lock change)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# CPU-only torch: required by the backend import chain on Linux
RUN uv pip install --python /app/.venv/bin/python \
    torch --index-url https://download.pytorch.org/whl/cpu

# OpenMP runtime required by LightGBM (not present in debian-slim)
RUN apt-get update \
 && apt-get install -y --no-install-recommends libgomp1 \
 && rm -rf /var/lib/apt/lists/*

# Application code
COPY backend ./backend
COPY scripts ./scripts
COPY NOTICE.md ./

# Non-root runtime user (bind-mounted ./artifacts must be writable by UID 10001)
RUN useradd --create-home --uid 10001 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

CMD ["uvicorn", "backend.app:app", "--host", "0.0.0.0", "--port", "8000"]
