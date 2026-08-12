"""提供不依赖数据库的确定性水利助手回答器。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from ai.guardrails import enforce_answer_policy


class WaterAI:
    """把已核验的工具与知识证据整理为安全回答。

    该类不读取数据库、不运行模型，也不拥有设备执行能力。后端服务负责
    收集证据并把它们作为 ``evidence`` 传入，因此生成层无法旁路业务接口。
    """

    def analyze(self, input_data: Mapping[str, Any]) -> dict[str, Any]:
        """基于问题、意图和证据生成可追溯回答。

        Args:
            input_data: 包含 ``question``、``intent``、``evidence`` 和 ``sources``
                的映射；所有字段均来自调用方的受控编排。

        Returns:
            包含回答、安全状态和来源数量的结构化结果。
        """

        if not isinstance(input_data, Mapping):
            raise TypeError("input_data 必须是映射类型")
        question = str(input_data.get("question", "")).strip()
        intent = str(input_data.get("intent", "knowledge"))
        evidence = input_data.get("evidence", [])
        sources = input_data.get("sources", [])
        if not isinstance(evidence, Sequence) or isinstance(evidence, (str, bytes)):
            raise TypeError("evidence 必须是序列")
        if not isinstance(sources, Sequence) or isinstance(sources, (str, bytes)):
            raise TypeError("sources 必须是序列")

        answer = self._compose(question, intent, evidence)
        guarded = enforce_answer_policy(question, answer, has_sources=bool(sources))
        return {
            "answer": guarded.text,
            "safety_status": guarded.status,
            "source_count": len(sources),
            "execution_authorized": False,
        }

    def _compose(
        self, question: str, intent: str, evidence: Sequence[Any]
    ) -> str:
        """按受控意图选择模板，不在无证据时补造事实。"""

        normalized = [item for item in evidence if isinstance(item, Mapping)]
        if not normalized:
            return (
                "当前没有检索到足够的可核验数据，无法对该问题给出工程结论。"
                "请补充任务编号、对象编号或知识文档后重试。"
            )
        if intent == "optimization":
            return self._optimization_answer(normalized)
        if intent == "simulation":
            return self._simulation_answer(normalized)
        if intent == "river":
            return self._river_answer(normalized)
        return self._knowledge_answer(normalized)

    @staticmethod
    def _optimization_answer(evidence: Sequence[Mapping[str, Any]]) -> str:
        """解释推荐候选及其可核验目标值。"""

        item = next((row for row in evidence if row.get("kind") == "optimization"), None)
        if item is None or item.get("recommended_candidate_id") is None:
            return "所选优化任务尚无满足硬约束的推荐候选，不能生成推荐解释。"
        objectives = item.get("objectives") or {}
        return (
            f"任务 #{item.get('task_id')} 推荐候选 #{item.get('recommended_candidate_id')}，"
            "原因是它位于第一 Pareto 前沿，并在当前版本化权重下总分最低。"
            f"可核验目标值：防洪风险 {float(objectives.get('flood_risk', 0)):.4f}，"
            f"能耗成本 {float(objectives.get('energy_cost', 0)):.4f}，"
            f"操作成本 {float(objectives.get('operation_cost', 0)):.4f}。"
            "该结论只用于人工复核，不具有真实设备执行权限。"
        )

    @staticmethod
    def _simulation_answer(evidence: Sequence[Mapping[str, Any]]) -> str:
        """概括仿真任务的水位、流量、流速和风险口径。"""

        item = next((row for row in evidence if row.get("kind") == "simulation"), None)
        if item is None or item.get("task_id") is None:
            return "当前没有成功且包含结果的仿真任务，无法判断洪水风险。"
        return (
            f"仿真任务 #{item.get('task_id')} 的结果显示：最高水位 "
            f"{float(item.get('maximum_water_level', 0)):.3f} m，最大流量 "
            f"{float(item.get('maximum_flow', 0)):.3f} m³/s，最大流速 "
            f"{float(item.get('maximum_velocity', 0)):.3f} m/s。"
            f"当前风险标记为“{item.get('risk_level', '数据不足')}”。"
            "风险结论受 DEMO 数据、边界条件和模型率定状态限制，需工程师复核。"
        )

    @staticmethod
    def _river_answer(evidence: Sequence[Mapping[str, Any]]) -> str:
        """汇总河道、断面与闸泵只读信息。"""

        item = next((row for row in evidence if row.get("kind") == "river"), None)
        if item is None:
            return "未查询到匹配的河道或水工建筑物。"
        return (
            f"数据版本 #{item.get('dataset_version_id')} 当前包含河道 "
            f"{item.get('river_count', 0)} 条、断面 {item.get('section_count', 0)} 个、"
            f"闸门 {item.get('gate_count', 0)} 座、泵站 {item.get('pump_count', 0)} 座。"
            f"状态摘要：{item.get('status_summary', '无可用状态')}。"
        )

    @staticmethod
    def _knowledge_answer(evidence: Sequence[Mapping[str, Any]]) -> str:
        """从最高相关知识片段生成带范围声明的摘要。"""

        snippets = [
            str(item.get("content", "")).strip()
            for item in evidence
            if item.get("kind") == "knowledge" and item.get("content")
        ][:3]
        if not snippets:
            return "知识库没有检索到足够相关的内容，无法形成有依据的回答。"
        summary = "\n\n".join(f"- {snippet[:280]}" for snippet in snippets)
        return f"根据知识库中相关度最高的资料：\n{summary}\n以上内容需结合项目条件与现行规范复核。"
