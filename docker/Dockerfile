# Stage 1: build dependencies
FROM python:3.12-slim AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
RUN pip install --no-cache-dir --prefix=/install ".[dev]"

# Stage 2: runtime image
FROM python:3.12-slim AS runtime

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

# Non-root user
RUN groupadd --gid 1001 appgroup && \
    useradd --uid 1001 --gid appgroup --no-create-home --shell /bin/bash appuser

WORKDIR /app

COPY --from=builder /install /usr/local
COPY auth_service/ ./auth_service/
COPY alembic/ ./alembic/
COPY alembic.ini ./

RUN chown -R appuser:appgroup /app

USER appuser

EXPOSE 8000

CMD ["sh", "-c", "alembic upgrade head && uvicorn auth_service.main:app --host 0.0.0.0 --port 8000"]
