# HYDRO-MODEL-02 目标架构与分阶段升级设计

- 文档状态：`DESIGN PROPOSED / NOT IMPLEMENTED`
- 适用阶段：HYDRO-MODEL-02-B 及后续
- 前置审查：`docs/review/HYDRO-MODEL-02-current-solver-audit.md`

## 1. 设计目标

在不破坏 v1/v2/v3 历史任务的前提下，增加一条原生、版本化、可验证的一维
Saint-Venant 计算路径，最终支持：

- 非恒定流和动态波传播；
- 真实库容、动量和质量守恒；
- 表格断面、分区糙率与 `K(h)`；
- 干湿交替、正性保持和受控数值耗散；
- `Q(t)`、`H(t)`、侧向入流及后续边界类型；
- Branch–Reach–Node 河网；
- Gate/Pump 与每个时间 stage 的强耦合；
- 冻结输入、可复现 provenance、质量门和结果级外部对比。

本设计不把“存在数学内核”与“通过生产验收”混为一谈。

## 2. 不变原则

1. 不删除或静默改写现有求解器；
2. v3 的业务字段、serializer 和 legacy 结果语义不变；固定 provenance 输入时 canonical bytes
   保持稳定，每个任务只要求自身 snapshot/hash 相符，不要求包含不同 engine commit 的跨版本
   hash 相等；
3. v4 不经过 `v3 -> v2` 适配器；
4. 新物理能力只由显式 solver ID 启用；
5. 数值状态由一个权威时间积分器管理；
6. Gate/Pump、节点和边界不能在时间积分器外另算一套状态；
7. 未通过当前阶段硬门禁时，状态必须是 failed/not-ready，不能降级假成功；
8. HEC-RAS/MIKE11 只用于结果级验证，不成为内部格式或计算替代品。

## 3. 版本化路由

```text
v1 -> legacy single-river Rusanov reference
v2 -> legacy network continuity-Manning
v3 -> deterministic v3-to-v2 -> legacy network continuity-Manning
v4 -> native finite-volume Saint-Venant engine
```

建议 solver 标识：

- `legacy-single-river-rusanov-v1`；
- `legacy-network-continuity-manning-v1`；
- `saint-venant-fv-hll-v1`（未来 v4 首个原生实现）。

引擎必须按 `schema_version + hydraulic_solver.type + hydraulic_solver.scheme` 注册路由，未知组合
在入队前拒绝。禁止自动把 v4 降为 v3/v2。

## 4. 包结构

不新建 `model/solver2`。建议在现有边界内增量增加：

```text
model/
  solver/
    saint_venant.py              # 现有 v1 reference，保留
    finite_volume/
      state.py                   # HydraulicState/SectionState/NodeState
      mesh.py                    # Cell/Face/Branch/Junction 计算网格
      geometry.py                # I1/K/分区断面运行视图
      flux.py                    # HLL + Rusanov reference
      reconstruction.py          # hydrostatic + MUSCL/limiter
      sources.py                 # 床坡、摩阻、侧向源项
      integrator.py              # SSP-RK2、CFL、事件对齐
      boundary.py                # 特征边界与序列绑定
      junction.py                # 节点非线性闭合
      structures.py              # Gate/Pump stage coupling
      diagnostics.py             # 守恒、收敛、clamp/重试证据
```

包名描述数值职责，版本放在 solver ID 与 provenance 中，不用目录名隐藏版本语义。

## 5. 核心状态类型

### 5.1 `HydraulicState`

全域唯一运行态，至少包含：

- 当前接受时刻；
- 每个 cell 的守恒量 `A,Q`；
- dry/wet mask；
- 节点和结构物运行态；
- 初始/当前总库容；
- 累计外部、侧向和结构物通量；
- 当前 dt、CFL、重试次数和 stage 诊断。

状态与静态网格分离，不允许结果持久化对象反向成为数值状态。

### 5.2 `SectionState`

