# 一维水力调度开发边界

更新日期：2026-09-03
适用合同：`dayu.dispatch-plan.v2` / `dayu.dispatch-plan.v3`
当前状态：静态预演保持原样；Gate、受限 Pump 及 Gate+Pump 合成水力预演已通过 reviewed Runtime；正式调度与生产能力保持 fail closed

## 四类能力不得混同

| 层级 | 用途与证据 | 可输出内容 | 当前实现状态 | 不得宣称 |
|---|---|---|---|---|
| **Static Preview** | 对冻结 `static_v2` 调度策略使用显式合成观测做确定性回放；证据级别为 `SYNTHETIC_DEVELOPMENT_ONLY` | 命令请求值、约束后值、选择/限制/拒绝结果、规则事件和冲突裁决 | `POST /api/v1/dispatch/plans/{plan_id}/schedule-preview` 可用；只读冻结快照，不创建任务或运行记录 | 水位 H、流量 Q、实际闸泵状态、能耗、水量平衡或 Solver 结果 |
| **Synthetic Hydraulic Preview** | 面向 D-Flow FM + DIMR + FBC/D-RTC 的合成数值开发轨道；证据级别为 `SYNTHETIC_NUMERICAL_ONLY` | 固定外部 Runtime 实际计算的 H/Q、Gate opening/Q、Pump requested/resolved/native Capacity 与 actual Q、控制轨迹和质量平衡 | Gate schedule/单水位阈值、Pump Capacity schedule、联合人工 schedule 及 Gate threshold + 独立 Pump schedule 可创建异步任务 | 真实工程验证、生产可用、现场控制或实际设备命令 |
| **Real Engineering Validation** | 基于可追溯实际河网、闸泵、边界与实测资料，完成 QA、率定、独立验证和交叉验证 | 经审查的率定/验证指标、偏差、不确定性、守恒证据和完整运行 provenance | 本阶段未执行；当前 v3 响应明确固定 `real_engineering_validation=false` | “类型化文件生成通过”或“合成 benchmark 通过”即真实工程验证 |
| **Real Equipment Control** | 向 PLC/SCADA/现场设备下发命令的独立安全系统，需要设备授权、联锁、人工接管、回执和审计 | 只能是经授权控制系统中已确认、可追溯的命令与回执 | 不在本仓库当前调度预演范围；`real_equipment_command=false` 且 `plc_scada_connected=false` | 任何预演、数值模拟或工程验证自动授予设备控制权 |

这四类能力是逐级增加的证据与授权边界，不是同一个“运行”开关。用户允许跳过真实验证只改变当前交付范围，不会把合成证据升格，也不会打开设备控制或生产运行。

## Static v2 与 Hydraulic v3 生命周期

```text
frozen static_v2 或 frozen hydraulic_v3
        |
        | POST .../hydraulic-clone
        v
hydraulic_v3 draft -- POST .../validate --> hydraulic_v3 validated
        ^                                      |
        | 修改动作/规则会回到 draft                | POST .../hydraulic-compile-check
                                               v
                                     只读编译报告
                                               |
                                               | ready_to_freeze=true
                                               | POST .../hydraulic-freeze
                                               v
                                     frozen hydraulic_v3
                                               |
                                               | POST .../hydraulic-preview
                                               v
                               异步 queued/running/success
```

`hydraulic-clone` 是唯一支持的 v3 迁移入口：

- 源计划必须已冻结，且是完整的 v2 或 v3 快照；
- 服务会核对源快照 hash，新计划以递增版本、`draft`、`snapshot_target=hydraulic_v3` 和显式 `cloned_from_plan_id` 创建；
- 动作与规则会被复制，但新计划必须重新校验；
- 不允许原地把 `static_v2` 改成 v3；普通 `POST .../freeze` 只冻结 v2，v3 必须走专用 `hydraulic-freeze` 路由。

## Compile Check

`POST /api/v1/dispatch/plans/{plan_id}/hydraulic-compile-check` 只接受已校验的显式 v3 clone。请求使用严格白名单合同，包括每个执行器的显式初始状态、观测绑定、观测采样间隔、运行模式、超时与固定为 `true` 的 `synthetic_fixture`。重复设施初态、重复观测身份或额外字段均被拒绝。

报告把下列状态分开，不允许前端自行合并推断：

- 计划、水力模型、能力门、闸泵映射、Manual control、D-RTC 和 Observation contract 各自的布尔状态及精确 issue；
- `ready_to_freeze` 只表示不可变静态/编译语义齐全，**不把 Runtime availability 作为冻结前提**；
- `runtime_available` 单独表示所选外部运行边界及完整 provenance 通过；
- `controlled_runtime_accepted` 单独表示经验收的 D-RTC/FBC 耦合运行时，不能由工件存在、静态编译或 Runtime readiness 推导；
- `ready_to_run = ready_to_freeze && runtime_available && controlled_runtime_accepted`，但它仍不是生产授权；
- 支持单 Gate manual schedule 或单 scalar water-level threshold Rule、单 Pump aggregate Capacity schedule、独立 Gate+Pump manual schedules，以及 Gate threshold + 独立 Pump schedule；多规则 priority、同一执行器 manual+rule、hysteresis/hold/cooldown、Pump threshold、`pump_enabled` 与 `pump_unit_count` 精确阻断；
- D-Flow FM 当前 `UNSTEADY_1D`、`BRANCHED_NETWORK`、`GATE`、`PUMP`、`ORIFICE`、`DYNAMIC_CONTROL` 是 `EXPERIMENTAL`，`D_RTC` 是 `UNVERIFIED`，没有任何 `VERIFIED_*` 能力。`EXPERIMENTAL` 只可按明确的合成开发策略进入编译路径，不可进入生产。

