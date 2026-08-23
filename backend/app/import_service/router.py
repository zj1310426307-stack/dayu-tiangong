"""Excel、CSV、GeoJSON 导入与模板下载 HTTP 路由。"""

import csv
import json
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.database.session import get_database_session
from app import files
from app.import_service import service
from app.import_service.schemas import ImportResponse


router = APIRouter(prefix="/api/v1/import", tags=["data-import"])
SessionDependency = Annotated[Session, Depends(get_database_session)]
ResourceForm = Annotated[Literal["rivers", "cross_sections", "gates", "pumps"], Form()]
VersionForm = Annotated[int, Form(gt=0)]
FileUpload = Annotated[UploadFile, File()]
TEMPLATE_ROOT = Path(__file__).resolve().parents[3] / "docs" / "templates"
MAX_UPLOAD_BYTES = 20 * 1024 * 1024


async def _read_upload(file: UploadFile, expected_suffixes: set[str]) -> tuple[bytes, str]:
    """检查扩展名和大小后读取上传内容。"""

    filename = file.filename or "upload"
    suffix = Path(filename).suffix.lower()
    if suffix not in expected_suffixes:
        raise HTTPException(status_code=415, detail=f"仅支持 {', '.join(sorted(expected_suffixes))}")
    content = await files.read_limited_upload(file, MAX_UPLOAD_BYTES)
    if not content:
        raise HTTPException(status_code=422, detail="上传文件为空")
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="上传文件不得超过 20 MB")
    return content, filename


@router.post("/excel", response_model=ImportResponse, summary="批量导入 Excel")
async def import_excel(resource: ResourceForm, dataset_version_id: VersionForm, file: FileUpload, session: SessionDependency) -> ImportResponse:
    """存档并原子导入 Excel 活动工作表。"""

    content, filename = await _read_upload(file, {".xlsx"})
    stored = service.store_upload(filename, content)
    try:
        records = service.parse_excel(content)
    except (ValueError, KeyError, StopIteration) as exc:
        raise HTTPException(status_code=422, detail=f"Excel 解析失败：{exc}") from exc
    return service.import_records(session, resource, dataset_version_id, records, stored)


@router.post("/csv", response_model=ImportResponse, summary="批量导入 CSV")
async def import_csv(resource: ResourceForm, dataset_version_id: VersionForm, file: FileUpload, session: SessionDependency) -> ImportResponse:
    """存档并原子导入 UTF-8 CSV。"""

    content, filename = await _read_upload(file, {".csv"})
    stored = service.store_upload(filename, content)
    try:
        records = service.parse_csv(content)
    except (UnicodeDecodeError, csv.Error) as exc:
        raise HTTPException(status_code=422, detail=f"CSV 解析失败：{exc}") from exc
    return service.import_records(session, resource, dataset_version_id, records, stored)


@router.post("/geojson", response_model=ImportResponse, summary="批量导入 GeoJSON")
async def import_geojson(resource: ResourceForm, dataset_version_id: VersionForm, file: FileUpload, session: SessionDependency) -> ImportResponse:
    """存档并原子导入 FeatureCollection。"""

    content, filename = await _read_upload(file, {".geojson", ".json"})
    stored = service.store_upload(filename, content)
    try:
        records = service.parse_geojson(content)
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=422, detail=f"GeoJSON 解析失败：{exc}") from exc
    return service.import_records(session, resource, dataset_version_id, records, stored)


@router.get("/templates/{resource}", response_class=FileResponse, summary="下载 Excel 导入模板")
def download_template(resource: Literal["rivers", "cross_sections", "gates", "pumps"]) -> FileResponse:
    """返回与导入字段严格一致的版本化 Excel 模板。"""

    path = TEMPLATE_ROOT / f"phase2_{resource}_template.xlsx"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="导入模板尚未生成")
    return FileResponse(
        path,
        filename=path.name,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
