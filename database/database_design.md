# 大禹·天工 Phase 6 数据库设计

业务空间统一 CGCS2000 / EPSG:4490；数值距离使用米制桩号和河段长度。权威演进为 Alembic `0001 → 0007`。

## 表域

| 领域 | 表 | 关键语义 |
|---|---|---|
| 数据/空间 | `dataset_version`、`river*`、`cross_section` | 版本隔离、有向河网、稳定节点身份、GIST 4490 |
| 结构物 | `gate`、`pump` | 静态可用性 + 明确河段/节点拓扑 + 设备约束/Q-H/Q-η |
| 模型输入 | `model_parameter`、`boundary_condition`、`simulation_case`、`simulation_case_boundary` | 一个方案显式关联一组外边界 |
| 任务 | `simulation_task` | 冻结快照/hash/引擎来源、队列、认领、心跳、取消、重试、诊断 |
| 调度 | `dispatch_plan`、`dispatch_action`、`dispatch_rule`、`dispatch_run` | 草稿—校验—冻结—归档，冻结 JSON 和 hash |
| 结果 | `simulation_result`、`junction_result`、`structure_result`、`dispatch_event` | 断面、节点、闸泵、请求/实际/原因审计 |
| 优化 | `optimization_task`、`optimization_candidate`、`optimization_result` | 冻结快照、候选仿真链路、Pareto 与人工推荐 |
| AI | `ai_conversation`、`knowledge_document`、`knowledge_chunk`、`ai_tool_call_log`、`ai_report` | 来源回答、版本知识、检索片段、工具审计与报告 |

`structure_result` 保存上下游水位、扬程差、泵转输类型、流量、功率、累计能耗、流态与约束标识。`junction_result` 对每个任务—节点—时刻唯一。

## 状态与约束

- 任务：`pending → queued → running → success|failed|cancelled`，可进入 `cancel_requested`。
- 计划：`draft → validated → frozen → archived`；冻结内容不能就地修改，只能克隆新版本。
- 动作必须恰有一个 `gate_id` 或 `pump_id`；跨数据版本引用在冻结前拒绝。
- 所有时间为 UTC；前端本地化显示。

## 迁移

- `20260811_0001`：GIS 基线。
- `20260811_0002`：版本化水利数据库/拓扑。
- `20260812_0003`：EPSG:4490 与 Phase 3 任务结果。
- `20260812_0004`：快照、边界组、异步字段、闸泵拓扑、调度和节点/结构结果。
- `20260812_0005`：结构结果扬程差与泵转输语义。
- `20260812_0006`：优化任务、候选和 Pareto 结果。
- `20260812_0007`：AI 会话、知识/片段、工具调用和报告。

幂等 seed 在已有完整拓扑时复用节点，避免破坏历史结果外键和可追溯性。
