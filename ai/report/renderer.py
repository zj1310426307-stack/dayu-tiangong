"""使用确定性模板生成 Markdown 和无外部依赖的中文 PDF。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
import re


def build_dispatch_report(
    context: Mapping[str, object], sources: Sequence[Mapping[str, object]]
) -> str:
    """构建六章闸泵联合调度分析报告并保留证据标识。"""

    simulation = context.get("simulation") if isinstance(context.get("simulation"), Mapping) else {}
    optimization = context.get("optimization") if isinstance(context.get("optimization"), Mapping) else {}
    river = context.get("river") if isinstance(context.get("river"), Mapping) else {}
    source_lines = [
        f"- {item.get('title', '未命名来源')}｜{item.get('reference', '无引用')}｜版本 {item.get('version', '未标注')}"
        for item in sources
    ]
    return f"""# 闸泵联合调度分析报告

> 生成性质：AI 辅助的只读分析成果；仅供人工复核，不具有设备执行权限。

## 1 项目概况

- 坐标系统：CGCS2000（EPSG:4490）
- 数据版本：#{river.get('dataset_version_id', '未指定')}
- 河道 / 断面：{river.get('river_count', 0)} / {river.get('section_count', 0)}
- 闸门 / 泵站：{river.get('gate_count', 0)} / {river.get('pump_count', 0)}

## 2 当前工况

- 仿真任务：#{simulation.get('task_id', '无')}
- 模型版本：{simulation.get('engine_version', '未记录')}
- 输入快照：{simulation.get('snapshot_hash', '未记录')}
- 状态摘要：{river.get('status_summary', '无可用状态')}

## 3 模型结果

- 最高水位：{float(simulation.get('maximum_water_level', 0) or 0):.3f} m
- 最大流量：{float(simulation.get('maximum_flow', 0) or 0):.3f} m³/s
- 最大流速：{float(simulation.get('maximum_velocity', 0) or 0):.3f} m/s
- 风险标记：{simulation.get('risk_level', '数据不足')}

## 4 优化方案

- 优化任务：#{optimization.get('task_id', '无')}
- 推荐候选：#{optimization.get('recommended_candidate_id', '无')}
- Pareto 候选数：{optimization.get('pareto_count', 0)}
- 算法版本：{optimization.get('algorithm_version', '未记录')}
- 优化快照：{optimization.get('snapshot_hash', '未记录')}

## 5 风险分析

- 当前结果来自模型与 DEMO 数据时，不能替代真实工程率定和现场复核。
- 推荐来自第一 Pareto 前沿的版本化权重排序，不代表唯一正确方案。
- 缺失的实测、规范或设备信息必须标记为数据不足，禁止推测补齐。

## 6 建议措施

- 由水利工程师核对边界条件、率定状态、约束和来源版本。
- 在审批系统外不得执行本报告中的任何模拟动作。
- 若需真实调度，必须进入独立的人工审批与设备安全联锁流程。

## 数据来源

