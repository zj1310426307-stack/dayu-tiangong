# HYDRO-MODEL-02-B/B2 开发报告

日期：2026-08-20
阶段状态：软件 MVP 可运行；科学/生产验收 `NO-GO`
实现提交：`48abdab`（B2 坡床、特征边界与受限非棱柱科学门）

## 1. 交付结果

本阶段在保留 v1/v2/v3 的前提下，增加了一条不经 v3/v2 投影的 `dayu.model-input.v4-lite` 直连路由，完成以下软件闭环：

```text
strict v4-lite JSON
        ↓
existing Profile offset/elevation
        ↓
cell-centred finite-volume mesh + U=(A,Q)
        ↓
HLL + hydrostatic reconstruction + SSP-RK2 + Manning
        ↓
Q(t)/H(t) + fixed/one-shot-threshold Gate/Pump
        ↓
dayu.hydraulic-result.mvp
```

## 2. 数值方法

### 2.1 状态与网格

- `HydraulicState` 只保存时间、A、Q、派生水深/流速/干湿标识、结构物状态和诊断，不持有 Mesh。
- `FiniteVolumeMesh` 保存 cell 身份、dx、断面几何和 Manning n。
- v4-lite 将每个物理断面建为一个 cell，内部 face 位于相邻 Chainage 中点，端点 cell 覆盖 Branch 起止范围。

### 2.2 断面几何

保留已有 A(H)、T(H)、P(H)、R(H)、H(A)，并在同一 `SectionGeometry` 协议中新增：

```text
I1(H) = 1/2 ∫ max(H-z(x), 0)^2 dx
```

- 矩形断面使用 `b h² / 2`。
- 非规则断面直接对冻结的 offset/elevation 折线分段解析积分，不依赖查算表垂向步长。

### 2.3 通量与时间推进

- 守恒量：`U=(A,Q)`。
- 物理通量：`F=(Q, Q²/A + g I1)`，MVP 锁定动量修正系数 `β=1`。
- 波速：`c=sqrt(g A/T)`，适用于非矩形断面。
- 默认 HLL，Rusanov 保留为 reference。
- hydrostatic reconstruction 保证已验证子集的 lake-at-rest。
- SSP-RK2 每个 stage 重新评价边界、通量、摩阻和结构物。
- CFL 自动缩步，步长精确落在边界折点、输出时刻和结束时刻。
- Manning 摩阻采用每 SSP stage 的半隐式处理，禁止流量因摩阻翻转符号。
- 显式 `uniform-manning-reference` 模式只接受经解析验证的均匀棱柱、线性坡、常 Q/H/n 亚临界平衡，并用同一离散算子扣除参考残差；默认仍为 `standard`。
- `subcritical-characteristic-v1` 通过一般断面的 `Phi(A)=∫c/A dA` 保留出域 Riemann invariant；矩形使用解析式，Tabulated 使用固定 GL8 积分和正根求解。干、临界/超临界、反向或无根状态关闭失败。
- `hydraulic-function-linear-face-v1` 在相邻断面的 A/T/P/I1 间建立线性 face path，并用匹配的 cell 压力源保持受限非棱柱 lake-at-rest。公开入口只允许全湿、零流、共同绝对水位、Qup=0、Hdown 匹配且无结构的静水案例。

## 3. 边界与结构物

- 上游 Q(t) 和下游 H(t) 采用域内线性插值，必须覆盖 `[0,duration]`，超域直接失败；v2 可显式选择亚临界特征闭合。
- 当前边界空间支撑冻结为 `nearest-section-cell-face-v1`：边界通量使用首/末 cell 的断面几何，不把 `target_node_id` 误写成端节点处已有实测断面。Case 002 末断面距 Branch 末端 25 m，对应连续坡床端点水位差约 0.019841 m，因此当前金样只验证末 cell face 的离散参考。
- Gate 在每个 RK stage 使用当前上下游水位重算定开度质量通量。它尚未闭合结构力/局损动量，因此强制输出 `structure_momentum_closure_mass_only_mvp`。
- Pump 是单 cell 的 ON/OFF 定流量外排源汇，移除对应质量与局部平流动量，外排体积进入全局水量账。

Case 004/005 保留固定开/关对照，并增加显式 `one-shot-stage-above` 合同。Gate/Pump 使用同一接受态水位独立判定，在成功步末原子锁存一次；两个 RK stage 和失败重试不推进控制状态。事件时刻是接受步离散时刻，不宣称连续 crossing 已精确定位。

## 4. 输入与结果合同

### 4.1 `dayu.model-input.v4-lite`

合同使用 Pydantic 强类型、`extra=forbid`和非有限数门禁，并严格校验：

