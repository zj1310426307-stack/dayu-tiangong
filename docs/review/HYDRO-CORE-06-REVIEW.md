# HYDRO-CORE-06 最终审查

- 审查日期：2026-09-28
- 分支：`refactor/hydro-core-06-engine-routing`
- 基线：`main@8d2d432d77c37ecf4896b776b80d965d38d19800`
- 当前结论：`READY_FOR_MERGE`（路由、迁移、证据语义、能力合同和 REAL-01 资料准入已闭合；真实工程执行不在本阶段范围）

## 已实现

1. `SimulationTask` 新增不可为空的 `engine_id`、`execution_class`，并用迁移 `20260924_0036` 对可证明的历史 MASCARET/D-Flow 任务进行确定性回填；不可证明的历史任务明确标为 `legacy-unresolved/legacy`，不会重跑。
2. 引入统一 `routing.py`：注册表解析、production/pilot/synthetic 门禁、能力检查与冻结 provenance 检查均走同一 fail-closed 规则。
3. 标准 API、同步执行、Worker、受控闸泵创建和生命周期均只从已冻结 `engine_id` 建立引擎。生产路径不存在无参 factory 调用；factory 默认值只保留给旧测试/命令行兼容。
4. MASCARET 仍是唯一 production eligible 引擎；D-Flow FM 的 `pilot` 是已定义的合同而非当前执行入口，只有 `synthetic` 受控路径可运行。Gate/Pump 仅走冻结调度合同，未扩大 PLC/SCADA、优化、第二 Domain 或原生文件业务边界。
5. `HydraulicStructure.operation_rule_type` 现确定性派生 `GATE_FIXED/GATE_SCHEDULE/GATE_RULE` 与 `PUMP_FIXED/PUMP_SCHEDULE/PUMP_RULE`；无证据的 `PUMP_RULE` 保持 fail closed。
5. 新增 `/api/v1/model/engines`；OpenAPI 生成客户端与水动力页面显示引擎目录、生产资格和 Task 的冻结引擎/执行类别。

## 验证结果

| 检查 | 结果 |
|---|---|
| 显式路由、registry、task/result/dispatch 定向回归 | PASS，34 项 |
| MASCARET + D-Flow FM 引擎/benchmark 分组 | PASS，195 passed，13 skipped（受运行时标记/外部条件控制） |
| 后端分组 | PASS，运行至 100%；跳过项均由既有环境标记控制 |
| 根目录 GIS/契约分组 | PASS，35 项 |
| 末段前端/仓库/优化/QGIS 契约分组 | PASS，43 passed，1 skipped |
| Ruff（backend/model/tests/新增迁移） | PASS |
| 前端 TypeScript | PASS |
| 前端生产构建 | PASS，本地 `dist/index.html` 已更新 |
| OpenAPI 漂移检查 | PASS |
| Alembic head | PASS，`20260924_0036` |
| Alembic 全链离线 SQL | PARTIAL：历史 `20260813_0010` 使用 `MockConnection` 不支持的 `exec_driver_sql`，在抵达本迁移前中断；不影响下列在线闭环 |
| 独立 PostGIS upgrade/downgrade/upgrade | PASS：`0035 → 0036 → 0035 → 0036`；新列均为 NOT NULL，执行类别约束存在 |
| MASCARET official / reviewed runtime acceptance | PASS：PR #24 托管 `MASCARET production acceptance` 通过 |
| D-Flow adapter / dispatch contracts | PASS：PR #24 托管 `D-Flow adapter and dispatch contracts` 通过 |
| D-Flow source-controlled controlled-runtime acceptance | PASS（限定合成子集） |
| D-Flow official external runtime acceptance | NOT VERIFIED by HYDRO-CORE-06 |
| D-Flow real engineering validation / production eligibility | NOT STARTED / FALSE |

## 兼容性与风险

- 旧 API 请求中的 `engine` 仍由 schema alias 接受，响应统一输出 `engine_id`。
- 旧 Task 只要 migration 可证明引擎身份即可被保留；不可证明的 Task 是可读不可重跑的安全状态。
- `engine_version` 未被重定义：MASCARET 继续保存既有 build identity，D-Flow 保存其已登记运行时版本；新增 `engine_id` 解决语义歧义。
- 真实工程资料包仍需按 `pilot-data-readiness.md` 准入；D-Flow Pilot Contract 已定义但 Pilot Execution 仍为 deferred/disabled，它们不是本次合成/平台路由验收的替代物。

## 合并前要求

1. 真实工程进入前，按试点资料画像完成资料、基准、观测和专业审核。
2. D-Flow 如申请真实 pilot，必须在 REAL-02 以独立任务实现专用执行入口并通过真实资料准入，不能把当前 `synthetic` 改名为 `pilot`，也不能改变 production eligibility。

## HYDRO-CORE-06-FIX-01 最终矩阵

| Item | Final Status |
|---|---|
| Explicit Engine Routing / Frozen Task Identity / Legacy Migration | PASS |
| MASCARET Production Route | PASS |
| D-Flow Synthetic Route / Pilot Contract | PASS |
| D-Flow Pilot Execution | DEFERRED |
| D-Flow Production | NOT ELIGIBLE |
| Gate Capability Granularity | PASS |
| Pump Capability Contract | PASS / UNVERIFIED EXECUTION for `PUMP_RULE` |
| PostGIS Migration / Runtime Evidence Semantics | PASS |
| REAL-01 Data Contract | PASS |
| Real Engineering Import / Calibration / Independent Validation | NOT STARTED |
| Optimization / PLC-SCADA | DISABLED / DISCONNECTED |
3. 本任务 PR 已审查就绪；仍不直接合并 `main`。
