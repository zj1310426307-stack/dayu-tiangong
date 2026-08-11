"""提供最小且一致的应用日志配置。"""

import logging


def configure_logging() -> None:
    """初始化控制台日志格式，保留 Uvicorn 已存在的处理器。"""

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
