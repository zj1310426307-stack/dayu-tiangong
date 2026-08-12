"""阻断设备控制、结果篡改和审批绕过表达。"""

from __future__ import annotations

from dataclasses import dataclass
import re


CONTROL_PATTERNS = (
    re.compile(r"(?:立即|马上|现在|直接)?.{0,8}(?:打开|关闭|启动|停机|下发|执行).{0,10}(?:闸|泵|机组|设备)"),
    re.compile(r"(?:闸|泵|机组|设备).{0,12}(?:打开|关闭|启动|停机|下发|执行)"),
    re.compile(r"(?:PLC|SCADA).{0,12}(?:控制|写入|下发|连接)", re.IGNORECASE),
)
TAMPER_PATTERNS = (
    re.compile(r"(?:修改|篡改|覆盖|重排).{0,10}(?:评分|Pareto|水动力结果|仿真结果)", re.IGNORECASE),
    re.compile(r"(?:绕过|跳过|无需).{0,8}(?:审批|确认|人工复核)"),
)
UNSAFE_ANSWER_PATTERN = re.compile(
    r"(?:请|应当|必须|立即|马上).{0,8}(?:打开|关闭|启动|停机).{0,10}(?:闸|泵|机组|设备)"
)


@dataclass(frozen=True, slots=True)
class GuardrailResult:
    """保存安全策略判定、原因和最终可展示文本。"""

    status: str
    reason: str | None
    text: str


def inspect_question(question: str) -> GuardrailResult:
    """识别请求是否试图触发设备控制、篡改结果或绕过审批。"""

    normalized = question.strip()
    if any(pattern.search(normalized) for pattern in CONTROL_PATTERNS):
        return GuardrailResult(
            status="blocked",
            reason="device_control_request",
            text=(
                "我不能生成或下发真实设备控制命令。可以改为分析模拟方案，例如："
                "“模拟结果显示某闸开度为 80%，该建议仍需工程师人工确认”。"
            ),
        )
    if any(pattern.search(normalized) for pattern in TAMPER_PATTERNS):
        return GuardrailResult(
            status="blocked",
            reason="result_tampering_or_approval_bypass",
            text=(
                "我不能修改优化评分、Pareto 排序、水动力结果，也不能绕过人工审批。"
                "我可以只读解释现有证据并标明来源。"
            ),
        )
    return GuardrailResult(status="allowed", reason=None, text="")


def enforce_answer_policy(
    question: str, answer: str, *, has_sources: bool
) -> GuardrailResult:
    """对最终回答执行第二道门禁，避免提供方输出越过系统边界。"""

    question_result = inspect_question(question)
    if question_result.status == "blocked":
        return question_result
    if UNSAFE_ANSWER_PATTERN.search(answer):
        return GuardrailResult(
            status="rewritten",
            reason="unsafe_control_language",
            text=(
                "检测到回答可能被误解为真实设备控制命令，已停止输出。"
                "请仅将模型结果作为模拟建议并交由工程师人工确认。"
            ),
        )
    if not has_sources:
        return GuardrailResult(
            status="insufficient_evidence",
            reason="missing_sources",
            text="当前没有可核验的数据来源，无法形成工程结论。",
        )
    return GuardrailResult(status="allowed", reason=None, text=answer.strip())
