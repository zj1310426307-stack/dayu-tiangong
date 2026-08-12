# 使用固定 Python 主次版本，确保依赖解析与运行环境一致。
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app:/app/backend

WORKDIR /app

# 先复制依赖清单以复用镜像缓存。
COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# 后端运行时镜像包含后端源码、数据库迁移和导入模板，不挂载前端树。
COPY backend ./backend
COPY database ./database
COPY model ./model
COPY docs/templates ./docs/templates

WORKDIR /app/backend

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=3s --retries=5 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/gis/health', timeout=2)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
