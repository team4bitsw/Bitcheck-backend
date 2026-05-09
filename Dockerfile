# Cloud Run — container listens on $PORT (defaults to 8080 locally).
# Build from repo root:  docker build -t bitcheck-api ./Bitcheck-backend
# Run (needs env / DB / Redis for full app):  docker run --rm -p 8080:8080 -e PORT=8080 --env-file .env bitcheck-api

FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# psycopg2-binary needs libpq at runtime
RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY . .

# Collect static files at build time (whitenoise serves them at runtime).
# A dummy SECRET_KEY is used because the real one is injected at runtime.
RUN SECRET_KEY=__build_only__ \
    ALLOWED_HOSTS=* \
    DEBUG=True \
    python manage.py collectstatic --noinput

RUN useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8080

# WEB_CONCURRENCY: optional override for Cloud Run CPU allocation (try 1–4).
CMD ["sh", "-c", "exec gunicorn config.wsgi:application --bind 0.0.0.0:${PORT:-8080} --workers ${WEB_CONCURRENCY:-2} --threads 4 --access-logfile - --error-logfile - --timeout 0"]
