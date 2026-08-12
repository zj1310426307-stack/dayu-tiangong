"""Add Phase 6 AI conversations, knowledge, tool audit and report tables.

Revision ID: 20260812_0007
Revises: 20260812_0006
Create Date: 2026-08-12
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260812_0007"
down_revision: str | None = "20260812_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create auditable AI/RAG tables without changing Phase 3-5 result data."""

    op.create_table(
        "ai_conversation",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user", sa.String(64), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("context", sa.JSON(), nullable=False),
        sa.Column("source", sa.JSON(), nullable=False),
        sa.Column("tools_used", sa.JSON(), nullable=False),
        sa.Column("safety_status", sa.String(32), nullable=False),
        sa.Column("provider", sa.String(64), nullable=False),
        sa.Column("created_time", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_ai_conversation_created_time", "ai_conversation", ["created_time"])
    op.create_table(
        "knowledge_document",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("category", sa.String(32), nullable=False),
        sa.Column("version", sa.String(64), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("source_type", sa.String(16), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("upload_time", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_time", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("source", "version", name="uq_knowledge_document_source_version"),
    )
    op.create_index("ix_knowledge_document_category", "knowledge_document", ["category"])
    op.create_table(
        "knowledge_chunk",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("document_id", sa.Integer(), sa.ForeignKey("knowledge_document.id", ondelete="CASCADE"), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("location", sa.String(128), nullable=False),
        sa.Column("embedding", sa.JSON(), nullable=False),
        sa.Column("created_time", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("document_id", "chunk_index", name="uq_knowledge_chunk_position"),
    )
    op.create_index("ix_knowledge_chunk_document_id", "knowledge_chunk", ["document_id"])
    op.create_table(
        "ai_tool_call_log",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("conversation_id", sa.Integer(), sa.ForeignKey("ai_conversation.id", ondelete="CASCADE")),
        sa.Column("tool_name", sa.String(64), nullable=False),
        sa.Column("input", sa.JSON(), nullable=False),
        sa.Column("output", sa.JSON(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("time", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_ai_tool_call_log_conversation_id", "ai_tool_call_log", ["conversation_id"])
    op.create_index("ix_ai_tool_call_log_time", "ai_tool_call_log", ["time"])
    op.create_table(
        "ai_report",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("conversation_id", sa.Integer(), sa.ForeignKey("ai_conversation.id", ondelete="SET NULL")),
        sa.Column("created_by", sa.String(64), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("report_type", sa.String(64), nullable=False),
        sa.Column("markdown_path", sa.Text(), nullable=False),
        sa.Column("pdf_path", sa.Text(), nullable=False),
        sa.Column("source", sa.JSON(), nullable=False),
        sa.Column("created_time", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_ai_report_created_time", "ai_report", ["created_time"])


def downgrade() -> None:
    """Remove Phase 6 tables in reverse dependency order."""

    op.drop_index("ix_ai_report_created_time", table_name="ai_report")
    op.drop_table("ai_report")
    op.drop_index("ix_ai_tool_call_log_time", table_name="ai_tool_call_log")
    op.drop_index("ix_ai_tool_call_log_conversation_id", table_name="ai_tool_call_log")
    op.drop_table("ai_tool_call_log")
    op.drop_index("ix_knowledge_chunk_document_id", table_name="knowledge_chunk")
    op.drop_table("knowledge_chunk")
    op.drop_index("ix_knowledge_document_category", table_name="knowledge_document")
    op.drop_table("knowledge_document")
    op.drop_index("ix_ai_conversation_created_time", table_name="ai_conversation")
    op.drop_table("ai_conversation")
