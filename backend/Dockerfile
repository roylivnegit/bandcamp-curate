FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# curl for the compose healthcheck.
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Install deps + package first (pyproject + the app package it points at) so this
# layer caches across source-only changes. `pip install .` needs the package dir,
# so app/ must be present before it runs.
COPY pyproject.toml ./
COPY app ./app
RUN pip install --upgrade pip && pip install .

# The rest of the source (alembic.ini, scripts, …); app/ is already present.
COPY . .

EXPOSE 8000

# API by default; the worker + migrate services override this in compose.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
