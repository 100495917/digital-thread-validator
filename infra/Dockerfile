# syntax=docker/dockerfile:1
# Container image for the Smart Thermostat API.
#
# Build and run from the repository root:
#   docker build -f infra/Dockerfile -t digital-thread-validator .
#   docker run --rm -p 8000:8000 digital-thread-validator

FROM python:3.11-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY pipeline ./pipeline
COPY src ./src

RUN pip install --no-cache-dir --prefix=/install .


FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src

WORKDIR /app

COPY --from=builder /install /usr/local
COPY src /app/src
COPY pipeline /app/pipeline

RUN useradd --create-home --home-dir /home/app --uid 10001 --shell /usr/sbin/nologin app \
    && chown -R app:app /app

USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/status', timeout=4).read()"]

CMD ["uvicorn", "thermostat.api:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
