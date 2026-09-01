# 复杂一维河网工程合同

更新日期：2026-09-02
适用范围：HYDRO-1D-ENGINEERING-03

## 权威模型

复杂一维河网继续使用同一 `hydraulic` schema 和 Dataset Version：

```text
Network → Node → directed Branch → Chainage → Cross Section/Profile
                                  ├→ Boundary / Lateral Inflow
                                  └→ Hydraulic Structure
```

`Branch.upstream_node_id` 指向水力上游，`downstream_node_id` 指向水力下游；`chainage_start_m < chainage_end_m`，桩号沿上游到下游严格递增。GIS 的 CGCS2000 `EPSG:4490` XY 只表示空间位置；距离、吸附和桩号计算在 Network 明确的米制 engineering CRS 中完成，不能把经纬度距离直接当桩号。

Node 可表达 `boundary`、`junction`、`bifurcation`、`internal` 和 `storage_connection`。当前 `storage_connection` 仅表示 Domain 语义；由于 CASIER 尚未完成 Adapter 与真实验收，提交 MASCARET 前会被能力门禁拒绝。

## 集中校验

`HydraulicNetworkValidator` 是 Adapter、Worker 和测试共享的唯一 Solver-neutral 拓扑校验器。它在任何原生文件生成之前检查：

- 悬空节点/河段引用、自环和重复有向边；
- 非法方向、断面缺失、同河段断面错序/重复桩号、最小断面几何；
- 外部上游/下游边界、内部节点误挂端点边界、横向入流桩号与时间序列；
- 孤立节点、多个意外连通分量、声明节点角色与实际入/出度不一致；
- 结构物和边界的 Branch、桩号及位置合法性。

稳定错误类别包括 `NETWORK_DISCONNECTED`、`NETWORK_BOUNDARY_MISSING`、`NETWORK_BOUNDARY_INTERNAL`、`NETWORK_NODE_ROLE_INVALID`、`INVALID_BRANCH_DIRECTION`、`INVALID_CHAINAGE`、`INVALID_CROSS_SECTION_ORDER` 和 `STRUCTURE_LOCATION_INVALID`。能力错误与 Domain/拓扑错误分层，不统一降格为模糊的 `MODEL_INVALID`。

`GET /api/v1/hydraulic/networks/{network_id}/graph` 一次返回 Node 入/出河段、Branch 端点、Cross Section 顺序、Structure 和 Boundary，供 GIS、前端和后续 Adapter 复用。入/出河段索引一次构建，避免节点×河段的二次扫描。

## 真实 MASCARET 验收

固定阈值来源为 `tests/benchmark/hydraulic_1d/network/acceptance-manifest.json`：节点连续性残差和全网质量残差均不超过 `0.005`，内部节点水位差不超过 `0.05 m`。节点门禁优先读取 MASCARET listing 中含初末库容、累计入流和累计出流的汇流控制体质量报告；断面端点瞬时不平衡仍作为透明诊断输出，但不冒充储量修正后的连续性误差。

| Case | 工程语义 | 节点连续性 | 全网质量残差 | 运行时 | 结果 |
|---|---|---:|---:|---:|---|
| N01 | 两入一出 Y 型汇流 | 0.251302% | 0.176207% | 10.69 s | PASS |
| N02 | 一入两出非等比分汊 | 0.201340% | 0.148250% | 7.19 s | PASS |
| N03 | 5 Branch、2 内部节点 | 0.131800% | 0.061818% | 10.77 s | PASS |
| N04 | 单河道 `Q_lateral(t)` | 0 | 0.015465% | 9.54 s | PASS |
| N05 | 多上游 `Q(t)` + 下游 `H(t)` + lateral | 0.279968% | 0.218371% | 13.43 s | PASS |

N02 最终流量为主河 `10.031 m³/s`、两分支 `6.325/3.701 m³/s`，验收没有假设 50/50。每个 case 同时记录 Branch 流量、水位、Q/H 峰值与时刻、model build、runtime、parser 和结果条数。

非运行时性能门使用 120 Branch、121 Node、600 Cross Section 的合成网络，校验和序列化各自设置宽松的 2 秒退化告警线。该测试用于阻止明显复杂度回退，不替代真实大工程压测。

## 边界

- 一个 Simulation 必须明确形成一个可解释的连通水力模型；不自动运行多个 disconnected components。
- Adapter 不修复错序断面、不猜河段方向、不静默删除未知边界或结构物。
- 本阶段没有实现 CAD 级河网编辑器、CASIER、二维网格或 1D/2D 耦合。
