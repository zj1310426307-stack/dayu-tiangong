"""FastAPI 应用入口，负责装配中间件与路由。"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.utils.logging import configure_logging


def create_app() -> FastAPI:
    """创建可测试、可重复装配的 FastAPI 应用实例。"""

    configure_logging()
    application = FastAPI(
        title="大禹·天工 API",
        version="5.0.0",
        description="河网联合水动力、闸泵调度仿真、水利数据库及 GIS 空间接口",
    )

    # 开发阶段仅允许本地前端来源，生产环境应改为显式域名白名单。
    application.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["*"],
    )
    application.include_router(api_router)
    return application


# Uvicorn 通过 app.main:app 引用此模块级实例。
app = create_app()
