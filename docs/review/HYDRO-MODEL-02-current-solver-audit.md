# HYDRO-MODEL-02-A 当前求解器审查与整改方案

- 审查日期：2026-08-19
- 审查基线：`4f681b4360e27f8c81042716c1b35bf11d9df364`
- 审查分支：`feature/HYDRO-MODEL-02-A-solver-audit`
- 阶段状态：**AUDIT COMPLETE / 升级路线 GO / 生产 Saint-Venant NO-GO**
- 本阶段边界：只审查、形成方案与门禁草案；未修改任何求解器、API、数据库或前端行为

## 1. 结论先行

当前仓库不是“完全没有 Saint-Venant”，而是存在两条没有统一起来的计算路径：

1. `dayu.model-input.v1` 单河道路径包含一阶 Rusanov 有限体积、hydrostatic
   reconstruction、显式时间推进和真实 CFL 缩步的 Saint-Venant 原型；
2. 正式 `dayu.model-input.v2/v3` 河网路径使用同步时刻的节点连续性、长度倒数分流和
   Manning 回水计算，不推进河道守恒状态，也不求解动量方程。

`dayu.model-input.v3` 在 `model/engine.py:36-44` 被适配成 v2，随后必然进入
`solve_network`；只有非 v2/v3 输入才在 `model/engine.py:45-61` 进入 `solve_river`。
所以当前不存在一条同时具备“完整 Saint-Venant、多分支、分区糙率、闸泵耦合”的正式链。

本审查作出以下决策：

- 保留 v1 单河原型和 v2/v3 continuity-Manning 路径，作为兼容回归与对照；
- 不建立含义模糊的第二套 `model/solver2`；
- 在现有 `model/solver/` 内建设版本化的原生有限体积包；
- v3 继续明确绑定 legacy network solver，绝不静默改变历史结果；
- 新内核只由未来 `dayu.model-input.v4` 显式选择，先 shadow，后 opt-in；
- Benchmark、外部结果级对比、真实率定和规模性能全部通过前，不切换默认求解器。

## 2. 审查口径

能力状态采用四级：

| 状态 | 含义 |
|---|---|
| `IMPLEMENTED` | 当前执行路径真实消费并有回归证据 |
| `PARTIAL` | 有部分算法或数据，但未形成完整科学链 |
| `RESERVED` | 只有接口、预览或诊断占位 |
| `NOT IMPLEMENTED` | 当前路径不存在该能力 |

现有绿色测试只说明对应的软件合同未回归，不自动升级为工程模型验收。

## 3. 实际调用路径

### 3.1 v1 单河路径

```text
dayu.model-input.v1
  -> build_river_meshes
  -> build_boundary_set
  -> solve_river
  -> dayu.hydraulic-result.v1
```

证据：`model/engine.py:45-77`。

### 3.2 v2/v3 正式河网路径

```text
dayu.model-input.v3
  -> adapt_v3_to_v2
  -> build_network_mesh
  -> build_boundary_set
  -> solve_network
  -> dayu.hydraulic-result.v2
```

证据：`model/engine.py:36-44,79-149`。该路径最终诊断为
`synchronous-network-continuity-manning-v1`，并明确输出
`momentum_compatibility: not implemented`（`model/network/solver.py:895-903`）。

## 4. 当前控制方程

### 4.1 v1：单河 Saint-Venant 原型

v1 使用守恒状态 `U=(A,Q)`，物理通量为：

```text
F(U) = (Q, Q²/A + g I1)
```

代码证据为 `model/solver/saint_venant.py:84-90`。连续项和动量项在内部控制体上显式更新，
并加入 Manning 摩阻：

```text
Sf = n² Q |Q| / (A² R^(4/3))
```

证据为 `model/solver/saint_venant.py:315-344`。

判定：

- 连续方程：`IMPLEMENTED`；
- 动量方程：`IMPLEMENTED`，限当前单河原型；
- 非规则断面精确静水压力矩：`PARTIAL`。当前用 `gA²/(2T)`，只对矩形精确，见
  `model/solver/saint_venant.py:64-71`；
- 侧向入流、非棱柱几何源项：`NOT IMPLEMENTED`。

### 4.2 v2/v3：连续性与 Manning 回水

河网路径在每个采样时刻按 DAG 传播外边界流量：汇流相加，分流按 `1/length` 权重，
证据为 `model/network/solver.py:51-117`。节点水位由下游水位和代表断面的 Manning 损失
反推，证据为 `model/network/solver.py:120-170`。

