"""Worker 启动或运维调用的僵尸任务恢复入口。"""

from app.database.session import SessionLocal
from app.worker.lifecycle import recover_stale_tasks


def recover_stale_running_tasks(stale_seconds: int = 120) -> list[int]:
    """使用独立会话恢复心跳过期任务并返回受影响 ID。"""

    with SessionLocal() as session:
        return recover_stale_tasks(session, stale_seconds)
