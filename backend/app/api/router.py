"""聚合系统全部 HTTP 路由，保持注册顺序清晰可审计。"""

from fastapi import APIRouter

from app.api.routes import system
from app.cross_section.router import router as cross_section_router
from app.dataset.router import router as dataset_router
from app.dispatch.router import router as dispatch_router
from app.gis.router import router as gis_router
from app.import_service.router import router as import_router
from app.model_engine.router import router as model_engine_router
from app.river.router import router as river_router
from app.structure.router import router as structure_router
from app.validation.router import router as validation_router


# 固定系统路由在通配业务路由之前注册，避免未来出现路径优先级冲突。
api_router = APIRouter()
api_router.include_router(system.router)
api_router.include_router(gis_router)
api_router.include_router(river_router)
api_router.include_router(cross_section_router)
api_router.include_router(structure_router)
api_router.include_router(model_engine_router)
api_router.include_router(dispatch_router)
api_router.include_router(dataset_router)
api_router.include_router(import_router)
api_router.include_router(validation_router)
