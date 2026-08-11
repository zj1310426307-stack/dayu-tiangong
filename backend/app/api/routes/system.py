"""系统信息与健康检查接口。"""

from fastapi import APIRouter, status

from app.models.system import HealthResponse, SystemInfoResponse
from app.services.system_service import get_health_status, get_system_info


router = APIRouter(tags=["system"])


@router.get(
    "/",
    response_model=SystemInfoResponse,
    summary="获取平台基础信息",
)
def read_system_info() -> SystemInfoResponse:
    """返回任务书约定的平台名称、版本、说明与运行状态。"""

    return get_system_info()


@router.get(
    "/api/v1/health",
    response_model=HealthResponse,
    status_code=status.HTTP_200_OK,
    summary="检查应用健康状态",
)
def read_health() -> HealthResponse:
    """返回应用层健康状态，供 Docker 与外部烟测共同使用。"""

    return get_health_status()
