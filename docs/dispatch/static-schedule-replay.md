# 合成静态调度预演

## 用途

`POST /api/v1/dispatch/plans/{id}/schedule-preview` 对 v2 冻结快照做纯调度回放，用于开发期检查时间轴、规则触发、冲突裁决和闸泵静态约束。它不是水力 Solver，也不是真实设备模拟器。

固定证据级别为 `SYNTHETIC_DEVELOPMENT_ONLY`，响应同时声明：

- `hydraulic_execution_supported=false`
- `no_hydraulic_feedback=true`
- `STATIC_DRY_RUN`
- `NO_REAL_EQUIPMENT_COMMAND`

## 输入合同

请求必须显式提供严格递增的时间点：首点为 0、末点等于冻结计划时长，并包含每个人工动作时刻。每个时间点都要包含所有启用动态规则所需的观测键；缺值、重复键、非有限数、超范围时间或超过 2000 点均拒绝。

前端便捷表单可由用户输入起止合成值并在时间轴上生成线性轨迹，但请求仍保存为逐点显式值。该生成方式不表示实测数据插值，更不表示水力响应。

## 输出合同

每个时间点返回：

- 被请求的设施、命令、目标、优先级和来源；
- 约束后的目标值；
- `selected/limited/rejected` 结果及稳定原因；
- 规则 `triggered/recovered` 事件；
- 冲突裁决计数。

响应不包含 H/Q、功率、能耗或水量平衡字段。`plan_snapshot_hash` 固定计划输入，`observation_hash` 固定本次合成轨迹，`result_hash` 固定完整预演输出，便于重复性核对。

## 评估器与合成初态

冻结快照必须绑定当前支持的 `dayu.synthetic-static-schedule.v1` 评估器、确定性冲突裁决和 `hydraulic_feedback=false`。缺少合同、版本未知或任一合同字段不一致时，快照即使 SHA-256 自洽也必须拒绝；算法语义改变必须提升评估器版本。

v1 的初态假设明确为 `ALL_GATES_CLOSED_ALL_PUMPS_STOPPED_MIN_STOP_SATISFIED_T0_SETPOINTS_APPLY_IMMEDIATELY`：所有闸门在 0 s 前关闭，泵停机且已满足最短停机，0 s 设定值作为合成初始设定立即生效。该假设只服务软件回归，不是现场设备状态；因而 0 s 变化率/最短停机结果不得作为工程约束证据。

## 零副作用保证

预演是同步纯计算：只读取冻结快照，不读取当前可编辑动作/规则作为执行事实，不创建或修改 `SimulationTask`、`DispatchRun`、`DispatchEvent`、节点结果或结构结果。失败也不得降级调用历史调度 Worker。

## 与水力运行的关系

静态预演通过不意味着水力运行就绪。水力运行必须另外满足不可变模型、真实运行时、版本化 Solver 能力和工程验证。当前 MASCARET Adapter 的 Gate/Pump 为 `UNSUPPORTED`，因此运行接口继续 fail closed；用户明确跳过真实验证仅缩小本阶段验收范围，不改变能力矩阵。