由 `A` 或 `h` 计算：

- `h, A, T, P, R, I1, K, beta`；
- 各粗糙率分区的 `A_i, P_i, R_i, n_i, K_i`；
- `u=Q/A`、波速、Froude 数；
- geometry/profile/processing hash。

### 5.3 `NodeState`

包含节点水位/总水头、各相连支路有符号流量、外部源汇、局部损失和非线性残差。节点
ID 使用 authoritative hydraulic ID。

## 6. 网格

- 使用 cell-centered finite volume；
- 由已验证的 Hydraulic Reach 和 chainage 生成 Cell/Face；
- 每条结构物必须显式绑定 face 或 node，不从地图位置猜测；
- 物理断面可作为 face/cell 几何控制点，计算 cell 可按数值需要插分；
- 分支起始桩号、方向、长度和 profile hash 必须进入网格 manifest；
- 节点是求解边界，不是事后连接的代数边；
- 网格生成必须确定性，相同快照产生相同 mesh hash。

## 7. 数值格式决策

### 7.1 第一阶段基线

- 空间：一阶 HLL finite-volume；
- 参考通量：保留现有 Rusanov，做交叉回归与 fallback 诊断；
- 床坡：hydrostatic reconstruction / well-balanced 源项；
- 时间：SSP-RK2；
- 摩阻：半隐式或算子分裂，避免显式刚性失稳；
- 全局自适应 CFL；
- 所有 step 精确落在边界折点、控制动作和输出时刻；
- 失败允许有限次数缩步重试，耗尽后必须 failed。

不在第一阶段同时引入 HLLC、高阶 WENO 或复杂隐式网络求解，以免验证面失控。

### 7.2 第二阶段精度

在一阶科学门禁通过后，再增加：

- MUSCL 线性重构；
- minmod 或 MC limiter；
- 光滑案例二阶收敛门；
- 激波/干湿/结构界面自动退回一阶正性通量；
- 通量选择和 limiter 全部写入 provenance。

## 8. 干湿处理

目标算法必须：

- 保证 `A >= 0`；
- dry cell 的 Q 有明确处理；
- 支持重新湿润；
- 质量修正进入诊断，不静默补水；
- dry threshold、re-wet threshold 和容差写入冻结配置；
- 对 lake-at-rest 与 wet/dry dam-break 分别验证。

现有“补到 minimum area 并把 Q 置零”只能作为 legacy reference，不能复用为生产算法。

## 9. 分区糙率

未来原生断面直接消费经过处理和 hash 固定的查算表：

```text
K(h) = sum(A_i(h) * R_i(h)^(2/3) / n_i)
Sf   = Q * |Q| / K(h)^2
```

要求：

- `roughness_zones` 是权威区间；
- LeftBank/MainChannel/RightBank 是可选明确语义，不从 offset 自动猜测；
- 未覆盖区间是否用 default n 必须在 processor policy 中冻结；
- v4 保存 `profile_id/profile_hash/processing_id/processor_version`；
- 求解器不得用另一默认步长重建第二套查算表；
- 查算范围外默认报错，不静默外推。
- A2 reference baseline 明确使用 `beta=1`；复式断面 `beta!=1` 只有在完整 Jacobian、HLL
  波速、Froude/CFL 和边界特征政策冻结后才能启用，否则 `not_ready`。

## 10. 边界系统

`BoundarySeries` 设计为强类型判别联合，逐步支持：

- `upstream_discharge: Q(t)`；
- `downstream_stage: H(t)`；
- `rating_curve: H(Q)`；
- `normal_depth`；
- `closed`；
- `lateral_inflow: q(x,t)`；
- `restart_state`。

每项冻结单位、水平/垂直基准、插值、覆盖域和外推策略；默认外推策略为 `error`。亚临界/
超临界边界按特征方向决定所需变量数，不能始终机械覆盖上游 Q、下游 H。

## 11. JunctionSolver

每个时间 stage 联立求解：

