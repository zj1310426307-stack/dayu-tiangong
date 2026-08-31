# HYDRO-MODEL-01 现有闸泵能力审查

> **历史基线 / 自研 Solver 路线已废止（2026-08-31）：** 文中“当前”只指 2026-08-19 审查时点；闸泵数据与公式可作历史参考，但旧河网求解器与调度执行链已由 [HYDRO-1D-RESET-01](../migration/HYDRO-1D-RESET-01.md) 废止。当前 MASCARET Adapter 对未验证的 Gate/Pump 映射 fail closed。

- 项目：大禹·天工（dayu-tiangong）
- 审查日期：2026-08-19
- 审查范围：现有 Gate/Pump、模型输入、数值内核、调度、任务持久化和前端
- 本阶段边界：形成准动态闸泵联合调度最小闭环，不声称完整 Saint-Venant 或生产能力
- 文档定位：本文件保留实施前基线；实施结果与验证证据见 `HYDRO-MODEL-01-development-report.md`

## 1. 审查结论

仓库已经具备一套受 Dataset Version 管理的 Gate/Pump 工程对象，也已经具备闸门过流、泵站曲线与能耗、白名单控制规则、联合时间循环、冻结任务、结构物结果和调度事件持久化能力。因此，本阶段不新增第二套闸泵表，也不重写现有求解器。

审查发现的主要断点不在“有没有闸泵模型”，而在以下集成边界：

1. `dayu.model-input.v3` 仍以顶层 `gates`、`pumps` 承载结构物，没有任务书要求的 `structures` 权威包络；
2. 调度运行和水动力任务页面仍固定创建 v2 输入，未进入 HYDRO-DATA-01/02 建立的 v3 河网、Reach、Profile 和 ID 兼容映射链；
3. 受控快照是在冻结完成后再手工附加计划，v3 下会绕过计划观测对象的 legacy ID 到 hydraulic ID 重写；
4. 已有前端可查看结构物明细和事件，但缺少 24 小时闸门开度、泵流量与累计能耗曲线；
5. 缺少任务书指定名称的四组合同测试和独立 5 km/20 断面/24 h 示例；
6. 当前河网路径是“同步连续性 + Manning 回水”的准动态求解，不含节点动量兼容和完整 Saint-Venant 动态波，必须持续披露。

## 2. 现有 Gate 对象

权威对象为 `backend/app/gis/models.py::Gate`，静态资产与运行状态分离。现有字段已经覆盖本阶段所需绝大多数参数：

| 语义 | 现有字段 | 说明 |
|---|---|---|
| 版本与身份 | `id`、`dataset_version_id`、`gate_code`、`name` | 受 Dataset Version 管理，版本内编码唯一 |
| 类型与位置 | `gate_type`、`river_id`、`river_segment_id`、`station`、`geometry` | `station` 即沿程桩号；空间几何为 EPSG:4490 Point |
| 拓扑 | `upstream_node_id`、`downstream_node_id` | 连接既有河网节点 |
| 几何 | `width`、`height`、`bottom_elevation`、`crest_elevation` | 支持孔流/堰流计算 |
| 能力 | `max_flow`、`discharge_coefficient`、`allow_reverse_flow` | 最大流量、流量系数和倒流策略 |
| 动作约束 | `minimum_opening`、`maximum_opening`、`opening_rate_limit`、`minimum_hold_seconds` | 用于动态开度约束 |
| 管理状态 | `control_mode`、`status`、`opening_direction` | 静态资产属性；实际开度不写回资产表 |

实际开度和上次变化时刻由 `model/structure/gate.py::GateControlState` 在一次模拟内部维护，逐时结果写入 `StructureResult`，没有把运行态混入静态 Gate。

## 3. 现有 Pump 对象

权威对象为 `backend/app/gis/models.py::Pump`：

| 语义 | 现有字段 | 说明 |
|---|---|---|
| 版本与身份 | `id`、`dataset_version_id`、`pump_code`、`name` | 受 Dataset Version 管理，版本内编码唯一 |
| 位置与拓扑 | `river_id`、`geometry`、`intake_node_id`、`outlet_node_id`、`transfer_type` | 支持内部转输、外部入流和外部出流 |
| 额定参数 | `design_flow`、`head`、`power`、`unit_count` | 描述额定能力和机组数量 |
| 曲线 | `head_curve`、`efficiency_curve` | 分段线性插值，禁止静默外推 |
| 运行约束 | `minimum_running_units`、`maximum_running_units`、`minimum_run_seconds`、`minimum_stop_seconds`、`maximum_starts_per_run` | 支持机组数、最短启停和启动次数约束 |
| 水力保护 | `minimum_operating_head`、`maximum_operating_head`、`reverse_flow_protection` | 支持扬程和倒流保护 |
| 管理状态 | `control_mode`、`status` | 静态资产属性 |

