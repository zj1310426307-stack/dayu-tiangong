# HYDRO-CORE-06 最终只读审计

- 审计日期：2026-09-28
- 审计分支：`refactor/hydro-core-06-engine-routing`
- 审计基线：`98957e3b07a9ba8b60656181767a94b2bb3ca5a3`
- PR：#24，`OPEN / CLEAN / MERGEABLE`（审计时）

## 当前事实

1. `SimulationTask` 已冻结 `engine_id + execution_class`，迁移 `20260924_0036` 对可证明的历史任务回填；身份不明任务为只读、不可重跑的 `legacy-unresolved/legacy`。
2. 标准创建、受控闸泵创建、Worker 领取/运行/结果落库均使用冻结身份和 `validate_frozen_task_identity()`；生产路径没有无参 factory 调用，也没有跨 Engine fallback。
3. MASCARET 是唯一 `production_eligible=true` 路径；D-Flow FM 只登记 `pilot`/`synthetic`，`production_eligible=false`。
4. 当前可执行 D-Flow 路径只有从冻结控制合同创建的 `d-flow-fm/synthetic`。`pilot` 是数据与架构合同，尚没有真实工程的 pilot 执行入口。
5. D-Flow 的 source-controlled controlled-runtime 与数值证据只适用于已登记的合成子集，不能表述为官方工程 runtime、真实工程验证或生产资格。
6. `HydraulicStructure.operation_rule_type` 是统一 Domain 中已有的控制语义来源；FIX-01 在此基础上细分 Gate/Pump 的 fixed、schedule 与 rule 能力，不新增第二套控制 Domain。

## 范围与非目标

本审计未发现允许本任务开放 D-Flow production、真实 D-Flow pilot、优化调度、PLC/SCADA 或第二套水力 Domain 的证据。REAL-01 只准备真实资料准入合同；真实导入、率定和独立验证仍未开始。