定义 `q_node > 0` 为外部向节点注水，则：

```text
sum(Q_in) - sum(Q_out) + q_node = 0
```

以及与流态相容的共同水头/局部损失/特征关系。要求：

- 支持汇流、分流、回流；
- 不使用 `1/length` fallback；
- 保存迭代次数、残差、条件数/失败原因；
- 超过容差或最大迭代次数必须缩步或失败；
- 有向图用于数据组织，但数值流向可反转；
- 环状网络只有在节点方程门禁通过后开放。

## 12. StructureSolver

复用 MODEL-01 Gate/Pump 纯方程和控制状态，但改变耦合位置：

```text
accepted state at t_n
  -> choose dt aligned to next event
  -> for each RK stage:
       reconstruct adjacent hydraulic states
       solve Gate/Pump flux from current stage heads
       solve junction/structure compatibility
       update conservative flux/source
  -> accept/reject step
  -> emit output and audit events
```

Gate 在内部 face 两侧施加同一个有符号质量通量 `Q_gate`；左右动量通量还必须分别满足
结构反力、局部损失或能头跳跃关系，不能机械复制同一个动量通量。Pump 作为 node-to-node
等量反号源汇或明确 external transfer，并求设备 Q-H 曲线与系统关系的工作点，而不是直接
把设计流量当解。

动作在时间边界生效，不能把 `t_n` 的新命令回填到 `[t_(n-1),t_n]`。能耗和累计体积由
已接受 stage 的一致积分得到。

## 13. `dayu.model-input.v4`

建议以 v3 数据身份为基础，加法增加：

```json
{
  "schema_version": "dayu.model-input.v4",
  "hydraulic_solver": {
    "type": "saint_venant_1d",
    "scheme": "finite_volume_hll",
    "time_integrator": "ssp_rk2",
    "maximum_time_step_seconds": 10.0,
    "cfl": 0.7,
    "dry_depth_m": 0.001,
    "friction_method": "semi_implicit"
  },
  "initial_state": {},
  "profile_selection": [],
  "boundary_series": [],
  "roughness_zones": [],
  "structures": {"gates": [], "pumps": []}
}
```

正式 schema 需使用强类型 DTO；这里仅表示结构方向。v4 canonical 只认嵌套 `structures`，
顶层 Gate/Pump 镜像最多作为 legacy export，不能形成双权威。

### 13.1 v4 readiness

入队前一次性检查：

- Dataset Version 状态及一致性锁；
- topology、direction、Reach/section mapping；
- profile selection 和查算表 hash；
- 初始状态和完整边界覆盖；
- 结构位置、曲线、初始状态与控制计划；
- solver 参数组合是否已实现；
- validation run 与当前内容 hash 是否一致；
- 规范快照 hash 和 mesh hash。

任何缺口返回 `not_ready`，不猜测、不 fallback。

## 14. 结果体系

计划新增强类型 `HydraulicTimeSeries` DTO，而不是立即复制数据库表：

- section/cell time series；
- node time series；
- structure time series；
- event series；
- task result manifest；
- water balance、CFL、iteration、retry、dry/wet、clamp diagnostics。

建议新结果 schema 为 `dayu.hydraulic-result.v3`。每份结果直接携带/关联：

- input snapshot hash；
- mesh hash；
- schema/solver/scheme/integrator；
- engine version/commit；
- validation policy version；
- numeric precision/platform manifest。

现有 section/node/structure/event 时序表优先评估增量扩展，但并非已证明可直接承载 v4。
`JunctionResult.node_id` 当前要求非空 public `RiverNode` FK；纯 hydraulic 节点需要“新增 v4
junction 表”或“新增 canonical ID、旧列 nullable 并重做条件约束/唯一索引”二选一。结构结果
还必须以 `(structure_type, canonical asset identity)` 消除裸整数歧义。只有完成实体/性能评估后
才能决定复用表还是新增专用表/对象存储。