它没有河道蓄量状态，也没有动量、能量或 Riemann 节点兼容条件。上游过程线在同一个
采样时刻被传播到所有下游边，不存在物理传播时滞。

判定：

- 节点代数连续性：`IMPLEMENTED`；
- Saint-Venant 连续方程的时空推进：`NOT IMPLEMENTED`；
- 动量方程：`NOT IMPLEMENTED`；
- 动态波、洪峰削减和蓄量演进：`NOT IMPLEMENTED`。

## 5. 当前空间离散

| 路径 | 当前方法 | 判定 |
|---|---|---|
| v1 | 物理断面上的一阶有限体积；Rusanov 数值通量；hydrostatic reconstruction | `IMPLEMENTED/PARTIAL` |
| v2/v3 | Reach 是有向代数边，不是 PDE 控制体；断面结果由节点水位线性插值 | `NOT IMPLEMENTED`（PDE 空间离散） |

v1 界面通量见 `model/solver/saint_venant.py:105-138`，控制体长度取相邻断面间距平均，
见 `model/solver/saint_venant.py:315-323`。当前没有 MUSCL/TVD 重构或 limiter，数值耗散
由一阶 Rusanov 谱半径决定。

v2/v3 将断面桩号按总边长比例映射到 Reach（`model/network/solver.py:855-864`），隐含
分支起始桩号为零；非零起始桩号可能错配。它不是有限差分、有限体积、有限元、
Preissmann、MacCormack 或 Godunov PDE 离散。

## 6. 当前时间推进和 CFL

### 6.1 v1

v1 使用一阶显式 Euler。每一步按当前状态计算
`|u| + sqrt(gA/T)`，时间步取请求步长、CFL 步长、下一输出时刻和剩余时长的最小值，
证据为 `model/solver/saint_venant.py:278-300`。

判定：

- 显式推进：`IMPLEMENTED`；
- 自适应 CFL 缩步：`IMPLEMENTED`；
- 隐式推进、SSP-RK、多级源项耦合：`NOT IMPLEMENTED`。

### 6.2 v2/v3

网络路径只构造 `0/结束/输出/调度事件`时刻（`model/network/solver.py:706-711`）。
`_network_cfl_step` 虽返回 `synchronized_time_step`，该值没有进入任何状态子步；主循环
直接遍历采样时刻（`model/network/solver.py:712,760-879`）。

所以其 `maximum_cfl` 和 `minimum_time_step` 只是一次性参考诊断，不能证明时间稳定性、
自适应推进或动态波计算。

## 7. 断面、分区糙率和 K(h)

### 7.1 已有能力

`model/geometry/sections.py` 已提供：

- `A(h)`：过水面积；
- `T(h)`：水面宽；
- `P(h)`：湿周；
- `R(h)`：水力半径；
- `h(A)`：面积反算水位。

矩形实现见 `model/geometry/sections.py:52-78`；表格断面实现见
`model/geometry/sections.py:125-238`。

后端 `backend/app/hydraulic/processing.py:98-160` 已按不重叠粗糙率区间计算并持久化
`A/T/P/R/K`，v3 也携带分区与查算表（`backend/app/hydraulic/model_input.py:276-360`）。

### 7.2 实际求解缺口

核心 `SectionGeometry` 没有 `I1(h)`、`K(h)` 或分区状态接口；`Section` 只有一个标量
`roughness`（`model/core/types.py:28-39`）。v3 适配器只取原始点和
`default_manning_n`（`model/adapters/v3.py:741-753`），未消费 `roughness_zones` 或
持久化查算表。

判定：

| 能力 | 数据/预处理 | 当前求解 |
|---|---:|---:|
| `A/P/R/T` | 已有 | 已消费 |
| `K(h)` | 已生成 | 未消费 |
| 任意 offset 粗糙率区 | 已有 | 未消费 |
| LeftBank/MainChannel/RightBank 语义 | 只有自由 `zone_type` 元数据 | 未实现 |
| 任务级 Profile 选择 | 全局 active Profile 在冻结时读取 | 未实现显式选择 |
| 运行中时变断面 | 无 | 未实现 |

“多 Profile”表示不同地形方案，不等于计算过程中断面随时间变化。

## 8. 边界条件

