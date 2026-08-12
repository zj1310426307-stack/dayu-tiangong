"""提供系统信息和健康状态的业务读模型。"""

from app.models.system import HealthResponse, SystemInfoResponse


def get_system_info() -> SystemInfoResponse:
    """构造平台基础信息，避免路由层直接持有业务常量。"""

    return SystemInfoResponse(
        name="大禹·天工",
        version="3.0.0",
        description="河网智能调度与数字孪生水利平台",
        status="running",
    )


def get_health_status() -> HealthResponse:
    """返回应用层健康；数据库/PostGIS 健康由 GIS 专用端点表达。"""

    return HealthResponse(status="healthy", service="dayu-tiangong-api", version="3.0.0")