## 15. 后端一致性与身份

- 冻结应锁定 approved/published Dataset，或使用可证明的一致性事务隔离；
- Plan/Action/Rule 在同一冻结边界内锁定，并在 create-run/claim 前复核 Plan frozen hash；
- Worker 执行前按当前 `SHA-256(UTF-8(canonical_json(snapshot)))` 重算 snapshot hash；
- 新 manifest 显式保存 `canonicalization_id/hash_algorithm/hash_domain`；task snapshot 的 hash
  domain 是包含 provenance 的完整冻结快照，不包含数据库行元数据；
- claim 时必须同时满足
  `task.input_schema_version == snapshot.schema_version == snapshot.provenance.input_schema_version`、
  `task.engine_version == snapshot.provenance.engine_version`、
  `task.engine_commit == snapshot.provenance.engine_commit`，并校验 schema/solver allow-list；
- v4 拓扑/断面数值层只使用 hydraulic ID；现有 bridge 仅覆盖 node、segment→Branch 和
  cross-section；
- Gate/Pump 当前仍是 public 资产 ID，A1 必须决定继续以 `(type, public asset id)` 作为
  canonical，还是新增 hydraulic structure identity；不得按整数相等自动桥接；
- legacy public 拓扑/断面 ID 仅在兼容视图/旧 API 中投影；
- 在接受 v4 task 前先发布未知 input schema fail-closed 的 Worker 底座，并隔离 v4 queue；
- 结果质量门按 schema 注册，未知 schema 拒绝持久化；
- engine version 由一个提供器生成，消除当前默认版本漂移；
- API 变化先改 Pydantic/OpenAPI，再重新生成前端客户端，禁止手改 generated client。

## 16. 实施阶段

### A0：审查冻结（本阶段）

- 状态：`DOCUMENT REVIEW COMPLETE / EXPERT FREEZE PENDING`；
- 产物：审查、方程、设计、验证、迁移计划；
- 门禁：当前路径、未实现项和 64 项 legacy regression 分类清楚。

### A1：v4 合同与 shadow 路由

- 只实现 schema、validator、migrator、selector 和 provenance；
- v4 默认禁用，不改变 v3；
- 门禁：固定 provenance 下 v3 canonical bytes 稳定、v3 业务/legacy 结果语义不变、各任务
  snapshot/hash 自洽；未知 schema 在 API/Worker 均 fail closed；v4 缺信息 fail closed。

### A2：单河有限体积

- `I1/K/zones`、HLL、SSP-RK2、半隐式摩阻、正性湿干；
- 门禁：静水、均匀流、湿/干溃坝、网格/时间收敛。

### A3：动态边界与节点

- Q/H/rating/lateral、JunctionSolver、回流；
- 门禁：边界折点、Y 汇/分流、节点残差、失败路径。

### A4：闸泵强耦合

- 每个 stage 结构—水位迭代、系统工作点、事件对齐；
- 门禁：Gate/Pump 动态案例、水量/能量、收敛失败不落 success。

### A5：外部结果级验证

- HEC-RAS 与 MIKE11 分别对比；
- 门禁：显式映射/基准/单位，预登记阈值，报告 RMSE/Bias/NSE/峰值/峰时。

### A6：规模性能

- 100 km、500 断面、20 结构物、24 h、全量落库；
- 只有科学门禁全部通过后才计时。

### A7：shadow、opt-in 与 cutover

- 同一冻结案例并行保存 legacy 与 v4 solver ID；
- 真实率定前只 shadow；
- 默认切换需要水力负责人签字和回退演练。

## 17. 当前 Go/No-Go

- 设计进入 A1 评审：`GO`；
- 直接重写或替换现有求解器：`NO-GO`；
- 直接把 v3 路由到现有单河内核：`NO-GO`；
- 在缺少科学 Benchmark 时开发全网络/结构物：`NO-GO`；
- 当前结果用于生产防洪决策：`NO-GO`。
