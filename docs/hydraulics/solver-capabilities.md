# 一维求解器能力矩阵

更新日期：2026-09-02
Registry：`dayu.hydraulic-engine-capabilities.v1`

## 状态语义与门禁

版本控制清单 `model/hydraulic_1d/hydraulic_engine_capabilities.yaml` 以 engine、engine version 和 adapter version 为键。状态只有：`VERIFIED_NATIVE`、`VERIFIED_EQUIVALENT`、`EXPERIMENTAL`、`UNVERIFIED`、`UNSUPPORTED`。只有前两类可进入生产 Adapter；其余状态都在 Runtime 前 fail closed。

API `GET /api/v1/hydraulic/engine-capabilities` 返回版本、feature、status、reason、benchmark IDs 和验证日期，不泄露宿主可执行路径。Frontend 使用同一生成客户端显示当前模型所需能力与求解器状态。

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

这些合同仍只是开发证据：

- 早期 Bridge/Culvert/Pump `structures.ini` spike 仍只证明序列化，不是 runtime 或数值证据；
- 新 Adapter 会生成并重读 native case，但尚无官方 D-Flow/D-RTC case 和 Dayu benchmark 通过已审查 runtime；
- 本机/仓库无满足 provenance 合同的 `dflowfm` / `dimr` / `fbc` 二进制或不可变镜像，因此当前为 `DFLOW_RUNTIME_BLOCKED`；
- D-Flow FM 登记仍 `production_eligible=false`；`UNSTEADY_1D`、`BRANCHED_NETWORK`、`GATE`、`PUMP`、`ORIFICE`、`DYNAMIC_CONTROL` 为 `EXPERIMENTAL`，`D_RTC` 与其余未验证能力为 `UNVERIFIED`，没有任何 `VERIFIED_NATIVE` 或 `VERIFIED_EQUIVALENT`，不影响 MASCARET 现有验证矩阵。

官方资料：

- [HYDROLIB-core Structure overview](https://deltares.github.io/HYDROLIB-core/latest/reference/dflowfm/external-forcing/structures/structure-overview/)
- [HYDROLIB-core documentation](https://deltares.github.io/HYDROLIB-core/latest/)
- [Deltares Delft3D repository](https://github.com/Deltares/Delft3D)
- [D-Flow FM Technical Reference Manual](https://content.oss.deltares.nl/delft3d/D-Flow_FM_Technical_Reference_Manual.pdf)

HYDROLIB-core `1.0.1` 的包元数据为 MIT；Delft3D 仓库各组件使用 AGPL/GPL/LGPL 等不同许可证，不能概括成一个统一许可证。任何 runtime 镜像分发前必须完成逐组件清单和人工许可证审查。MASCARET 仍按 GPL-3.0-only 的外部部署/分发边界审查。以上仅记录事实，不构成法律意见。

详细 Adapter、Runtime、依赖和 blocked 判据见 [`dflow-fm-adapter.md`](./dflow-fm-adapter.md)；D-RTC 编译语义见 [`../dispatch/drtc-compiler.md`](../dispatch/drtc-compiler.md)。

## 运行来源

Engineering-03 复用 MASCARET-02 的 provenance：官方 source archive/tree hash、tag、commit、binary SHA-256、resource digest、build timestamp、平台/架构和 `is_real/version_verified`。本次真实门禁的 binary SHA-256 为 `632967296f39bf548b37eceee242f0125ed4364ddced4e50a697d3047b7c48b9`，source tree SHA-256 为 `cd116294009e08872331cab1dedc54f2321f13bbb304c863c0e06c07e17e3a6f`。
