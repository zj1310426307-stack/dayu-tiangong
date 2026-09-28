# ADR-HYDRO-0005：Explicit Hydraulic Engine Selection and Capability-Based Routing

- 状态：Accepted
- 日期：2026-09-24
- 适用范围：统一一维水动力任务、MASCARET、D-Flow FM 和受控闸泵预演

## 背景

平台已经拥有 MASCARET 与 D-Flow FM 两个 Adapter，但标准任务仍可通过无参 factory 隐式选择 MASCARET，受控 D-Flow Task 又由 task kind 与快照组合识别。该设计使一个不可变任务不能独立、明确地说明实际执行的 Engine，并给未来真实工程试点留下静默 fallback 风险。

## 决策

### 1. SimulationTask 是最终执行身份

每个新水动力 Task 必须冻结并持久化：

- `engine_id`、`engine_version`、`solver_id`、`runtime_adapter_id`；
- `capability_id`、selected `registry_hash`；
- `input_schema_version`、`result_schema_version`、`input_snapshot_hash`；
- `execution_class`：`production`、`pilot` 或 `synthetic`。

现有 build identity、runtime mode 和 attempt/token 字段继续复用；不新增第二份 Solver 或 Runtime 身份。

### 2. Worker 只执行 Task 已冻结的 Engine

生产 Worker、同步诊断执行和重试前验证都必须从 `task.engine_id` 解析 Engine。无参 `create_hydraulic_1d_engine()` 不能出现在生产路径。Task 的 Engine registration、版本、solver、adapter、capability、result schema 和 selected registry hash 任一不一致时均终止运行。

### 3. Engine Catalog 是选择与 provenance 的唯一来源

`HydraulicEngineRegistration` 同时描述 identity、runtime、许可证、evidence 和 capability matrix。API 只公开由 Catalog 派生的信息；业务层不得根据 Engine 名称猜测能力，也不得直接写 MASCARET XCAS、D-Flow MDU、DIMR XML 或 FBC。

### 4. 能力路由与执行等级

统一模型先确定性推导所需能力，再以选择的 Engine 和 `execution_class` 进行单一路径校验：

- `production`：仅 `production_eligible=true` 且已验证的能力；
- `pilot`：显式非生产工程试点等级，保留真实验证/批准/设备命令警示；
- `synthetic`：只允许 source-controlled accepted fixture/benchmark 子集。

未知 registration、execution class、能力或 subtype 必须 fail closed，并返回稳定错误码。禁止 MASCARET 与 D-Flow FM 之间的自动转换或 fallback。

### 5. 领域与结果边界

`SimulationCase` 继续只表达工程工况；`DispatchPlan` 继续只表达控制策略；`HydraulicStructureScenario` 继续只表达工况覆盖。Adapter 从冻结的 solver-neutral 模型派生 native 文件，MASCARET 与 D-Flow FM 均写入现有统一 Section/Structure Result 体系。

### 6. 历史兼容

迁移只确定性回填可证明的旧任务：标准 unified input + MASCARET provenance 映射到 `mascaret/production`；controlled preview + D-Flow provenance 映射到 `d-flow-fm/synthetic`。无法证明 identity 的历史 Task 标为 `legacy-unresolved`，可读取历史结果但不可重新执行。不得以 `NULL → mascaret` 作为兼容策略。

## 后果

- MASCARET 仍为当前唯一 production-eligible Standard 1D Engine。
- D-Flow FM 可表达 `pilot`，但本次不执行真实工程 Pilot，且 `production_eligible=false` 保持不变。
- Dataset Version、冻结输入和历史结果均不被重写；新增 migration 提供明确 downgrade。
- Optimization 保持关闭；PLC/SCADA 与真实设备命令保持断开。

## 回滚

如新路由出现问题，优先恢复已验证的 MASCARET 显式 `engine_id=mascaret` 生产路径；不得回退到旧自研 Solver，也不得删除历史结果或 Dataset Version。数据库 downgrade 仅删除本 ADR 新增的 identity 字段和约束，不删除既有 task/result 数据。
