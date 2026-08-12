"""创建 Redis broker 驱动的 Celery 应用并支持测试 eager mode。"""

from os import getenv

from celery import Celery


celery_app = Celery(
    "dayu_tiangong",
    broker=getenv("CELERY_BROKER_URL", "redis://localhost:6379/0"),
    backend=getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/1"),
    include=["app.worker.tasks", "app.optimization.tasks"],
)
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_always_eager=getenv("CELERY_TASK_ALWAYS_EAGER", "0") == "1",
    task_eager_propagates=True,
)