该路由是只读检查：不修改计划，不创建 `SimulationTask`、`DispatchRun`、Workspace 或 native 运行文件。报告使用自身 `report_hash` 固定当次诊断内容。

Observation contract 不只检查字段类型：每个 source 必须存在于 Adapter 实际输出的观测源 inventory 中，Gate 上/下游水头对必须在同一 Branch 上按方向夹住设施，Pump 取水观测必须与设施方向一致。请求 `timeout_seconds` 也必须与当前运行配置精确一致，不得使用前端或冻结快照的超时值覆盖 Worker 边界。

## Hydraulic v3 Freeze

`POST /api/v1/dispatch/plans/{plan_id}/hydraulic-freeze` 不信任之前的前端报告。它先按全局写入顺序锁定 `DatasetVersion`，再锁定计划和所有引用资产，防止 READ COMMITTED 下的河网/断面/边界/工况并发更改生成混合快照。锁内使用同一请求重新编译，只在 `ready_to_freeze=true` 时持久化 `dayu.dispatch-plan.v3` 快照。

冻结内容包含完整 canonical `Hydraulic1DModel`、D-Flow 当次 capability 事实、闸泵映射、Manual/D-RTC 编译合同、观测合同、执行设置及内外层 hash。完整性检查会独立重算 Manual 和 D-RTC 报告的 `artifact_hash`，再校验 control contract 与外层快照 hash，因此重算外层 hash 不能掩盖内层报告篡改。每个执行器只允许顶层 `initial_actuator_state` 作为唯一显式初始状态权威源，不从 v2 资产约束或 native 文件猜测/复制第二份初始状态。响应固定声明 `SYNTHETIC_NUMERICAL_ONLY`、`real_engineering_validation=false`、`real_equipment_command=false` 和 `plc_scada_connected=false`。

Runtime unavailable 可以与静态合同已冻结同时存在：这是可审计的状态分离，不代表已能运行。

## Hydraulic Preview 异步 API

`POST /api/v1/dispatch/plans/{plan_id}/hydraulic-preview` 是隔离的开发端点，不是正式 `/runs` 的别名。当前服务依次检查：

1. 计划是已冻结的 `hydraulic_v3`；
2. v3 类型包装、证据声明与内外 hash 完整；
3. 本次请求与冻结的初态、Observation contract、Runtime mode 和 timeout 逐项相同，且 timeout 与 Worker 当前 Runtime 配置精确匹配；
4. 外部 Runtime 可用且 provenance 完整。

运行时缺失时仍返回 HTTP 409 `DFLOW_RUNTIME_BLOCKED`；registry 漂移时返回 `DRTC_COMPILER_BLOCKED`。门禁通过后创建不可变 `controlled_hydraulic_preview` 任务与 `hydraulic_preview` 运行记录，交给现有 Celery `hydraulic-1d` 队列。Worker 用执行 lease/CAS 处理 heartbeat、取消、超时、重投和孤儿恢复；成功时原子持久化 H/Q、Gate requested/resolved/applied、Pump requested/resolved/native Capacity/actual Q/intake/outlet/head、控制事件、四组件 provenance 与质量平衡。

前端轮询任务状态并链接到运行详情；规则兼容逐条展示，能力表直接展示后端返回的 supported/unsupported subset，且固定显示 `Multi-rule priority: Not verified`。Pump Capacity target 与 actual Q 分图展示，结果 KPI 以 actual Q 积分转输水量，不计算无证据的 kWh。任何失败都不得降级到 MASCARET、静态 replay 或 Python 自制水力方程。

## 正式 Dispatch `/runs` 继续关闭

`POST /api/v1/dispatch/plans/{plan_id}/runs` 仍是历史 MASCARET 调度创建入口，当前对任何存在的计划均返回 HTTP 409，错误详情以 `UNSUPPORTED_BY_MASCARET_ADAPTER` 开头。D-Flow FM 登记、v3 冻结、Runtime 安装或用户允许跳过真实验证都不会打开该路由。

该接口不创建 `SimulationTask`、`DispatchRun`、`DispatchEvent` 或任何新结果。`GET /api/v1/dispatch/runs...` 系列路由仅用于查询兼容性历史记录；历史记录存在不表示现行运行已授权。这一关闭边界特指 Dispatch plan 的 `/runs`；独立的水力生产工作流仍受其自身 QA/率定/验证/审批门禁约束，不授予调度设备控制权。

前端按同一语义展示两个预演入口，并始终禁用“生产运行未开放”按钮：Static Preview 不显示任何伪造 H/Q，Hydraulic Preview 则展示开发证据警示、编译门和精确 blocker。

## 解锁条件的分层证据

Synthetic Hydraulic Preview 要获得成功执行分支，至少需要：固定且完整的 D-Flow FM/DIMR/FBC/HYDROLIB-core provenance；真实生成并校验的耦合文件；官方基础 case 与 D-RTC coupling case；Dayu 闸泵、规则、约束、取消/超时/并发隔离 benchmark；以及 H/Q/control trace/守恒结果合同。

Real Engineering Validation 还必须使用独立、有权限、可追溯的真实资料执行模型 QA、率定和验证；资料清单见 [D-Flow FM 真实工程资料要求](../hydraulics/dflow-fm-real-data-requirements.md)。Real Equipment Control 则需要另立项完成现场安全架构、设备控制授权和法规/运行规程审查，不得由前两层自动推导。

相关文档：

- [一维闸泵调度领域契约](./dispatch_contract.md)
- [合成静态调度预演](./static-schedule-replay.md)
- [D-RTC 编译器与闭环控制边界](./drtc-compiler.md)
- [D-Flow FM Adapter 与外部运行时边界](../hydraulics/dflow-fm-adapter.md)
- [水力生产工作流](../hydraulics/production-workflow.md)
