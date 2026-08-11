"""集中管理数据库连接配置和 SQLAlchemy 连接串。"""

from dataclasses import dataclass
from os import getenv


@dataclass(frozen=True, slots=True)
class DatabaseConfig:
    """保存 PostgreSQL 连接参数，便于后续依赖注入和测试替换。"""

    host: str = "localhost"
    port: int = 5432
    name: str = "dayu_tiangong"
    user: str = "dayu"
    password: str = "dayu_dev"
    database_url: str | None = None

    @property
    def dsn(self) -> str:
        """生成 SQLAlchemy 可消费的 PostgreSQL DSN。"""

        if self.database_url:
            return self.database_url
        return (
            f"postgresql+psycopg://{self.user}:{self.password}"
            f"@{self.host}:{self.port}/{self.name}"
        )


def load_database_config() -> DatabaseConfig:
    """从环境变量加载配置，未配置时使用仅限本地开发的默认值。"""

    return DatabaseConfig(
        host=getenv("POSTGRES_HOST", "localhost"),
        port=int(getenv("POSTGRES_PORT", "5432")),
        name=getenv("POSTGRES_DB", "dayu_tiangong"),
        user=getenv("POSTGRES_USER", "dayu"),
        password=getenv("POSTGRES_PASSWORD", "dayu_dev"),
        database_url=getenv("DATABASE_URL"),
    )