当前支持常值或分段线性 `Q(t)` / `H(t)`，并校验有限数、严格递增时间和覆盖域，见
`model/boundary/conditions.py:71-110`。v2/v3 还要求 source 节点为上游流量、sink 节点为
下游水位，见 `model/network/solver.py:634-682`。

当前不足：

- API 层的 `values` 仍是任意字典，错误可能到 Worker 运行时才被识别；
- v1 使用相邻状态零梯度后覆盖 Q/H，不是特征边界；
- 无超临界变量数判断、rating curve、normal depth、closed boundary、侧向入流、热启动；
- `allow_fallback_boundary` 存在于输入，但模型未消费；
- 常值/series 已运行只证明输入插值，不证明 Saint-Venant 非恒定流。

## 9. 闸泵与调度

### 9.1 可复用能力

- Gate：关闭、干床、堰流、自由/淹没孔流、倒流、最大流量，见
  `model/structure/gate.py:112-186`；
- Gate 控制：开度范围、保持时间、变化率和可用性，见
  `model/structure/gate.py:75-109`；
- Pump：机组数、启停时长、启动次数、扬程、进水深度、效率、功率和能耗，见
  `model/structure/pump.py:114-188`；
- 调度：人工动作、阈值、滞回、冷却、优先级和审计事件。

### 9.2 耦合缺口

- v1 只做结构物容量预览，明确 `structure_coupling: reserved`，见
  `model/engine.py:63-75`；
- v2/v3 先按自然河道 `base_levels` 求结构流量，再路由一次并重算水位，没有迭代使
  结构流量和更新后水头一致，见 `model/network/solver.py:763-786`；
- Pump 未求 Q-H 曲线与系统曲线交点；正静扬程存在时直接用静扬程，流量仍来自设计或
  目标值，见 `model/network/solver.py:467-505`；
- 当前时刻的新动作会拿到上一采样区间的 `elapsed_seconds`，随后用当前结构流量乘整个
  上一区间，阶跃动作存在向前回填的能耗/体积语义，见
  `model/network/solver.py:765-769,830-843`；
- 多个固定 Gate 同时占用同一节点出流时没有联合分配/蓄量方程。审查探针在 20 m³/s
  分流节点配置两个 Gate 后得到节点残差 `0.868084818 m³/s`、全局相对收支残差
  `0.022183551`、状态 `fail`；输入/结果 hash 与完整复现命令见附录 A。持久化门会拒绝，
  但说明当前耦合不能生产使用。

## 10. 多 Reach 和多分支

数据拓扑部分可复用：v3 校验 channel Reach、连续桩号、长度、端点和分支覆盖，并把每个
Reach 投影为一条独立边，见 `model/adapters/v3.py:41-201,712-731`。

求解部分仍是 `PARTIAL`：

- 只支持 DAG，有向环直接拒绝（`model/network/solver.py:29-48`）；
- 分流按长度倒数，不按动态输水能力（`model/network/solver.py:51-54`）；
- 同一 Branch 的 Reach 共用固定代表断面在 `bed+1m` 的 `n/A/R`；
- 节点水位取下游 Manning 候选最大值，无局部损失、能量或动量兼容；
- 无回流、激波穿越节点和节点非线性收敛诊断。

## 11. 质量平衡、稳定性与成功门

v1 的初末库容和边界界面通量进入水量平衡，见
`model/solver/saint_venant.py:221-229,346-377`。但其湿干处理是在面积低于地板时补到
最低面积并把 `Q=0`（`model/solver/saint_venant.py:339-342`），这不是已证明守恒的
正性湿干算法。

v2/v3 把 `initial_storage` 和 `final_storage` 都写成零，见
`model/network/solver.py:880-887`。其 balance pass 只说明外部代数通量记账闭合，不证明
河道蓄量、洪峰演进或湿干守恒。

后端已经有可复用的结果有限性门。当前 `evaluate_water_balance` 在相对残差大于 0.5% 时
标记 `fail`，持久化层同时以 `status=fail` 或相对残差不小于 1% 作后备拒绝门，见
`model/diagnostics/water_balance.py:37-59`、`backend/app/model_engine/service.py:144-180`。
未来必须按 result schema 注册质量门；不能让新的结果版本绕过检查，也不能把 legacy
零库容 balance 当作动态质量验收。

## 12. v3 后端能力矩阵

