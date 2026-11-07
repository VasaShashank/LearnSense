# LearnSense backend (FastAPI). Build: docker build -t learnsense-api .
# Runtime configuration is injected as environment variables / secrets; nothing
# secret is baked into the image (.dockerignore excludes .env files).
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    LEARNSENSE_ENV=production

# OCR runtime for ingestion (English + Hindi language data).
RUN apt-get update \
 && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng tesseract-ocr-hin \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# Unprivileged runtime user. /app/storage holds the file stores that have not yet
# moved to PostgreSQL (docs/architecture/persistence-strategy.md): mount a volume.
RUN useradd --create-home --uid 10001 learnsense \
 && mkdir -p /app/storage \
 && chown -R learnsense /app/storage
USER learnsense

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status == 200 else 1)"

# Migrations are NOT run here; deployments run `python scripts/migrate.py apply
# --dsn-env DATABASE_URL` as a separate release step (docs/deployment/deployment.md).
CMD ["uvicorn", "backend.app:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