Pump 没有独立的数据库桩号字段。其 v3 结构物包络需要保留 `chainage: null` 并在 provenance 中说明“节点转输对象、未确认沿程桩号”，不得凭点位投影猜测工程桩号。实际机组数、累计运行时间、启停次数和能耗由 `PumpControlState` 在模拟内部维护。

## 4. 当前模型输入

`backend/app/dataset/service.py::build_model_input_v2` 已输出河流、节点、河段、断面、边界、参数、Gate、Pump、controls 和可选 dispatch plan。`backend/app/hydraulic/model_input.py::build_model_input_v3` 在此基础上读取 authoritative hydraulic schema，增加 Network、Branch、Reach、active Profile、糙率分区、查算表、工程 CRS 和兼容 ID 映射。

审查前的 v3 结构物仍沿用顶层：

```json
{
  "gates": [],
  "pumps": [],
  "controls": {},
  "dispatch_plan": null
}
```

本阶段采用如下兼容策略：`structures.gates/pumps` 是 v3 结构化表达，原顶层 `gates/pumps` 保留为旧求解器兼容镜像；两者必须来自同一个冻结快照并保持一致，不能成为两份可独立编辑的权威状态。`controls.rules` 只镜像同一冻结 dispatch plan 中的规则，求解器仍消费同一份不可变计划。

## 5. 当前求解器是否消费闸泵

结论：**已经消费，但属于准动态最小模型。**

- `model/structure/gate.py`：关闭、自由孔流、淹没孔流、堰流、干床、最大流量和倒流策略；开度受上下限、变化率、最小保持时长和资产可用性约束。
- `model/structure/pump.py`：Q-H/Q-η 曲线、机组数、启停、扬程、进水深度、流量、功率和能耗。
- `model/network/solver.py`：统一时间轴读取状态、评估控制策略、计算闸门边通量和泵站节点源汇、更新河网流量/水位并产生 `structure_series` 与 `dispatch_events`。
- `model/adapters/v3.py`：将验证后的 HydraulicReach 链无损投影成求解器河段；不能精确表达的多 Reach 闸门定位会 fail closed。

闸门不是边界流量替代脚本：它在目标内部河段上形成受设备公式和上游可用流量共同约束的通量。泵站不是结果后处理：它作为节点源汇参与质量路由，功率和能耗随实际流量、扬程、效率和时间步计算。

## 6. 当前调度模块

`backend/app/dispatch` 已支持：

- 计划草稿、校验、冻结哈希、克隆和归档；
- 闸门开度/比例、泵启停/机组数/目标流量人工动作；
- 节点水位、断面水位、闸门水头差、泵进口水位和时间白名单观测；
- `>`、`>=`、`<`、`<=` 白名单操作符；
- 滞回、最小保持、冷却、优先级和冲突计数；
- baseline/controlled 两个冻结任务、异步执行、对比指标；
- `StructureResult`、`DispatchEvent`、`JunctionResult` 和断面结果持久化。

规则模板是结构化数据，不执行任意脚本。请求值、实际值、约束、结果和原因均可审计。

## 7. 当前前端

- `frontend/src/pages/data-center/` 已通过生成的 OpenAPI 客户端维护版本化 Gate/Pump 静态资产；
- `frontend/src/pages/dispatch/DispatchPages.tsx` 已提供计划、动作、规则、冻结、运行和详情页面；
- 运行详情已显示基准/受控水位、结构物逐时结果、调度事件、节点收支和水量平衡；
- 静态资产状态和模拟运行状态已分开，没有把某次计算的开度或启停写回 Gate/Pump。

审查前缺少闸开度、闸流量、泵流量和累计能耗的联合趋势图，以及明确的 0/6/12/24 h 里程碑。

## 8. 本阶段实施决策

1. 不新增数据库表，不新增 Alembic 迁移；
2. 在 v3 冻结快照中增加 `structures` 和 `controls.rules`，保留兼容镜像；
3. 让调度 baseline/controlled 都直接冻结 v3，受控计划在冻结函数内部注入，确保 ID 映射、来源和哈希完整；
4. 复用现有 Gate/Pump 领域公式、控制策略、河网循环和结果持久化；
5. 新增独立 24 h 合成示例与任务书指定测试，不把它表述为真实工程率定；
6. 补充前端结构物趋势图和里程碑，继续只调用生成的 API 客户端；
7. 将完整 Saint-Venant、动态波、复杂结构耦合、真实曲线率定和 HEC-RAS/MIKE11 对比留给 HYDRO-MODEL-02。

## 9. 科学适用边界

当前联合路径的求解器标识为 `synchronous-network-continuity-manning-v1`。它执行同步时刻的节点连续性、共同水位和 Manning 回水，并通过闸泵内部通量/源汇形成准动态调度闭环；诊断明确记录 `momentum_compatibility: not implemented`。

因此，本阶段成功仅说明：软件可以在冻结、版本化的合成输入上确定性运行闸泵控制、输出有限结果、持久化事件并通过质量平衡门禁。它不表示已经完成完整 Saint-Venant 非恒定流、工程率定、MIKE11/HEC-RAS 同等级能力或真实生产验收。
