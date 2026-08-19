# HYDRO-MODEL-02-B 开发报告

日期：2026-08-20
阶段状态：软件 MVP 可运行；科学/生产验收 `NO-GO`

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
Q(t)/H(t) + fixed Gate + ON/OFF external Pump
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

## 3. 边界与结构物

- 上游 Q(t) 和下游 H(t) 采用域内线性插值，必须覆盖 `[0,duration]`，超域直接失败。
- Gate 在每个 RK stage 使用当前上下游水位重算定开度质量通量。它尚未闭合结构力/局损动量，因此强制输出 `structure_momentum_closure_mass_only_mvp`。
- Pump 是单 cell 的 ON/OFF 定流量外排源汇，移除对应质量与局部平流动量，外排体积进入全局水量账。

Case 004/005 只对固定开/关状态做对照。任务书同时写了“固定开度/ON-OFF”与“超阈动作”，但没有冻结控制规则合同；本阶段没有暗造阈值或回填动作时间，自动调度留给 MODEL-02-C。

## 4. 输入与结果合同

### 4.1 `dayu.model-input.v4-lite`

合同使用 Pydantic 强类型、`extra=forbid`和非有限数门禁，并严格校验：

- Dataset/CRS/Branch/Section/Profile 身份；
- Chainage 顺序、显式初态和 Profile 水位范围；
- 单槽、单调岸坡且各 cell 完全相同的棱柱非规则断面限制；
- 边界类型、两端节点、唯一身份和时域覆盖；
- Gate 相邻 face 绑定和 Pump 明确 external outlet；
- 唯一 solver tuple。

引擎入口先把 JSON 规范化成独立快照并预计算 hash，之后的解析、求解和结果均使用该副本，阻断运行中调用方修改导致的 TOCTOU 证据错配。

### 4.2 `dayu.hydraulic-result.mvp`

MVP 结果是独立 DTO，不继承 `EngineResult`，包含：

- 逐 Section 的 time/water_level/flow/velocity；
- Gate opening/flow 和 Pump status/flow；
- 动态初末库容、边界体积、Pump 外排体积及归一化误差；
- maximum CFL、minimum dt、retry/step count 和强制诊断；
- 输入快照 hash 和实际消费几何的 mesh hash。

mesh hash 包含实际 Profile points、dx、Manning n、几何处理策略和声明的 Profile hash，不仅信任调用方标签。

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
| Q(t)/H(t) | PASS | 插值、折点对齐、禁止外推 |
| Gate/Pump | PASS (MVP) | 固定质量通量/外排源汇，非强耦合/非 Q-H 工作点 |
| 结果过程线 | PASS | 独立 `hydraulic-result.mvp` |
| Case 001–005 场景 | PASS/PARTIAL | 5 个 MVP 场景通过；Case 002 严格科学门 XFAIL |
| 多河网预留 | PASS | 5 个 Protocol，无伪实现 |
| HTTP/Celery/DB 闭环 | NOT IN THIS STAGE | 仅 direct engine，不对外写成已通过 |

## 7. 已知限制和下一阶段

1. Case 002 恒定均匀流当前流量最大相对误差约 3.71%，未达 0.1% 候选科学线。
2. Q/H 边界的 companion 量仍是亚临界 MVP 零梯度闭合，尚无特征边界和流态相容性判定。
3. 非棱柱几何源项和多湿区复式断面未实现，v4-lite 已 fail-closed 到单槽、完全相同 Profile。
4. Gate 结构力/局损动量闭合、Pump Q-H/Q-η 工作点和阈值调度未实现。
5. 湿干前沿、溃坝解析解、网格收敛阶、HEC-RAS/MIKE11 结果级对比和真实率定未运行。
6. 直连输入中的 `engine_version/engine_commit` 是调用方声明，未经任务系统运行时证明；持久化阶段必须与 Worker 运行时元数据做等值校验。

MODEL-02-C 应优先关闭 Case 002、特征边界、非棱柱源项和结构物强耦合，再扩展 Branch/Junction 河网。