{chr(10).join(source_lines) if source_lines else '- 无可核验来源'}
"""


def _pdf_escape_utf16(text: str) -> str:
    """把一行 Unicode 文本编码为 PDF Type0 字体可消费的十六进制串。"""

    return text.encode("utf-16-be").hex().upper()


def _pdf_escape_ascii(text: str) -> str:
    """转义 Helvetica 文本中的 PDF 字符串控制符。"""

    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _wrap_display_text(text: str, maximum_units: float) -> list[str]:
    """按中西文近似显示宽度换行，避免长哈希和引用溢出。"""

    lines: list[str] = []
    current = ""
    units = 0.0
    for character in text:
        character_units = 0.55 if " " <= character <= "~" else 1.0
        if current and units + character_units > maximum_units:
            lines.append(current.rstrip())
            current = ""
            units = 0.0
        current += character
        units += character_units
    if current or not lines:
        lines.append(current.rstrip())
    return lines


def _render_pdf_text(text: str, size: int) -> list[str]:
    """在同一行按字符集切换中文 CID 字体与 Helvetica。"""

    text = text.replace("³", "^3")
    operations: list[str] = []
    for run in re.findall(r"[\x20-\x7e]+|[^\x20-\x7e]+", text):
        if all(" " <= character <= "~" for character in run):
            operations.extend((f"/F2 {size} Tf", f"({_pdf_escape_ascii(run)}) Tj"))
        else:
            operations.extend((f"/F1 {size} Tf", f"<{_pdf_escape_utf16(run)}> Tj"))
    return operations


def markdown_to_pdf(markdown: str, output_path: Path) -> None:
    """把 Markdown 文本渲染为中西文字体分流的分页 PDF。

    该实现只承担可审计报告交付，不执行 HTML、脚本或外部资源加载。
    """

    output_path.parent.mkdir(parents=True, exist_ok=True)
    styled_lines: list[tuple[str, str]] = []
    for raw in markdown.splitlines():
        stripped = raw.strip()
        if not stripped:
            styled_lines.append(("blank", ""))
            continue
        if stripped.startswith("# "):
            style, text, width = "title", stripped[2:].strip(), 34.0
        elif stripped.startswith("## "):
            style, text, width = "heading", stripped[3:].strip(), 42.0
        elif stripped.startswith("> "):
            style, text, width = "note", stripped[2:].strip(), 52.0
        elif stripped.startswith("- "):
            style, text, width = "body", f"• {stripped[2:].strip()}", 54.0
        else:
            style, text, width = "body", stripped, 54.0
        styled_lines.extend((style, line) for line in _wrap_display_text(text, width))

    heights = {"title": 28, "heading": 22, "note": 18, "body": 16, "blank": 3}
    pages: list[list[tuple[str, str]]] = []
    current_page: list[tuple[str, str]] = []
    used_height = 0
    for item in styled_lines or [("blank", "")]:
        height = heights[item[0]]
        if current_page and used_height + height > 730:
            pages.append(current_page)
            current_page = []
            used_height = 0
        current_page.append(item)
        used_height += height
    pages.append(current_page)

    objects: list[bytes] = []
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    page_ids = [6 + index * 2 for index in range(len(pages))]
    kids = " ".join(f"{page_id} 0 R" for page_id in page_ids)
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>".encode())
    objects.append(
        b"<< /Type /Font /Subtype /Type0 /BaseFont /STSong-Light "
        b"/Encoding /UniGB-UCS2-H /DescendantFonts [4 0 R] >>"
    )
    objects.append(
        b"<< /Type /Font /Subtype /CIDFontType0 /BaseFont /STSong-Light "
        b"/CIDSystemInfo << /Registry (Adobe) /Ordering (GB1) /Supplement 4 >> >>"
    )
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    for page_index, lines in enumerate(pages):
        content_id = page_ids[page_index] + 1
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
            f"/Resources << /Font << /F1 3 0 R /F2 5 0 R >> >> "
            f"/Contents {content_id} 0 R >>".encode()
        )
        operations = [
            "0.32 0.40 0.44 rg",
            "BT", "/F2 8 Tf", "48 812 Td", "(DAYU TIANGONG | PHASE 6 AI REPORT) Tj", "ET",
            "0.78 0.82 0.84 RG", "48 803 m", "547 803 l", "S",
            "0.10 0.16 0.19 rg", "BT", "48 778 Td",
        ]
        for style, line in lines:
            size = {"title": 17, "heading": 13, "note": 10, "body": 10, "blank": 10}[style]
            leading = heights[style]
            if style == "title":
                operations.append("0.06 0.39 0.42 rg")
            elif style == "heading":
                operations.append("0.08 0.30 0.34 rg")
            elif style == "note":
                operations.append("0.35 0.39 0.41 rg")
            else:
                operations.append("0.10 0.16 0.19 rg")
            operations.extend(_render_pdf_text(line, size))
            operations.append(f"0 -{leading} Td")
        operations.append("ET")
        operations.extend(
            (
                "0.42 0.47 0.49 rg",
                "BT", "/F2 8 Tf", "48 30 Td",
                f"(Page {page_index + 1} / {len(pages)} | AI-assisted, human review required) Tj",
                "ET",
            )
        )
        stream = "\n".join(operations).encode("ascii")
        objects.append(
            f"<< /Length {len(stream)} >>\nstream\n".encode()
            + stream
            + b"\nendstream"
        )

    document = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for object_id, payload in enumerate(objects, start=1):
        offsets.append(len(document))
        document.extend(f"{object_id} 0 obj\n".encode())
        document.extend(payload)
        document.extend(b"\nendobj\n")
    xref_offset = len(document)
    document.extend(f"xref\n0 {len(objects) + 1}\n".encode())
    document.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        document.extend(f"{offset:010d} 00000 n \n".encode())
    document.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_offset}\n%%EOF\n".encode()
    )
    output_path.write_bytes(document)
