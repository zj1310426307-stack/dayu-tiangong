# 一维求解器能力矩阵

更新日期：2026-09-03
Registry：`dayu.hydraulic-engine-capabilities.v2`

## 状态语义与门禁

版本控制清单 `model/hydraulic_1d/hydraulic_engine_capabilities.yaml` 以 engine、engine version 和 adapter version 为键。v2 将 `production_status`/`production_eligible` 与 `synthetic_status`/`accepted_cases`/`evidence_class` 分开：合成数值算例 PASS 不会把生产状态升格为 `VERIFIED_NATIVE`。生产只接受经现行门禁核准的 verified 能力；D-Flow 开发子集始终 `production_eligible=false`。

API `GET /api/v1/hydraulic/engine-capabilities` 返回 engine/version/feature、生产与合成状态、生产资格、已验收算例、证据等级、支持/未支持子集与 reason。Frontend 只使用该后端权威响应，不根据引擎名称自行推导。

## MASCARET v9.1.1

Adapter：`dayu-mascaret-adapter-v2`
官方 tag/commit：`v9.1.1` / `1fe3b5141f7d9c9fa8fe6d6d0316c994a39c2d95`

| Feature | 状态 | 证据 | Benchmark / 限制 |
|---|---|---|---|
| UNSTEADY_1D | VERIFIED_NATIVE | 官方 runtime + 统一结果链 | B01–B05；31/31 |
| STEADY_1D | UNVERIFIED | 官方上游存在 steady kernel | 当前 Adapter 不生成正式 steady case |
| BRANCHED_NETWORK | VERIFIED_NATIVE | native `listeBranches/listeNoeuds` | N01–N03；内部 native node 当前要求恰好三条 extremity |
| LATERAL_INFLOW | VERIFIED_NATIVE | native `debitsApports` | N04–N05；支持 constant Q 与 Q(t) |
| COMBINED_BOUNDARIES | VERIFIED_NATIVE | 多 Q(t)+H(t)+lateral | N05 |
| WEIR | VERIFIED_NATIVE | native geometric seuil / REZO | S01；仅固定宽顶几何堰已验证 |
| CULVERT | UNVERIFIED | 未建立 Dayu→MASCARET 等价语义 | 不运行 |
| BRIDGE | UNVERIFIED | 未证实当前 Adapter 的原生桥梁语义 | 不运行 |
| GATE | UNSUPPORTED | 无完整控制/开度语义与 benchmark | fail closed |
| SLUICE | UNSUPPORTED | 未映射活动控制 | fail closed |
| PUMP | UNSUPPORTED | 当前验证 Adapter 无安全映射 | fail closed |
| ORIFICE / DAM / STORAGE_LINK / COMPOUND | UNVERIFIED | 无本阶段真实 benchmark | 不运行 |
| CASIER | UNVERIFIED | v9.1.1 源码存在 Casier/Liaison 能力 | Dayu Domain、Adapter 和 runtime case 未完成 |

每个 VERIFIED 行都能追溯到 source-controlled benchmark ID。状态不是“MASCARET 永久支持某功能”的布尔声明，未来 engine/adapter 版本必须新增或更新独立矩阵。

## D-Flow FM / HYDROLIB-core 开发适配器

当前已建立 `dayu-dflow-fm-adapter-v1` 的开发期合同：Solver-neutral 1D 模型严格校验、HYDROLIB-core `1.0.1` 类型化 Network/MDU/INI/BC/DIMR 生成、Gate/Pump 受限映射、HIS NetCDF 结果解析、Job Workspace 隔离及 DIMR CLI/Container 运行边界。官方源固定为 `DIMRset_2026.02` / `5a4649830b1e5072caf019fb4850bbdefd9ad431`。

开发证据现已绑定 reviewed OCI digest、四组件 provenance、acceptance registry v2 及每份紧凑证据的 SHA-256。官方 D-Flow 01、官方 D-Flow+FBC 10、DF01、DRTC-S01、G01–G03、PUMP01–PUMP02、GP01–GP03 与 24h L01 均已 PASS。其中 Pump 只开放经审计的 `pumps/<id>/capacity` aggregate Capacity 目标，并将 requested/resolved/native Capacity 与 actual structure discharge 分开；`pump_enabled`、`pump_unit_count`、Pump threshold、分级 Pump 仍关闭。Gate 可以使用单水位阈值，且 GP03 证明它可与另一 Pump 的手工 Capacity schedule 在同一 FBC 组件中并行。

这些全部是 `SYNTHETIC_NUMERICAL_ONLY`：D-Flow 的生产状态仍为 `EXPERIMENTAL`/`UNVERIFIED`，不具备生产资格，也不影响 MASCARET 作为 Standard 1D 默认引擎的现有验证矩阵。Bridge/Culvert 的早期序列化 spike 仍不是 runtime 或数值证据。

官方资料：

- [HYDROLIB-core Structure overview](https://deltares.github.io/HYDROLIB-core/latest/reference/dflowfm/external-forcing/structures/structure-overview/)
- [HYDROLIB-core documentation](https://deltares.github.io/HYDROLIB-core/latest/)
- [Deltares Delft3D repository](https://github.com/Deltares/Delft3D)
- [D-Flow FM Technical Reference Manual](https://content.oss.deltares.nl/delft3d/D-Flow_FM_Technical_Reference_Manual.pdf)

HYDROLIB-core `1.0.1` 的包元数据为 MIT；Delft3D 仓库各组件使用 AGPL/GPL/LGPL 等不同许可证，不能概括成一个统一许可证。任何 runtime 镜像分发前必须完成逐组件清单和人工许可证审查。MASCARET 仍按 GPL-3.0-only 的外部部署/分发边界审查。以上仅记录事实，不构成法律意见。

详细 Adapter、Runtime、依赖和 blocked 判据见 [`dflow-fm-adapter.md`](./dflow-fm-adapter.md)；D-RTC 编译语义见 [`../dispatch/drtc-compiler.md`](../dispatch/drtc-compiler.md)。

## 运行来源

Engineering-03 复用 MASCARET-02 的 provenance：官方 source archive/tree hash、tag、commit、binary SHA-256、resource digest、build timestamp、平台/架构和 `is_real/version_verified`。本次真实门禁的 binary SHA-256 为 `632967296f39bf548b37eceee242f0125ed4364ddced4e50a697d3047b7c48b9`，source tree SHA-256 为 `cd116294009e08872331cab1dedc54f2321f13bbb304c863c0e06c07e17e3a6f`。
