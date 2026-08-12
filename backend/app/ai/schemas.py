"""定义 AI 助手、检索、工具审计和报告的严格 HTTP 契约。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    """拒绝未知字段，避免前端上下文被静默忽略。"""

    model_config = ConfigDict(extra="forbid")


class AIContext(StrictModel):
    """限定 AI 可引用的稳定业务主键。"""

    dataset_version_id: int | None = Field(default=None, gt=0)
    river_id: int | None = Field(default=None, gt=0)
    simulation_task_id: int | None = Field(default=None, gt=0)
    optimization_task_id: int | None = Field(default=None, gt=0)
    knowledge_document_ids: list[int] = Field(default_factory=list, max_length=20)


class SourceCitation(StrictModel):
    """描述回答中的一个可核验来源。"""

    source_type: Literal["knowledge", "database", "simulation", "optimization"]
    title: str
    reference: str
    version: str
    updated_time: datetime | None = None
    excerpt: str | None = None


class AIChatRequest(StrictModel):
    """接收一轮受控对话问题和可选业务上下文。"""

    question: str = Field(min_length=2, max_length=2000)
    user: str = Field(default="engineer", min_length=1, max_length=64)
    context: AIContext = Field(default_factory=AIContext)


class AIChatResponse(StrictModel):
    """返回回答、证据、工具与不可执行标记。"""

    conversation_id: int
    answer: str
    sources: list[SourceCitation]
    tools_used: list[str]
    safety_status: str
    provider: str
    execution_authorized: Literal[False] = False
    created_time: datetime


class KnowledgeSearchItem(StrictModel):
    """返回一个带文档元数据和引用位置的检索片段。"""

    document_id: int
    document_name: str
    category: str
    version: str
    source: str
    location: str
    content: str
    score: float
    updated_time: datetime


class KnowledgeSearchResponse(StrictModel):
    """返回查询及按相似度排序的片段。"""

    query: str
    items: list[KnowledgeSearchItem]


class KnowledgeDocumentRecord(StrictModel):
    """返回已入库知识文档及片段数量。"""

    id: int
    name: str
    category: str
    version: str
    source: str
    source_type: str
    content_hash: str
    chunk_count: int
    upload_time: datetime
    updated_time: datetime


class AIToolCallLogRecord(StrictModel):
    """返回只读工具调用审计记录。"""

    id: int
    conversation_id: int | None
    tool_name: str
    input: dict[str, Any]
    output: dict[str, Any]
    duration_ms: int
    time: datetime


class ReportGenerateRequest(StrictModel):
    """选择业务上下文生成一份只读调度分析报告。"""

    user: str = Field(default="engineer", min_length=1, max_length=64)
    context: AIContext = Field(default_factory=AIContext)


class ReportGenerateResponse(StrictModel):
    """返回报告下载地址和数据来源。"""

    report_id: int
    title: str
    markdown_url: str
    pdf_url: str
    sources: list[SourceCitation]
    execution_authorized: Literal[False] = False
    notice: str
    created_time: datetime
