# 一维闸泵调度领域契约

## 当前能力边界

调度建模与合成静态预演已经形成软件闭环，但 Gate/Pump 在现行 MASCARET Adapter 能力矩阵中仍为 `UNSUPPORTED`。`POST /api/v1/dispatch/plans/{id}/runs` 必须返回冲突并且不得创建 `SimulationTask`、`DispatchRun`、事件或结果。运行时已安装、计划校验通过或冻结成功，都不能覆盖 Solver 能力门。

合成静态预演只回答“给定人工动作、阈值规则和冻结约束时，哪个命令被选择、限制或拒绝”。它不计算水位、流量、功率、能耗或水量平衡，不连接 PLC/SCADA，也不构成真实工程验证。详细合同见 [合成静态调度预演](./static-schedule-replay.md)。

## 计划版本

计划状态为 `draft → validated → frozen → archived`。动作或规则修改会回到 `draft`；只有 `validated` 可冻结。冻结时生成 `dayu.dispatch-plan.v2` 规范快照和 SHA-256，包含计划、动作、规则、统一 Hydraulic Structure 映射、闸泵静态约束以及当时的 Solver 能力事实。

冻结内容不可就地修改或删除，归档也不解除不可变性；后续迭代必须 clone 为递增版本。旧 v1 快照不能预演，必须 clone、重新校验并冻结为 v2。写操作使用数据库行锁保护状态转换；同名 clone 的版本分配也在锁内完成。冻结操作还锁定全部引用的 Gate/Pump 与统一 Hydraulic Structure，避免校验和快照之间发生资产并发变更。

## 动作与约束

| 命令 | 单位/语义 | 插值 |
|---|---|---|
| `gate_opening_m` | m | step / linear |
| `gate_opening_ratio` | 0–1 比例 | step / linear |
| `pump_enabled` | 0/1 | step |
| `pump_unit_count` | 整数机组数 | step |
| `pump_target_flow` | m³/s 目标值；不等于已计算流量 | step / linear |

同一物理设施在同一时刻只能有一个人工动作，不因命令字段不同而绕过冲突检查。数据库使用 Gate/Pump 两个 partial unique index 处理 nullable 外键，另以 check constraint 固定时刻、设施/命令/外键对应关系和插值域；离散泵命令在数据库层也只能使用 step。

校验要求设施属于计划数据版本、状态为 online、唯一映射到同版本 active 的统一 `hydraulic.structure`，并检查闸门开度/比例、泵站机组数和静态目标流量上限。一个计划不得同时用不同命令模式控制同一物理设施。

迁移 `20260902_0027` 不自动改写旧调度数据。若 0026 数据含离散泵命令 linear 插值，或同设施/同刻的多命令，升级会以 `DISPATCH_0027_PREFLIGHT_*` 和受影响 action IDs 明确停止；维护人员必须先备份、逐计划人工审查并显式修复/克隆，再重试迁移。

## 权威就绪状态

`GET /api/v1/dispatch/plans/{id}/readiness` 分别返回：

- 规划校验是否通过；
- v2 冻结快照及哈希是否完整；
- 合成静态预演是否允许；
- 外部运行时是否可用；
- 当前 engine/version/adapter 的 Gate/Pump 能力事实；
- 闸泵水力能力与真实验证状态；
- blockers、warnings 和最终 `run_allowed`。

前端只展示该接口的结论，不自行推导可运行状态。当前 Gate/Pump 水力运行固定 `run_allowed=false`，静态预演入口与水力运行入口分离。

## 历史运行数据

数据库仍保留旧调度运行、事件和结果模型以兼容历史记录查询，但本阶段不新增调度水力运行。历史 `success` 只说明当时任务生命周期结束，不代表现行 MASCARET Gate/Pump 支持、真实工程验证或生产可用。