- Dataset/CRS/Branch/Section/Profile 身份；
- Chainage 顺序、显式初态和 Profile 水位范围；
- 单槽、单调岸坡；v1 仅允许绝对相同 Profile，v2 只允许封闭策略元组；
- 坡床策略要求相同相对 Profile、严格线性下降床面、cell-center metric 和解析 Manning 平衡；
- 非棱柱静水策略要求共同绝对 H、Q=0、完整 Q/H 静水边界、无结构，并以共同水位下实际 A/T/P/I1 而不是点数判定断面确有差异；
- 边界类型、两端节点、唯一身份和时域覆盖；
- Gate 相邻 face 绑定和 Pump 明确 external outlet；
- 固定与一次性阈值控制使用互斥、可辨别合同；阈值必须位于被监测 Profile 范围内；
- 唯一 solver tuple，以及显式 geometry/source/equilibrium/boundary/spatial-support 版本。

引擎入口先把 JSON 规范化成独立快照并预计算 hash，之后的解析、求解和结果均使用该副本，阻断运行中调用方修改导致的 TOCTOU 证据错配。

### 4.2 `dayu.hydraulic-result.mvp`

MVP 结果是独立 DTO，不继承 `EngineResult`，包含：

- 逐 Section 的 time/water_level/flow/velocity；
- Gate opening/flow 和 Pump status/flow；
- 可选的 typed Gate/Pump 接受态控制事件；固定输入仍保持原 JSON 输出形状；
- 动态初末库容、边界体积、Pump 外排体积及归一化误差；
- maximum CFL、minimum dt、retry/step count 和强制诊断；
- 输入快照 hash 和实际消费几何的 mesh hash。

mesh hash 包含实际 Profile points、dx、Manning n、几何处理策略和声明的 Profile hash，不仅信任调用方标签。v2 另有 `solver_policy_hash`，覆盖边界闭合、边界空间支撑、平衡、摩阻、积分、root 和时间步策略；两者权责不混合。hash 是关联证据，不是签名，独立验真必须与冻结输入成对重算。

## 5. 主要修改文件

- 断面：`model/geometry/sections.py`
- v4-lite 合同：`model/api/v4_lite.py`
- v4-lite 网格/输入/结果适配：`model/adapters/v4_lite.py`
- 独立结果：`model/result/mvp.py`
- 引擎路由：`model/engine.py`
- 数值核心：`model/solver/finite_volume/`
- 测试：`tests/model02/`
- 可运行示例：`examples/hydraulic/saint-venant-mvp/`

## 6. 完成矩阵

| 任务书项 | 状态 | 证据/边界 |
|---|---|---|
| v1/v2/v3 保留 | PASS | 旧测试全部继续通过，v4 独立路由 |
| finite_volume/HLL/Rusanov | PASS | 组件和合成测试 |
| SSP-RK2/CFL/重试 | PASS | 每步 2 stage，诊断入结果 |
| 非规则断面 I1 | PASS | 分段解析积分；棱柱子集静水通过 |
| 单河非恒定流 | PASS (MVP) | 洪峰传播行为通过，无解析精度声明 |
| Q(t)/H(t) | PASS (限定) | 插值、折点对齐、禁止外推；亚临界特征闭合通过独立积分证据 |
| Case 002 v4 坡床 | PASS (严格参考子集) | Q/depth 误差 0；默认 standard 不变 |
| 非棱柱静水 | PASS (严格静水子集) | A/T/P/I1 不同的全湿 lake-at-rest；一般移动流关闭失败 |
| Gate/Pump | PASS (MVP) | 固定或接受步一次性阈值质量通量/外排源汇，非强耦合/非 Q-H 工作点 |
| 结果过程线 | PASS | 独立 `hydraulic-result.mvp` |
| Case 001–005 场景 | PASS | Case 002 仅在显式严格参考子集通过；Case 004/005 为离散一次性阈值行为 |
| 多河网预留 | PASS | 5 个 Protocol，无伪实现 |
| HTTP/Celery/DB 闭环 | NOT IN THIS STAGE | 仅 direct engine，不对外写成已通过 |

## 7. 已知限制和下一阶段

1. Case 002 只在显式 `uniform-manning-reference-v1` 严格子集达到候选线；默认 standard 仍约 3.71%，一般移动稳态与全局二阶 IMEX 未证明。
2. 特征边界只支持全湿、正向、严格亚临界状态；边界作用在最近 Section cell face，不是任意端节点断面、rating curve 或超临界特征数配置。
3. 非棱柱路径只验收 lake-at-rest 和单步扰动不被冻结；一般移动流、湿干、多湿区、结构物及 manufactured-solution 收敛均关闭失败或未运行。
4. Gate 结构力/局损动量闭合、Pump Q-H/Q-η 工作点和连续阈值 crossing 定位未实现。
5. 湿干前沿、溃坝解析解、网格收敛阶、HEC-RAS/MIKE11 结果级对比和真实率定未运行。
6. v4-lite 仍未接入 HTTP/Celery/DB；`engine_version/engine_commit` 是调用方声明，结果 hash 也不是数字签名。

MODEL-02-C 应优先完成移动非棱柱 manufactured solution、湿干/溃坝和连续事件定位，再实现 Junction 特征兼容、结构物强耦合和安全后端持久化；B2 的两个 reference policy 不得被外推为上述能力已完成。
