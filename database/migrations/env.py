"""Alembic 运行环境，从后端配置加载数据库并绑定 GIS 模型元数据。"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.database.config import load_database_config
from app.gis.models import Base


config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# URL 由环境变量控制，百分号需要转义以免被 ConfigParser 插值。
config.set_main_option("sqlalchemy.url", load_database_config().dsn.replace("%", "%%"))
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """在不建立连接时生成可审阅的 SQL 迁移。"""

    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """连接目标 PostgreSQL/PostGIS 并执行事务化迁移。"""

    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
