# 使用固定 Python 主次版本，确保依赖解析与运行环境一致。
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app:/app/backend

WORKDIR /app

# GDAL/OGR is the mature conversion engine; Python only orchestrates bounded CLI calls.
RUN apt-get update \
    && apt-get install -y --no-install-recommends gdal-bin \
    && rm -rf /var/lib/apt/lists/*

# 先复制依赖清单以复用镜像缓存。
COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Build arguments live below the expensive dependency layers so a new source SHA
# does not invalidate the Python/GDAL runtime cache.
ARG ENGINE_VERSION=dayu-hydraulic-4.0.0
ARG ENGINE_COMMIT
ARG BUILD_MODE=release
ARG SOURCE_URL=https://github.com/zj1310426307-stack/dayu-tiangong

ENV DAYU_ENGINE_VERSION=${ENGINE_VERSION} \
    ENGINE_COMMIT=${ENGINE_COMMIT} \
    DAYU_BUILD_MODE=${BUILD_MODE}

LABEL org.opencontainers.image.title="Dayu Tiangong hydraulic runtime" \
      org.opencontainers.image.source=${SOURCE_URL} \
      org.opencontainers.image.version=${ENGINE_VERSION} \
      org.opencontainers.image.revision=${ENGINE_COMMIT}

# 后端运行时镜像包含后端源码、数据库迁移和导入模板，不挂载前端树。
COPY backend ./backend
COPY database ./database
COPY model ./model
COPY ai ./ai
COPY optimization ./optimization
COPY geoserver ./geoserver
COPY docs/templates ./docs/templates
COPY outputs/HYDRO-DATA-01-20260818 ./outputs/HYDRO-DATA-01-20260818

# A CI/release image is invalid unless its immutable SHA and Registry-bound build
# identity can be resolved during the image build itself.
RUN python -c "from model.build_identity import current_runtime_build_identity; current_runtime_build_identity()"

WORKDIR /app/backend

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=3s --retries=5 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/gis/health', timeout=2)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
