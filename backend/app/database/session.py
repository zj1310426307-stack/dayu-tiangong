"""创建 SQLAlchemy 引擎、会话工厂和 FastAPI 数据库依赖。"""

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.database.config import load_database_config


# 引擎只在首次执行 SQL 时连接，便于文档和非 GIS 测试离线加载应用。
engine = create_engine(
    load_database_config().dsn,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=5,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_database_session() -> Generator[Session, None, None]:
    """为单个 HTTP 请求提供独立数据库会话并确保结束后释放。"""

    with SessionLocal() as session:
        yield session
