

FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
    && apt-get install --yes --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --system app && useradd --system --create-home --gid app app

WORKDIR /app

COPY backend /app/backend
COPY database /app/database

RUN python -m pip install --upgrade pip setuptools wheel \
    && pip install /app/backend \
    && mkdir -p /app/storage/private \
    && chown -R app:app /app

WORKDIR /app/backend

USER app

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
