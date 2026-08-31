# Phase 4 闸泵水力方程与约束

> **历史归档 / 自研 Solver 路线已废止（2026-08-31）：** 公式可作为历史专业参考，但它们已不是 Standard 1D 的生产执行实现；当前 MASCARET Adapter 对未验证的 Gate/Pump 映射明确 fail closed。见 [HYDRO-1D-RESET-01](../migration/HYDRO-1D-RESET-01.md)。

## 闸门

闸门必须使用已持久化的 `river_segment_id/upstream_node_id/downstream_node_id`，不从 GIS 坐标猜测正式拓扑。

- 自由/淹没孔流：`Q = Cd · b · a · sqrt(2gH)`，淹没时 `H` 取上下游有效水头差。
- 堰流：当有效水深不超过开度时 `Q = Cw · b · h^(3/2)`。
- 关闭、干床、最大流量、倒流允许/阻止均返回明确 `regime/constraint_flags`。
- 实际边通量还受上游可用水量限制；`available_flow_limited` 表示请求公式值与进入连续方程的实际值不同。

开度约束依次考虑资产可用性、最小/最大开度、最短持时、`opening_rate_limit × Δt`。初始状态不误判为刚发生变位。

## 泵站

泵站按请求机组数/目标流量确定 Q；Q-H 与 Q-η 均分段线性插值并禁止外推。功率和步能耗：

```text
P(kW) = ρ g Q H / (η · 1000)
E(kWh) = P · Δt / 3600
```

支持 `internal_transfer`、`external_outflow`、`external_inflow`。内部转输从进水节点扣除、向出水节点增加；外排/外引计入全域外边界。约束包括 online/maintenance/fault、整数机组、最短启停、最大启动次数、运行扬程、进水深度与曲线范围。

输出保存请求/实际控制、流量、上下游水位、扬程差、瞬时功率、累计能耗、流态、转输类型和原因。模拟状态仅存在于任务结果，绝不回写静态资产状态。

2 小时 DEMO：累计泵量 `140,400 m³`，峰值功率 `2,774.83 kW`，能耗 `4,374.21 kWh`。
