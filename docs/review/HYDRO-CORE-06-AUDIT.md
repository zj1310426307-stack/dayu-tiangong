# HYDRO-CORE-06 审计：多引擎生产路由收口

- 审计日期：2026-09-24
- 基线：`main@8d2d432d77c37ecf4896b776b80d965d38d19800`
- 审计分支：`refactor/hydro-core-06-engine-routing`
- 结论：需要受控 schema/data migration；当前不能仅靠运行时推导满足不可变 Task 的显式引擎身份要求。

## 1. 当前路由图

```text
SimulationCase + Dataset Version
  ├─ Standard 1D API → freeze_hydraulic_1d_input(engine_id defaults to mascaret)
  │  → SimulationTask(task_kind=standard_1d; no engine_id column)
  │  → hydraulic-1d Worker → create_hydraulic_1d_engine() → MASCARET
  └─ frozen DispatchPlan hydraulic_v3
     → controlled_hydraulic_preview SimulationTask
     → hydraulic-1d Worker → create_hydraulic_1d_engine("d-flow-fm")
     → D-Flow FM / DIMR / FBC
```

两条路径都写入统一断面结果；受控 D-Flow 路径还写入 `StructureResult`。业务层没有第二套 D-Flow 河网、断面或结果领域模型。

## 2. MASCARET 执行路径

- `backend/app/model_engine/service.py` 创建并冻结标准一维任务。
- `backend/app/worker/tasks.py` 在 claim、快照 hash、构建身份和生产门通过后执行 MASCARET。
- 当前问题：Worker 和同步诊断运行均调用无参 `create_hydraulic_1d_engine()`；`factory.py` 的无参默认值为 `mascaret`。
- 现有 `solver_id`、`capability_id`、`runtime_adapter_id`、`result_schema_version`、`registry_hash` 和 build identity 已被持久化；但它们不能替代 Task 自身的显式 `engine_id`。

## 3. D-Flow FM 执行路径

- `backend/app/dispatch/hydraulic_service.py` 从冻结 `hydraulic_v3` 计划创建 `controlled_hydraulic_preview` Task。
- 该路径已写入 D-Flow solver、adapter、capability、selected-engine hash 与受控快照。
- Worker 对此 task kind 显式创建 `d-flow-fm`，执行 `run_controlled()`，复用同一 claim、heartbeat、取消、超时、attempt CAS 与最终化生命周期。
- 当前身份仍依赖 task kind 与快照合同的组合推导，而不是 SimulationTask 的统一 `engine_id`。

## 4. Engine identity 与 Registry

- `model/hydraulic_1d/registry.py` 已有不可变 MASCARET/D-Flow registration，含版本、solver、adapter、capability、schema、runtime mode、上游 tag/commit、许可证和 `production_eligible`。
- `engine_catalog_payload()` 已可同时列出两个 Engine，但 legacy `engine_registry_payload()` 仅哈希 MASCARET 并把 D-Flow 标记为 reserved。
- `HydraulicEngineRegistration` 尚未直接公开 evidence class；它来自 capability manifest，存在由多处拼接造成语义漂移的风险。

## 5. Capability enforcement

- `required_capabilities(model)` 已是 solver-neutral、确定性的统一推导入口，可推导网络、边界、结构和 CASIER 要求。
- `compatibility_report()` / `enforce_compatibility()` 已 fail closed，但当前以 `execution_policy + development_mode + production_mode` 三个参数表达执行等级。
- `CapabilityExecutionPolicy` 仅有 production 与 synthetic；尚无明确 `pilot` 语义，也未统一标准错误码。
- MASCARET Gate/Pump 为 `UNSUPPORTED`；D-Flow 只可走 synthetic accepted 子集且 `production_eligible=false`。这些边界必须原样保留。

## 6. Worker route 与兼容性

- `SimulationTask` 已持久化 snapshot、snapshot hash、engine version、solver/adapter/capability、result schema、registry hash、attempt token 与运行 build identity。
- `SimulationTask` 目前没有 `engine_id` 字段；`execution_mode` 是历史 v4 的 `validation|shadow` 字段，不能复用为本任务的 `production|pilot|synthetic`。
- 历史标准任务可由受控 input schema + MASCARET provenance 确定性识别；历史 controlled preview 可由 task kind + D-Flow provenance 确定性识别。
- 缺少这些可验证线索的旧任务必须只读并拒绝重新执行，不能默认为 MASCARET。

## 7. 隐式默认行为清单

1. `model/hydraulic_1d/factory.py` 为 `create_hydraulic_1d_engine()` 提供 MASCARET 默认参数。
2. `backend/app/worker/tasks.py` 标准 Worker 分支无参创建 Engine。
3. `backend/app/model_engine/service.py` 的同步诊断执行无参创建 Engine。
4. `backend/app/model_engine/service.py`、schemas 与 readiness 以 MASCARET default 常量固定标准任务 API。
5. `backend/app/model_engine/hydraulic_1d_service.py` 默认使用 MASCARET；这只能保留为明确的兼容/调用层默认，不能继续作为 Worker 选择依据。

## 8. Migration 判断

需要新增迁移，原因如下：

- 新 Task 必须不可变地保存 `engine_id` 与 `execution_class`；当前 `simulation_task` 没有前者，且既有 `execution_mode` 语义不兼容，不能借名复用。
- 数据迁移必须按可验证 provenance 回填：标准 unified input → `mascaret/production`；controlled preview → `d-flow-fm/synthetic`；无法确定者 → `legacy-unresolved`（只读、不可重新入队）。
- 迁移将只添加字段、约束和确定性回填；不会删改历史结果、Dataset Version 或调度快照。

## 9. 拟修改范围

- Registry / factory / router / capabilities：显式 Engine 解析、执行等级门禁、统一错误码、无 fallback。
- SimulationTask model、迁移、创建与历史读取：冻结 `engine_id`、`execution_class`、选中 registry hash。
- Worker 和同步诊断：只按 Task 冻结 identity 创建 Engine，并在运行前复核 identity、hash、执行等级与能力。
- API/OpenAPI/前端：Engine catalog、显式任务选择和真实 evidence banner；不暴露 Solver 私有文件。
- 文档：ADR、当前架构、能力矩阵、生产工作流、D-Flow 边界、clone plan、pilot profile、最终 review。
- 测试：registry、factory、routing/capability、历史 Task、Worker identity 和禁止无参生产调用的 architecture test。

## 10. 非目标与安全边界

- 不导入真实工程资料，不执行真实 D-Flow 工程模拟。
- D-Flow `production_eligible` 保持 false；Optimization、PLC/SCADA、设备命令和第二套领域模型均不在范围内。
- Adapter 继续是唯一 native 文件边界；结果继续写统一结果体系。