| 项目 | 当前状态 | HYDRO-MODEL-02 结论 |
|---|---|---|
| constant/series 边界 | 已进入当前求解 | 保留，前移强类型 preflight |
| 闸泵静态包络与调度 | 已冻结、消费、持久化；初始 opening/running_units 为 null/uninitialized，当前 runtime 默认从 0 开始 | v4 必须要求显式工程初态，复用方程和状态机，重做逐 stage 耦合 |
| 分区糙率/K(h) | 已生成并冻结 | 原生 v4 必须直接消费 |
| 多 Profile | 唯一 active，冻结时选择 | 增加任务级 profile selection |
| Solver 参数 | 基础 duration/dt/output/CFL/initial/min depth | 增加强类型 solver/scheme/limiter/wet-dry/iteration |
| 输入 hash/provenance | 已冻结 SHA、engine version/commit | 增加一致性锁、validation hash、Worker 重算 |
| ID bridge | v3 对 node、segment→Branch、cross-section 做严格 bridge；Gate/Pump 仍是 public 资产 ID | v4 先冻结结构物 canonical identity；legacy 仅兼容投影 |
| 结果持久化 | section/node/structure/event 已有；JunctionResult 仍要求非空 public RiverNode FK | M3 前决定增量改约束/索引或新增 v4 junction 表，不能假定现表可直接保存纯 hydraulic 节点 |
| OpenAPI | 任务/单断面部分强类型 | v4 与节点/结构时序需正式 DTO 和生成客户端 |

冻结仍有三个生产缺口：多查询未形成可证明的一致性读快照、计划冻结存在并发编辑竞态、
Worker 执行前未重算 `input_snapshot_hash`。这些属于 v4 preflight/执行完整性整改范围。

## 13. P0 阻断项

1. v3 正式路径没有进入 Saint-Venant 内核；
2. 网络 CFL 不参与时间推进，却以稳定性诊断输出；
3. 网络无河道状态和库容，水量平衡硬编码零库容；
4. 分区糙率和已生成 `K(h)` 在适配时丢失；
5. 没有统一的 Saint-Venant—Junction—Gate/Pump 时间积分；
6. 非规则断面缺少精确 `I1(h)` 与非棱柱几何源项；
7. 结构动作、能量和体积存在采样区间回填语义；
8. 经验分流和回水不能承担动态波生产计算；
9. v4 原生输入、结果和质量门尚不存在；
10. HEC-RAS/MIKE11 结果级对比和真实率定尚未执行。

## 14. P1 整改项

- 特征边界、侧向入流、热启动和超临界边界处理；
- 真正干湿界面、正性保持与重湿算法；
- 二阶空间/时间精度、limiter 和可控数值耗散；
- 半隐式摩阻或稳定源项处理；
- Gate 水头—流量迭代和 Pump 系统工作点；
- 回流/环状网络、节点局部损失及能量兼容；
- 非零起始桩号的 Section→Reach 映射；
- 阈值越界时刻定位，而不是只在输出时刻采样；
- Dataset/Plan 一致性冻结、Worker hash 复核；
- 结果 DTO 直接暴露 task snapshot hash、solver ID、engine commit 和质量门版本。

## 15. 保留、重构与替换边界

| 组件 | 决策 |
|---|---|
| v1 `solve_river` | 保留为参考内核与回归，逐步抽取可复用通量/重构 |
| v2/v3 `solve_network` | 保留为 `legacy-continuity-manning-v1`，禁止改名冒充动态波 |
| A/T/P/R 断面几何 | 保留并扩展 `I1/K/zones` |
| 分区查算处理 | 保留，统一 processor/version/hash 权威入口 |
| BoundarySignal | 保留插值/覆盖规则，扩展强类型边界与特征闭合 |
| Gate/Pump 方程与控制状态 | 保留，接入每个 FV stage 的结构求解器 |
| Reach/ID/hash/provenance | 保留，v4 原生读取 hydraulic ID |
| 结果与任务生命周期 | 保留并增量扩展，不删除旧 API/表 |

## 16. 审查验证证据

