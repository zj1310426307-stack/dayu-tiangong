"""编排受控 RAG、只读业务工具、安全回答和报告持久化。"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from hashlib import sha256
from io import BytesIO
import json
from os import getenv
from pathlib import Path
from time import perf_counter
from typing import Any
from xml.etree import ElementTree
from zipfile import ZipFile

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ai.assistant import WaterAI
from ai.assistant.provider import CompatibleChatProvider, ProviderConfig
from ai.guardrails import enforce_answer_policy, inspect_question
from ai.prompts import GROUNDED_SYSTEM_PROMPT
from ai.report import build_dispatch_report, markdown_to_pdf
from ai.retrieval import chunk_text, cosine_similarity, embed_text
from app.ai.models import (
    AIConversation,
    AIReport,
    AIToolCallLog,
    KnowledgeChunk,
    KnowledgeDocument,
)
from app.ai.schemas import (
    AIChatRequest,
    AIChatResponse,
    AIContext,
    AIToolCallLogRecord,
    KnowledgeDocumentRecord,
    KnowledgeSearchItem,
    KnowledgeSearchResponse,
    ReportGenerateRequest,
    ReportGenerateResponse,
    SourceCitation,
)
from app.gis.models import (
    CrossSection,
    DatasetVersion,
    Gate,
    OptimizationCandidate,
    OptimizationResult,
    OptimizationTask,
    Pump,
    River,
    SimulationResult,
    SimulationTask,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
KNOWLEDGE_ROOT = REPOSITORY_ROOT / "ai" / "knowledge"
REPORT_ROOT = REPOSITORY_ROOT / "backend" / "storage" / "ai-reports"
BUILTIN_KNOWLEDGE_VERSION = "phase6-builtin-v1"
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_EXTRACTED_BYTES = 20 * 1024 * 1024
MAX_PDF_PAGES = 200
SUPPORTED_SUFFIXES = {".md", ".txt", ".pdf", ".docx"}


class AIServiceError(RuntimeError):
    """表示可安全返回客户端的 AI 业务错误。"""


class AINotFoundError(AIServiceError):
    """表示请求引用的业务任务、知识或报告不存在。"""


def _source_json(sources: list[SourceCitation]) -> list[dict[str, Any]]:
    """把来源转为数据库 JSON 可持久化的数据。"""

    return [source.model_dump(mode="json") for source in sources]


def _document_record(session: Session, document: KnowledgeDocument) -> KnowledgeDocumentRecord:
    """返回文档元数据并实时聚合片段数。"""

    chunk_count = session.scalar(
        select(func.count(KnowledgeChunk.id)).where(KnowledgeChunk.document_id == document.id)
    ) or 0
    return KnowledgeDocumentRecord(
        id=document.id,
        name=document.name,
        category=document.category,
        version=document.version,
        source=document.source,
        source_type=document.source_type,
        content_hash=document.content_hash,
        chunk_count=int(chunk_count),
        upload_time=document.upload_time,
        updated_time=document.updated_time,
    )


def _decode_docx(content: bytes) -> str:
    """从 DOCX 的标准 document.xml 中提取段落文本。"""

    with ZipFile(BytesIO(content)) as archive:
        try:
            document_info = archive.getinfo("word/document.xml")
        except KeyError as exc:
            raise AIServiceError("DOCX 缺少标准正文结构") from exc
        if document_info.file_size > MAX_EXTRACTED_BYTES:
            raise AIServiceError("DOCX 解压后的正文不能超过 20 MB")
        xml = archive.read("word/document.xml")
    root = ElementTree.fromstring(xml)
    namespace = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    paragraphs = []
    for paragraph in root.iter(f"{namespace}p"):
        text = "".join(node.text or "" for node in paragraph.iter(f"{namespace}t"))
        if text.strip():
            paragraphs.append(text.strip())
    return "\n".join(paragraphs)


def _decode_pdf(content: bytes) -> str:
    """使用 pypdf 提取 PDF 页文本并保留页分隔标识。"""

    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover - 部署依赖缺失时的明确失败语义
        raise AIServiceError("PDF 解析依赖 pypdf 未安装") from exc
    reader = PdfReader(BytesIO(content))
    if len(reader.pages) > MAX_PDF_PAGES:
        raise AIServiceError("PDF 不能超过 200 页")
    pages = [f"[第 {index} 页]\n{page.extract_text() or ''}" for index, page in enumerate(reader.pages, 1)]
    return "\n\n".join(pages)


def _decode_document(filename: str, content: bytes) -> tuple[str, str]:
    """按白名单后缀提取 PDF、Word、Markdown 或文本内容。"""

    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise AIServiceError("仅支持 PDF、DOCX、Markdown 和 TXT 知识文档")
    if not content:
        raise AIServiceError("知识文档不能为空")
    if len(content) > MAX_UPLOAD_BYTES:
        raise AIServiceError("知识文档不能超过 10 MB")
    try:
        if suffix == ".pdf":
            text = _decode_pdf(content)
        elif suffix == ".docx":
            text = _decode_docx(content)
        else:
            text = content.decode("utf-8")
    except AIServiceError:
        raise
    except UnicodeDecodeError as exc:
        raise AIServiceError("Markdown/TXT 文档必须使用 UTF-8 编码") from exc
    except Exception as exc:
        raise AIServiceError("文档结构损坏或无法安全解析") from exc
    if not text.strip():
        raise AIServiceError("文档没有可检索文本")
    return text, suffix.lstrip(".")


def ingest_document(
    session: Session,
    *,
    name: str,
    category: str,
    version: str,
    source: str,
    filename: str,
    content: bytes,
) -> KnowledgeDocumentRecord:
    """解析、切分并在一个事务内替换指定来源版本的全部片段。"""

    if category not in {"regulations", "hydraulic", "dispatch", "engineering", "templates"}:
        raise AIServiceError("知识分类不受支持")
    text, source_type = _decode_document(filename, content)
    digest = sha256(content).hexdigest()
    document = session.scalar(
        select(KnowledgeDocument).where(
            KnowledgeDocument.source == source,
            KnowledgeDocument.version == version,
        )
    )
    if document is None:
        document = KnowledgeDocument(
            name=name,
            category=category,
            version=version,
            source=source,
            source_type=source_type,
            content_hash=digest,
        )
        session.add(document)
        session.flush()
    elif document.content_hash == digest:
        return _document_record(session, document)
    else:
        document.name = name
        document.category = category
        document.source_type = source_type
        document.content_hash = digest
        document.updated_time = datetime.now(UTC)
        session.query(KnowledgeChunk).filter(
            KnowledgeChunk.document_id == document.id
        ).delete(synchronize_session=False)
    for index, (chunk, location) in enumerate(chunk_text(text)):
        session.add(
            KnowledgeChunk(
                document_id=document.id,
                chunk_index=index,
                content=chunk,
                location=location,
                embedding=embed_text(chunk),
            )
        )
    session.commit()
    session.refresh(document)
    return _document_record(session, document)


def seed_builtin_knowledge(session: Session) -> list[KnowledgeDocumentRecord]:
    """幂等导入仓库内五类基础知识，供空数据库启动使用。"""

    records = []
    for path in sorted(KNOWLEDGE_ROOT.rglob("*.md")):
        relative = path.relative_to(KNOWLEDGE_ROOT).as_posix()
        records.append(
            ingest_document(
                session,
                name=path.stem,
                category=path.parent.name,
                version=BUILTIN_KNOWLEDGE_VERSION,
                source=f"repository://ai/knowledge/{relative}",
                filename=path.name,
                content=path.read_bytes(),
            )
        )
    return records


def list_documents(session: Session) -> list[KnowledgeDocumentRecord]:
    """按最新更新时间列出知识库清单。"""

    documents = session.scalars(
        select(KnowledgeDocument).order_by(KnowledgeDocument.updated_time.desc())
    ).all()
    return [_document_record(session, document) for document in documents]


def search_knowledge(
    session: Session,
    query: str,
    *,
    limit: int = 5,
    document_ids: list[int] | None = None,
) -> KnowledgeSearchResponse:
    """以余弦相似度检索知识片段并返回完整引用元数据。"""

    query_vector = embed_text(query)
    statement = select(KnowledgeChunk, KnowledgeDocument).join(
        KnowledgeDocument, KnowledgeDocument.id == KnowledgeChunk.document_id
    )
    if document_ids:
        statement = statement.where(KnowledgeDocument.id.in_(document_ids))
    rows = session.execute(statement).all()
    scored = [
        (
            cosine_similarity(query_vector, [float(value) for value in chunk.embedding]),
            chunk,
            document,
        )
        for chunk, document in rows
    ]
    scored.sort(key=lambda item: (-item[0], item[1].id))
    items = [
        KnowledgeSearchItem(
            document_id=document.id,
            document_name=document.name,
            category=document.category,
            version=document.version,
            source=document.source,
            location=chunk.location,
            content=chunk.content,
            score=round(max(score, 0.0), 6),
            updated_time=document.updated_time,
        )
        for score, chunk, document in scored[:limit]
        if score > 0
    ]
    return KnowledgeSearchResponse(query=query, items=items)


def _latest_dataset_id(session: Session) -> int | None:
    """返回最新数据版本主键，供未显式选择版本的只读查询使用。"""

    return session.scalar(select(DatasetVersion.id).order_by(DatasetVersion.id.desc()))


def get_river_info(session: Session, context: AIContext) -> tuple[dict[str, Any], SourceCitation]:
    """只读聚合河道、断面和闸泵数量与状态。"""

    dataset_id = context.dataset_version_id or _latest_dataset_id(session)
    if dataset_id is None:
        raise AINotFoundError("没有可用的数据版本")
    version = session.get(DatasetVersion, dataset_id)
    if version is None:
        raise AINotFoundError("数据版本不存在")
    river_filter = [River.dataset_version_id == dataset_id]
    if context.river_id is not None:
        river_filter.append(River.id == context.river_id)
    river_ids = select(River.id).where(*river_filter)
    river_count = session.scalar(select(func.count()).select_from(River).where(*river_filter)) or 0
    section_count = session.scalar(
        select(func.count()).select_from(CrossSection).where(
            CrossSection.dataset_version_id == dataset_id,
            CrossSection.river_id.in_(river_ids),
        )
    ) or 0
    gate_count = session.scalar(
        select(func.count()).select_from(Gate).where(
            Gate.dataset_version_id == dataset_id,
            Gate.river_id.in_(river_ids),
        )
    ) or 0
    pump_count = session.scalar(
        select(func.count()).select_from(Pump).where(
            Pump.dataset_version_id == dataset_id,
            Pump.river_id.in_(river_ids),
        )
    ) or 0
    status_rows = session.execute(
        select(Gate.status, func.count(Gate.id)).where(
            Gate.dataset_version_id == dataset_id, Gate.river_id.in_(river_ids)
        ).group_by(Gate.status)
    ).all() + session.execute(
        select(Pump.status, func.count(Pump.id)).where(
            Pump.dataset_version_id == dataset_id, Pump.river_id.in_(river_ids)
        ).group_by(Pump.status)
    ).all()
    status: dict[str, int] = {}
    for label, count in status_rows:
        status[str(label)] = status.get(str(label), 0) + int(count)
    evidence = {
        "kind": "river",
        "dataset_version_id": dataset_id,
        "river_count": int(river_count),
        "section_count": int(section_count),
        "gate_count": int(gate_count),
        "pump_count": int(pump_count),
        "status_summary": "、".join(f"{key} {value}" for key, value in sorted(status.items())) or "无设施状态",
    }
    source = SourceCitation(
        source_type="database",
        title=version.name,
        reference=f"dataset_version:{dataset_id}",
        version=version.version,
        updated_time=version.created_time,
        excerpt=f"河道 {river_count}，断面 {section_count}，闸门 {gate_count}，泵站 {pump_count}",
    )
    return evidence, source


def get_simulation_result(
    session: Session, context: AIContext
) -> tuple[dict[str, Any], SourceCitation]:
    """只读聚合成功任务的水位、流量、流速和警戒阈值。"""

    task = session.get(SimulationTask, context.simulation_task_id) if context.simulation_task_id else session.scalar(
        select(SimulationTask)
        .where(SimulationTask.status == "success")
        .order_by(SimulationTask.id.desc())
    )
    if task is None:
        raise AINotFoundError("没有可用的成功仿真任务")
    values = session.execute(
        select(
            func.max(SimulationResult.water_level),
            func.max(func.abs(SimulationResult.flow)),
            func.max(func.abs(SimulationResult.velocity)),
            func.count(SimulationResult.id),
        ).where(SimulationResult.task_id == task.id)
    ).one()
    if not values[3]:
        raise AINotFoundError("仿真任务没有结果行")
    warning_level = None
    latest_optimization = session.scalar(
        select(OptimizationTask)
        .where(OptimizationTask.simulation_case_id == task.case_id)
        .order_by(OptimizationTask.id.desc())
    )
    if latest_optimization is not None:
        warning_level = latest_optimization.objective_config.get("warning_level")
    maximum_level = float(values[0])
    if warning_level is None:
        risk_level = "数据不足（未配置警戒水位）"
    elif maximum_level > float(warning_level):
        risk_level = "超过已配置警戒水位"
    else:
        risk_level = "未超过已配置警戒水位"
    evidence = {
        "kind": "simulation",
        "task_id": task.id,
        "maximum_water_level": maximum_level,
        "maximum_flow": float(values[1]),
        "maximum_velocity": float(values[2]),
        "result_count": int(values[3]),
        "risk_level": risk_level,
        "warning_level": warning_level,
        "engine_version": task.engine_version or "unrecorded",
        "snapshot_hash": task.input_snapshot_hash or "unrecorded",
    }
    source = SourceCitation(
        source_type="simulation",
        title=f"水动力仿真任务 #{task.id}",
        reference=f"simulation_task:{task.id}",
        version=task.engine_version or "unrecorded",
        updated_time=task.end_time or task.created_time,
        excerpt=f"输入快照 {task.input_snapshot_hash or 'unrecorded'}；结果 {values[3]} 行",
    )
    return evidence, source


def get_optimization_result(
    session: Session, context: AIContext
) -> tuple[dict[str, Any], SourceCitation]:
    """只读返回成功优化任务的推荐、Pareto 与评价指标。"""

    task = session.get(OptimizationTask, context.optimization_task_id) if context.optimization_task_id else session.scalar(
        select(OptimizationTask)
        .where(OptimizationTask.status == "success")
        .order_by(OptimizationTask.id.desc())
    )
    if task is None:
        raise AINotFoundError("没有可用的成功优化任务")
    row = session.execute(
        select(OptimizationCandidate, OptimizationResult)
        .join(OptimizationResult, OptimizationResult.candidate_id == OptimizationCandidate.id)
        .where(
            OptimizationResult.task_id == task.id,
            OptimizationResult.recommendation_status == "recommended",
        )
    ).first()
    pareto_count = session.scalar(
        select(func.count(OptimizationResult.candidate_id)).where(
            OptimizationResult.task_id == task.id,
            OptimizationResult.pareto_level == 1,
        )
    ) or 0
    candidate = row[0] if row else None
    evidence = {
        "kind": "optimization",
        "task_id": task.id,
        "recommended_candidate_id": candidate.id if candidate else None,
        "pareto_count": int(pareto_count),
        "score": candidate.score if candidate else None,
        "objectives": ((candidate.objective_values or {}).get("values", {}) if candidate else {}),
        "metrics": (
            {
                key: value
                for key, value in (candidate.metrics or {}).items()
                if key != "comparison_series"
            }
            if candidate
            else {}
        ),
        "algorithm_version": task.algorithm_version,
        "snapshot_hash": task.input_snapshot_hash,
    }
    source = SourceCitation(
        source_type="optimization",
        title=f"多目标优化任务 #{task.id}",
        reference=f"optimization_task:{task.id}",
        version=task.algorithm_version,
        updated_time=task.end_time or task.created_time,
        excerpt=f"快照 {task.input_snapshot_hash}；第一 Pareto 前沿 {pareto_count} 个候选",
    )
    return evidence, source


def _call_tool(
    session: Session,
    tool_name: str,
    context: AIContext,
) -> tuple[dict[str, Any], SourceCitation, dict[str, Any]]:
    """执行固定只读工具并返回稍后持久化的审计记录。"""

    started = perf_counter()
    if tool_name == "get_river_info":
        output, source = get_river_info(session, context)
    elif tool_name == "get_simulation_result":
        output, source = get_simulation_result(session, context)
    elif tool_name == "get_optimization_result":
        output, source = get_optimization_result(session, context)
    else:
        raise AIServiceError("工具不在只读白名单中")
    log = {
        "tool_name": tool_name,
        "input": context.model_dump(mode="json"),
        "output": output,
        "duration_ms": max(0, int((perf_counter() - started) * 1000)),
    }
    return output, source, log


def _intent(question: str) -> str:
    """用可审计关键词选择最小必要工具，不允许模型自注册函数。"""

    lowered = question.lower()
    if any(word in lowered for word in ("优化", "推荐", "pareto", "方案")):
        return "optimization"
    if any(word in lowered for word in ("仿真", "模拟", "洪水", "水位", "流量", "流速", "风险")):
        return "simulation"
    if any(word in lowered for word in ("河道", "断面", "闸泵", "闸门", "泵站", "状态")):
        return "river"
    return "knowledge"


def _external_answer(
    question: str,
    evidence: list[dict[str, Any]],
    sources: list[SourceCitation],
) -> tuple[str | None, str]:
    """在管理员配置完整时调用兼容 LLM，否则返回本地生成路径。"""

    if getenv("AI_LLM_PROVIDER", "local") != "compatible":
        return None, "local-grounded-v1"
    base_url = getenv("AI_LLM_BASE_URL", "").strip()
    model = getenv("AI_LLM_MODEL", "").strip()
    api_key = getenv("AI_LLM_API_KEY", "").strip()
    if not all((base_url, model, api_key)):
        return None, "local-grounded-v1"
    provider = CompatibleChatProvider(ProviderConfig(base_url=base_url, model=model, api_key=api_key))
    prompt = json.dumps(
        {
            "question": question,
            "evidence": evidence,
            "sources": [item.model_dump(mode="json") for item in sources],
        },
        ensure_ascii=False,
    )
    try:
        return provider.complete(GROUNDED_SYSTEM_PROMPT, prompt), f"compatible:{model}"
    except Exception:
        return None, "local-grounded-v1"


def chat(session: Session, payload: AIChatRequest) -> AIChatResponse:
    """完成安全检查、检索/工具调用、回答生成与一次性审计提交。"""

    guard = inspect_question(payload.question)
    evidence: list[dict[str, Any]] = []
    sources: list[SourceCitation] = []
    pending_logs: list[dict[str, Any]] = []
    tools_used: list[str] = []
    intent = _intent(payload.question)
    if guard.status == "blocked":
        answer = guard.text
        safety_status = guard.status
        provider_name = "guardrail"
    else:
        try:
            if intent == "knowledge":
                result = search_knowledge(
                    session,
                    payload.question,
                    limit=5,
                    document_ids=payload.context.knowledge_document_ids,
                )
                for item in result.items:
                    evidence.append({"kind": "knowledge", "content": item.content})
                    sources.append(
                        SourceCitation(
                            source_type="knowledge",
                            title=item.document_name,
                            reference=f"knowledge_document:{item.document_id}#{item.location}",
                            version=item.version,
                            updated_time=item.updated_time,
                            excerpt=item.content[:220],
                        )
                    )
            else:
                tool_name = {
                    "optimization": "get_optimization_result",
                    "simulation": "get_simulation_result",
                    "river": "get_river_info",
                }[intent]
                output, source, log = _call_tool(session, tool_name, payload.context)
                evidence.append(output)
                sources.append(source)
                pending_logs.append(log)
                tools_used.append(tool_name)
        except AINotFoundError:
            evidence = []
            sources = []
        generated = WaterAI().analyze(
            {
                "question": payload.question,
                "intent": intent,
                "evidence": evidence,
                "sources": [item.model_dump(mode="json") for item in sources],
            }
        )
        external, provider_name = _external_answer(payload.question, evidence, sources)
        if external is not None:
            guarded = enforce_answer_policy(payload.question, external, has_sources=bool(sources))
            answer = guarded.text
            safety_status = guarded.status
        else:
            answer = str(generated["answer"])
            safety_status = str(generated["safety_status"])
    conversation = AIConversation(
        user_name=payload.user,
        question=payload.question,
        answer=answer,
        context=payload.context.model_dump(mode="json"),
        source=_source_json(sources),
        tools_used=tools_used,
        safety_status=safety_status,
        provider=provider_name,
    )
    session.add(conversation)
    session.flush()
    for log in pending_logs:
        session.add(
            AIToolCallLog(
                conversation_id=conversation.id,
                tool_name=log["tool_name"],
                input_data=log["input"],
                output_data=log["output"],
                duration_ms=log["duration_ms"],
            )
        )
    session.commit()
    session.refresh(conversation)
    return AIChatResponse(
        conversation_id=conversation.id,
        answer=conversation.answer,
        sources=sources,
        tools_used=conversation.tools_used,
        safety_status=conversation.safety_status,
        provider=conversation.provider,
        execution_authorized=False,
        created_time=conversation.created_time,
    )


def list_tool_logs(
    session: Session, *, limit: int = 50, offset: int = 0
) -> list[AIToolCallLogRecord]:
    """按时间倒序返回工具审计日志。"""

    rows = session.scalars(
        select(AIToolCallLog)
        .order_by(AIToolCallLog.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    return [
        AIToolCallLogRecord(
            id=row.id,
            conversation_id=row.conversation_id,
            tool_name=row.tool_name,
            input=row.input_data,
            output=row.output_data,
            duration_ms=row.duration_ms,
            time=row.time,
        )
        for row in rows
    ]


def generate_report(
    session: Session, payload: ReportGenerateRequest
) -> ReportGenerateResponse:
    """聚合三类只读工具证据并生成 Markdown/PDF 双格式报告。"""

    context: dict[str, Any] = {}
    sources: list[SourceCitation] = []
    logs: list[dict[str, Any]] = []
    for key, tool_name in (
        ("river", "get_river_info"),
        ("simulation", "get_simulation_result"),
        ("optimization", "get_optimization_result"),
    ):
        try:
            output, source, log = _call_tool(session, tool_name, payload.context)
        except AINotFoundError:
            continue
        context[key] = output
        sources.append(source)
        logs.append(log)
    if not sources:
        raise AINotFoundError("没有可用于报告的模型、优化或河道数据")
    markdown = build_dispatch_report(context, _source_json(sources))
    report = AIReport(
        created_by=payload.user,
        title="闸泵联合调度分析报告",
        report_type="gate-pump-dispatch-analysis",
        markdown_path="pending",
        pdf_path="pending",
        source=_source_json(sources),
    )
    session.add(report)
    session.flush()
    REPORT_ROOT.mkdir(parents=True, exist_ok=True)
    markdown_path = REPORT_ROOT / f"dispatch-analysis-{report.id}.md"
    pdf_path = REPORT_ROOT / f"dispatch-analysis-{report.id}.pdf"
    markdown_path.write_text(markdown, encoding="utf-8")
    markdown_to_pdf(markdown, pdf_path)
    report.markdown_path = str(markdown_path.relative_to(REPOSITORY_ROOT)).replace("\\", "/")
    report.pdf_path = str(pdf_path.relative_to(REPOSITORY_ROOT)).replace("\\", "/")
    for log in logs:
        session.add(
            AIToolCallLog(
                conversation_id=None,
                tool_name=log["tool_name"],
                input_data=log["input"],
                output_data=log["output"],
                duration_ms=log["duration_ms"],
            )
        )
    session.add(
        AIToolCallLog(
            conversation_id=None,
            tool_name="generate_report",
            input_data=payload.context.model_dump(mode="json"),
            output_data={"report_id": report.id, "formats": ["markdown", "pdf"]},
            duration_ms=0,
        )
    )
    session.commit()
    session.refresh(report)
    return ReportGenerateResponse(
        report_id=report.id,
        title=report.title,
        markdown_url=f"/api/v1/ai/reports/{report.id}/markdown",
        pdf_url=f"/api/v1/ai/reports/{report.id}/pdf",
        sources=sources,
        execution_authorized=False,
        notice="报告仅供人工复核，不具有 PLC、SCADA 或真实设备执行权限。",
        created_time=report.created_time,
    )


def get_report_file(session: Session, report_id: int, format_name: str) -> tuple[Path, str]:
    """解析数据库登记的报告路径并校验其仍位于受控目录。"""

    report = session.get(AIReport, report_id)
    if report is None:
        raise AINotFoundError("报告不存在")
    relative = report.markdown_path if format_name == "markdown" else report.pdf_path
    path = (REPOSITORY_ROOT / relative).resolve()
    root = REPORT_ROOT.resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise AINotFoundError("报告文件不存在或路径无效")
    media_type = "text/markdown; charset=utf-8" if format_name == "markdown" else "application/pdf"
    return path, media_type
