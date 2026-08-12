"""GeoJSON 校验、PostGIS 写入表达式与序列化工具。"""

import json
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session


def validate_geometry(geometry: dict[str, Any], expected_type: str) -> None:
    """校验基础 GeoJSON 类型、坐标范围和最小点数。"""

    if geometry.get("type") != expected_type:
        raise ValueError(f"geometry.type 必须是 {expected_type}")
    coordinates = geometry.get("coordinates")
    if expected_type == "Point":
        _validate_position(coordinates)
        return
    if not isinstance(coordinates, list) or len(coordinates) < 2:
        raise ValueError("LineString 至少需要两个坐标点")
    for position in coordinates:
        _validate_position(position)


def _validate_position(position: Any) -> None:
    """校验单个 CGCS2000 地理二维坐标。"""

    if not isinstance(position, list) or len(position) != 2:
        raise ValueError("坐标必须是 [longitude, latitude]")
    longitude, latitude = position
    if not isinstance(longitude, (int, float)) or not isinstance(latitude, (int, float)):
        raise ValueError("经纬度必须是数值")
    if not -180 <= longitude <= 180 or not -90 <= latitude <= 90:
        raise ValueError("经纬度超出 CGCS2000 / EPSG:4490 范围")


def geometry_expression(geometry: dict[str, Any], expected_type: str) -> Any:
    """把已校验 GeoJSON 转换为 SRID 4490 的 PostGIS 表达式。"""

    validate_geometry(geometry, expected_type)
    return func.ST_SetSRID(func.ST_GeomFromGeoJSON(json.dumps(geometry)), 4490)


def geometry_json(session: Session, geometry_column: Any) -> dict[str, Any]:
    """把一个 ORM 几何字段转换为可 JSON 序列化的 GeoJSON 对象。"""

    raw = session.scalar(func.ST_AsGeoJSON(geometry_column, 8))
    if raw is None:
        raise ValueError("空间对象缺少 geometry")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("数据库返回了无效 GeoJSON")
    return value


def point_coordinates(geometry: dict[str, Any]) -> tuple[float, float]:
    """返回通过校验的 Point 经度、纬度。"""

    validate_geometry(geometry, "Point")
    longitude, latitude = geometry["coordinates"]
    return float(longitude), float(latitude)
