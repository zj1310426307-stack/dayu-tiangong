# Phase 5 多目标调度优化评审

## 1. 完成情况

已实现 PSO 候选生成、Phase 4 水动力复用、三目标评分、硬约束、Pareto 分层、人工推荐、三张数据库表、异步生命周期、OpenAPI 客户端与三个优化页面。CGCS2000 / EPSG:4490 继续写入冻结快照。

## 2. 优化算法检查

`optimization/algorithms/particle_swarm.py` 实现固定种子 PSO，支持粒子数、迭代数、惯性、认知/社会系数、容差和连续稳定代数。算法测试在二维 sphere 函数上达到 `< 0.01`，每个粒子评价均保留代数与候选索引。

## 3. 目标函数检查

`dayu.objectives.v1` 对防洪、能耗、操作三个目标分别归一化，再按 W1/W2/W3 归一化权重求和。警戒/保证水位、泵运行/能耗/启动、闸动作/开度变化和泵停机均进入指标。

## 4. 约束检查

仿真前检查闸门开度、开度速率、动作数、泵最小运行时间和启动次数；仿真后检查最大水位、最大流量和最大泵功率。结果统一为 `{valid, reasons[]}`，无效候选保留但不能成为推荐。

## 5. 水动力调用检查

优化层没有修改 `HydraulicEngine`。每个有效候选冻结 `dayu.model-input.v2`，新建独立 `simulation_task` 并调用 `run_hydraulic_task.run`，结果落入 Phase 4 的 `simulation_result` / `structure_result`。端到端实测候选 #5/#6 分别关联仿真任务 #119/#120。

## 6. Pareto 检查

三目标按最小化执行确定性非支配分层；第一层有效候选进入 Pareto API 和二维散点图，颜色表达操作成本。加权最低的第一层方案才标记为推荐。

## 7. 前端检查

完成 `/optimization`、`/optimization/tasks`、`/optimization/tasks/:id`。内置浏览器验证了配置表单、模型版本/方案、异步进度、候选链路、推荐说明、Pareto 图与方案对比均可见；页面无真实设备执行按钮。

## 8. 性能测试

- 开启真实 PostGIS 集成后的全量自动测试：`91 passed`。
- 1000 个三目标向量 Pareto 分层测试阈值：`< 2.5s`，通过。
- 本地 eager 端到端：2 粒子 × 1 代、每候选 60 秒仿真，优化 Worker 约 `0.53s` 完成（开发机、DEMO 河网，不代表生产容量）。
- 最终前端生产构建约 `82s`，优化业务块约 `15.59kB`（gzip `5.53kB`，包含四类候选时序对比）。

## 9. 已知限制

- 当前仅实现 PSO，不包含遗传算法、强化学习或 AI 自主调度。
- 水动力仍继承 Phase 4 简化河网动量耦合与 DEMO 数据限制。
- PSO 候选按当前单 Worker 串行调用水动力，尚未实现跨 Worker 候选并行与配额调度。
- Ant Design、ECharts、Cesium 供应商块仍超过 Vite 500kB 建议值；Cesium 已路由懒加载，后续可继续拆分 ECharts/Ant Design。
- `npm audit` 本次因 registry audit endpoint 不可用未返回新结果；既有 moderate 告警需继续跟踪。

## 10. Phase 6 AI 助手建议

保留 `GET /api/v1/optimization/tasks/{id}/explain` 的稳定契约。Phase 6 可在严格检索与权限边界内生成“为什么推荐、风险点、方案差异”说明，但必须引用候选指标、快照哈希和约束理由；AI 输出不得改写 Pareto/评分，不得获得真实设备执行权限。当前实现明确返回 `deterministic_template`，不冒充 AI。
