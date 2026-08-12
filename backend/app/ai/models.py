"""持久化 AI 会话、知识文档、检索片段、工具日志和报告。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.gis.models import Base


class AIConversation(Base):
    """保存一轮问题、受来源约束的回答和安全判定。"""

    __tablename__ = "ai_conversation"
    __table_args__ = (Index("ix_ai_conversation_created_time", "created_time"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_name: Mapped[str] = mapped_column("user", String(64), nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    context: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    source: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    tools_used: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    safety_status: Mapped[str] = mapped_column(String(32), nullable=False)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    created_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    tool_calls: Mapped[list["AIToolCallLog"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan"
    )


class KnowledgeDocument(Base):
    """保存知识文档的来源、分类、版本与内容校验和。"""

    __tablename__ = "knowledge_document"
    __table_args__ = (
        UniqueConstraint("source", "version", name="uq_knowledge_document_source_version"),
        Index("ix_knowledge_document_category", "category"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    source_type: Mapped[str] = mapped_column(String(16), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    upload_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    chunks: Mapped[list["KnowledgeChunk"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )


class KnowledgeChunk(Base):
    """保存可引用位置和确定性向量的知识片段。"""

    __tablename__ = "knowledge_chunk"
    __table_args__ = (
        UniqueConstraint("document_id", "chunk_index", name="uq_knowledge_chunk_position"),
        Index("ix_knowledge_chunk_document_id", "document_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_document.id", ondelete="CASCADE"), nullable=False
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    location: Mapped[str] = mapped_column(String(128), nullable=False)
    embedding: Mapped[list[float]] = mapped_column(JSON, nullable=False)
    created_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    document: Mapped[KnowledgeDocument] = relationship(back_populates="chunks")


class AIToolCallLog(Base):
    """审计每次只读工具调用的输入、输出和耗时。"""

    __tablename__ = "ai_tool_call_log"
    __table_args__ = (
        Index("ix_ai_tool_call_log_conversation_id", "conversation_id"),
        Index("ix_ai_tool_call_log_time", "time"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int | None] = mapped_column(
        ForeignKey("ai_conversation.id", ondelete="CASCADE")
    )
    tool_name: Mapped[str] = mapped_column(String(64), nullable=False)
    input_data: Mapped[dict[str, Any]] = mapped_column("input", JSON, nullable=False)
    output_data: Mapped[dict[str, Any]] = mapped_column("output", JSON, nullable=False)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    conversation: Mapped[AIConversation | None] = relationship(back_populates="tool_calls")


class AIReport(Base):
    """记录报告文件、来源快照与生成者，便于受控下载。"""

    __tablename__ = "ai_report"
    __table_args__ = (Index("ix_ai_report_created_time", "created_time"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int | None] = mapped_column(
        ForeignKey("ai_conversation.id", ondelete="SET NULL")
    )
    created_by: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    report_type: Mapped[str] = mapped_column(String(64), nullable=False)
    markdown_path: Mapped[str] = mapped_column(Text, nullable=False)
    pdf_path: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    created_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
