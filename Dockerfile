# Stage 1: Build
FROM python:3.12-slim AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gdal-bin libgeos-dev libproj-dev gcc g++ \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv

WORKDIR /app
COPY pyproject.toml .
COPY src/ src/
RUN uv pip install --system --no-cache .

# Stage 2: Runtime
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 gdal-bin libgeos-c1v5 libproj25 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY --from=builder /app/src /app/src

ENV PYTHONPATH=/app/src

CMD ["uvicorn", "traffic_ai.main:app", "--host", "0.0.0.0", "--port", "8000"]