本轮以运行时代码树 `4f681b4360e27f8c81042716c1b35bf11d9df364` 为基线；工作区只有
文档改动。仓库根目录主审查实际运行：

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
$env:PYTHONPATH='.;backend'
backend\.venv\Scripts\python.exe -m pytest -c backend/pyproject.toml `
  -p no:cacheprovider `
  tests/test_hydraulic_engine.py tests/test_phase4_hydraulic_gate.py `
  tests/test_phase4_network.py tests/test_model_input_v3_adapter.py `
  tests/test_gate_model.py tests/test_pump_model.py tests/test_dispatch_engine.py `
  tests/test_gate_pump_simulation.py tests/benchmarks/test_phase4_benchmarks.py -ra
# 64 passed in 0.55s
```

覆盖 v1 数值内核、静水与几何门禁、v2/v3 河网、v3 适配、Gate/Pump、调度、24 h
合成案例及现有 Phase 4 benchmarks。另一路只读复核运行的 56 项是重叠子集，亦全通过但
不与 64 相加。

同一运行时代码树在 `backend/` 目录执行全仓测试：

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
.\.venv\Scripts\python.exe -m pytest -c pyproject.toml -p no:cacheprovider -ra
# 308 passed, 71 skipped in 13.89s
```

71 项 skip 是 PostGIS/Timescale/GDAL/QGIS 等外部环境门，属于未执行项，不计为通过。

这些结果统一归类为 **legacy/software regression**，不能写成 64 项 Saint-Venant 科学
Benchmark。其能力边界见 `docs/model/HYDRO-MODEL-02-validation.md`。

## 17. 阶段判定

- 当前求解器审查：**PASS**；
- 升级方向和兼容策略：**GO**；
- v4 设计进入下一评审：**GO，需先冻结数学/门禁参数**；
- 当前 v3 生产 Saint-Venant：**NO-GO**；
- 非恒定、多分支、分区糙率、闸泵强耦合：**NOT IMPLEMENTED**；
- HEC-RAS/MIKE11 对比、真实工程率定、100 km 性能：**NOT EVALUATED**。

下一步不是“一次性重写完整求解器”，而是先实施 v4 合同与 shadow 路由，再按单河 FV、
动态边界/节点、结构物、外部对比和规模性能逐门推进。

## 附录 A：双 Gate 探针复现

在仓库根目录、运行时代码树 `4f681b4360e27f8c81042716c1b35bf11d9df364` 执行：

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
$env:PYTHONPATH='.;backend'
@'
from model import HydraulicEngine
from model.provenance import snapshot_hash
from tests.test_phase4_network import make_y_network

snapshot = make_y_network(bifurcation=True)
snapshot["gates"] = [
    {
        "id": gate_id,
        "river_segment_id": segment_id,
        "upstream_node_id": 3,
        "downstream_node_id": downstream_id,
        "width": 4.0,
        "height": 2.0,
        "maximum_opening": 2.0,
        "minimum_opening": 0.0,
        "opening_rate_limit": 100.0,
        "minimum_hold_seconds": 0.0,
        "crest_elevation": 9.0,
        "discharge_coefficient": 0.62,
        "max_flow": 15.0,
        "status": "online",
        "allow_reverse_flow": False,
    }
    for gate_id, segment_id, downstream_id in ((1, 2, 2), (2, 3, 4))
]
snapshot["dispatch_plan"] = {
    "actions": [
        {
            "id": gate_id,
            "time_seconds": 0.0,
            "structure_type": "gate",
            "structure_id": gate_id,
            "command_type": "gate_opening_m",
            "target_value": 2.0,
            "interpolation": "step",
            "priority": 10,
        }
        for gate_id in (1, 2)
    ],
    "rules": [],
}
print("input", snapshot_hash(snapshot))
result = HydraulicEngine().run(snapshot).to_dict()
node = next(row for row in result["node_series"] if row["node_id"] == 3)
print("result", snapshot_hash(result))
print("node_balance_residual", node["balance_residual"])
print("maximum_normalized_node_residual", result["diagnostics"]["maximum_normalized_node_residual"])
print("relative_balance_residual", result["water_balance"]["relative_balance_residual"])
print("status", result["water_balance"]["status"])
'@ | backend\.venv\Scripts\python.exe -
```

冻结输出：

```text
input 798040a27b24298f962b5c97a066b830d8b0c2272f4bbeb7fcdac77b360d4a57
result 4a66472cccb9ffb2e2c33fb7c7dc016b6558660f659835cecd6c960819c5768b
node_balance_residual 0.8680848180547436
maximum_normalized_node_residual 0.04340424090273718
relative_balance_residual 0.022183550537165156
status fail
```
