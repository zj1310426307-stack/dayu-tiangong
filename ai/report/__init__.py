"""公开调度报告与 PDF 生成能力。"""

from .renderer import build_dispatch_report, markdown_to_pdf

__all__ = ["build_dispatch_report", "markdown_to_pdf"]
