# Phase 4 河网耦合

> **历史归档 / 已由 HYDRO-1D-RESET-01 废止（2026-08-31）：** 本文记录已删除的自研 1D Solver 河网耦合方案，不得作为当前实现或运维指引。现行生产路线是 Unified Hydraulic Model + MASCARET Adapter，见 [HYDRO-1D-RESET-01](../migration/HYDRO-1D-RESET-01.md)。

## 领域模型与拓扑

`NetworkMesh` 由 `river_node`、`river_segment`、`river_connection` 和每河断面网格构建。构建时拒绝有向环、自环、重复边、悬空节点、方向不连续、无法映射的外边界与少于 3 个断面的分支。

## 节点条件

河网在统一时轴上按 DAG 路由。节点控制量使用：

```text
Q_available = ΣQ_in + Q_external + Q_structure_source_sink
ΣQ_out = Q_available
residual = ΣQ_in + source_sink - ΣQ_out
```

汇流直接累加，一入多出按河段长度倒数权重分流；有闸门的边先应用实际闸门通量，其余边分配剩余流量。节点采用共同水位，下游水位边界向上游按 Manning 损失回算。

全网以最短河段、代表断面波速和请求步长计算统一保守 CFL 步长；时轴精确包含 `0`、结束、输出、人工计划与规则检查时刻。最终 DEMO 同步步长 `60 s`、CFL `0.0268536`。诊断明确记录 `momentum_compatibility: not implemented`。

## 定量证据

- Y 汇流：`10 + 15 = 25 m³/s`，最大节点残差 `0`。
- 等权分流：`20 → 10 + 10 m³/s`。
- 2 小时 DEMO：最大节点残差 `7.11×10⁻¹⁵ m³/s`，全域相对残差 `6.74×10⁻¹⁷`。
- 所有网络基准确定性重复且无 NaN/Inf。

## 限制

共同水位 + 连续性尚未完整处理汇分流局部损失、节点动量与能量兼容，也未支持有向环河网。Phase 5 前应先率定并评估更高阶节点耦合方法。
