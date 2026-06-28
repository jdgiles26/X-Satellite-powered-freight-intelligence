FROM public.ecr.aws/docker/library/python:3.11-slim

# System dependencies for geospatial / ML stack
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ libgdal-dev libproj-dev gdal-bin \
    libgeos-dev curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first for layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application code
COPY . .

# Ensure data dirs exist
RUN mkdir -p /app/drishx_data/osm_cache /app/drishx_data/sh_cache /app/drishx_data/sentinel_data/detections

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8000/api/sites || exit 1

CMD ["uvicorn", "drishx:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
