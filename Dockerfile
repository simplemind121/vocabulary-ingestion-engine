FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN groupadd --system vie && useradd --system --gid vie --home-dir /app vie

RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install --yes --no-install-recommends \
        tesseract-ocr \
        tesseract-ocr-chi-sim \
        tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY app ./app
COPY migrations ./migrations
COPY alembic.ini ./
# Optional OCR runtimes, e.g. --build-arg OCR_EXTRAS=ocr-rapid. Their models
# are fetched now because the running container has a read-only filesystem.
ARG OCR_EXTRAS=""
RUN if [ -n "$OCR_EXTRAS" ]; then \
      apt-get update \
      && apt-get install --yes --no-install-recommends libgomp1 libgl1 libglib2.0-0 \
      && rm -rf /var/lib/apt/lists/*; \
    fi
RUN pip install --no-cache-dir ".${OCR_EXTRAS:+[$OCR_EXTRAS]}" \
    && mkdir -p /app/data \
    && chown -R vie:vie /app
RUN case ",$OCR_EXTRAS," in *,ocr-rapid,*) \
      python -m app.adapters.rapidocr ;; \
    esac

USER vie
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/live', timeout=2)"]

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
