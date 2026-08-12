"""提供 AI 对话、知识检索、报告和工具日志的薄 HTTP 路由。"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.ai import service
from app.ai.schemas import (
    AIChatRequest,
    AIChatResponse,
    AIToolCallLogRecord,
    KnowledgeDocumentRecord,
    KnowledgeSearchResponse,
    ReportGenerateRequest,
    ReportGenerateResponse,
)
from app.database.session import get_database_session


router = APIRouter(prefix="/api/v1/ai", tags=["ai-assistant"])
SessionDependency = Annotated[Session, Depends(get_database_session)]


def _http_error(exc: Exception) -> HTTPException:
    """把 AI 服务错误映射为稳定 HTTP 状态。"""

    code = status.HTTP_404_NOT_FOUND if isinstance(exc, service.AINotFoundError) else status.HTTP_422_UNPROCESSABLE_ENTITY
    return HTTPException(status_code=code, detail=str(exc))


@router.post("/chat", response_model=AIChatResponse, status_code=status.HTTP_201_CREATED)
def chat(payload: AIChatRequest, session: SessionDependency) -> AIChatResponse:
    """生成一轮有来源、不可执行且可审计的水利助手回答。"""

    try:
        return service.chat(session, payload)
    except service.AIServiceError as exc:
        raise _http_error(exc) from exc


@router.get("/knowledge/search", response_model=KnowledgeSearchResponse)
def search_knowledge(
    session: SessionDependency,
    q: str = Query(min_length=2, max_length=500),
    limit: int = Query(default=5, ge=1, le=20),
) -> KnowledgeSearchResponse:
    """返回包含来源、版本、更新时间和位置的相关知识片段。"""

    return service.search_knowledge(session, q, limit=limit)


@router.get("/knowledge/documents", response_model=list[KnowledgeDocumentRecord])
def list_documents(session: SessionDependency) -> list[KnowledgeDocumentRecord]:
    """列出已入库 PDF、Word、Markdown 与文本知识。"""

    return service.list_documents(session)


@router.post(
    "/knowledge/documents",
    response_model=KnowledgeDocumentRecord,
    status_code=status.HTTP_201_CREATED,
)
async def upload_document(
    session: SessionDependency,
    file: Annotated[UploadFile, File()],
    category: Annotated[str, Form()],
    version: Annotated[str, Form(min_length=1, max_length=64)],
) -> KnowledgeDocumentRecord:
    """上传并原子切分一份受支持的知识文档。"""

    filename = Path(file.filename or "unnamed").name
    try:
        return service.ingest_document(
            session,
            name=Path(filename).stem,
            category=category,
            version=version,
            source=f"upload://{filename}",
            filename=filename,
            content=await file.read(service.MAX_UPLOAD_BYTES + 1),
        )
    except service.AIServiceError as exc:
        session.rollback()
        raise _http_error(exc) from exc


@router.post("/report/generate", response_model=ReportGenerateResponse, status_code=201)
def generate_report(
    payload: ReportGenerateRequest, session: SessionDependency
) -> ReportGenerateResponse:
    """生成带任务快照和来源清单的 Markdown/PDF 调度报告。"""

    try:
        return service.generate_report(session, payload)
    except service.AIServiceError as exc:
        session.rollback()
        raise _http_error(exc) from exc


@router.get("/reports/{report_id}/{format_name}")
def download_report(
    report_id: int,
    format_name: str,
    session: SessionDependency,
) -> FileResponse:
    """仅下载数据库登记且位于受控报告目录的成果。"""

    if format_name not in {"markdown", "pdf"}:
        raise HTTPException(status_code=404, detail="报告格式不存在")
    try:
        path, media_type = service.get_report_file(session, report_id, format_name)
    except service.AIServiceError as exc:
        raise _http_error(exc) from exc
    suffix = ".md" if format_name == "markdown" else ".pdf"
    return FileResponse(path, media_type=media_type, filename=f"dispatch-analysis-{report_id}{suffix}")


@router.get("/tools/logs", response_model=list[AIToolCallLogRecord])
def list_tool_logs(
    session: SessionDependency,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> list[AIToolCallLogRecord]:
    """返回 AI 只读工具的输入、输出、耗时与会话关联。"""

    return service.list_tool_logs(session, limit=limit, offset=offset)
