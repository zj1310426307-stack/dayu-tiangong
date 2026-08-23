# HYDRO-MODEL-02-B 当前基线任务书复核

日期：2026-08-23

复核基线：`main` 合并提交 `a0bdfbde74e39990f19915c8f097d13e2065a508`

性能加固分支：`feature/HYDRO-MODEL-02-B-performance-hardening`

## 1. 结论

任务书的自主单河 Saint-Venant 软件 MVP 已存在并保持可运行。当前复核没有重建历史 B 分支，而是在最新 `main` 上验证 v1/v2/v3 兼容边界，并关闭此前缺少稳定证据的 100 断面/24 h/<60 s 性能门。

软件 MVP 与冻结性能 smoke case 为 `GO`；一般动态长时程性能、湿干、端点断面、Pump Q-H、完整 Gate/Pump 强耦合、Branch/Junction、v4 后端任务链、外部结果级对比和真实率定继续 `NO-GO`。

## 2. 完成矩阵

| 任务书要求 | 当前状态 | 证据/边界 |
|---|---|---|
| v1/v2/v3 保持原语义 | PASS | `HydraulicEngine` 按 schema 精确分流；代表性路由与全仓回归通过 |
| 独立 v4-lite，不转回 v3 | PASS | `model/api/v4_lite.py`、`model/adapters/v4_lite.py`、`model/engine.py` |
| `finite_volume` 模块 | PASS | state/mesh/flux/reconstruction/friction/integrator/boundary/structures/diagnostics 及后续加固模块 |
| HydraulicState 与 Result 分离 | PASS | immutable `HydraulicState` 与独立 `dayu.hydraulic-result.mvp` DTO |
| 单河 cell/face/boundary 网格 | PASS | `FiniteVolumeMesh` 及 v4-lite adapter |
| 非规则断面 I1 | PASS | 矩形解析式、原始 Profile 折线分段解析积分及导数/大 datum 反例 |
| HLL + Rusanov reference | PASS | 通量组件与端到端测试 |
| Hydrostatic reconstruction | PASS（限定） | 棱柱/受限非棱柱 lake-at-rest；一般移动/湿干不外推 |
| SSP-RK2 | PASS | 每个 stage 重算边界、通量、摩阻和结构物 |
| CFL、重试和失败显式化 | PASS | maximum CFL/minimum dt/retry/failed gates 进入诊断和结果 |
| Manning 稳定处理 | PASS（MVP） | stage 级半隐式、符号安全；不是全局 IMEX |
| 动态 Q(t)/H(t) | PASS（限定） | 域内线性插值、折点对齐、禁止外推；限定特征闭合 |
| 固定/一次性 Gate | PASS（MVP） | B 的 mass-only Gate 保持；C2b/C2c 另有显式版本化强 Gate 子集 |
| ON/OFF Pump | PASS（MVP） | 定流量 external sink；Q-H/Q-η 未实现 |
| 独立结果过程线 | PASS | Section/Gate/Pump/水量/诊断/来源 hash |
| Case 001–005 | PASS（分级） | 科学子集、诊断基线与行为回归分开标注 |
| 数值/水量质量门 | PASS | finite、A≥0、干 cell Q=0、CFL 和动态水量账 |
| 100 断面/24 h/<60 s | PASS（冻结 smoke） | 100 个表格化 V 形断面，三个全新进程最坏 `41.3694 s` |
| 多 Branch/Junction 等接口 | PASS（仅 Protocol） | 5 个 Protocol，无伪实现 |
| 三份交付报告 | PASS | development/validation/benchmark 报告已同步 |

## 3. 性能加固

本轮只移除数值上严格等价的重复计算：

1. 同床面及较高床面一侧的 hydrostatic reconstruction 是精确恒等时，跳过断面反演和零压力修正；
2. HLL/Rusanov 为每侧状态合并水位、波速和压力通量评价；
3. 相邻面通过线程隔离、容量受限、精确状态/几何身份键复用 frozen geometry 评价；非 frozen geometry 不缓存。

性能脚本：`examples/hydraulic/saint-venant-mvp/benchmark_100_sections.py`。三次通过均为全新进程，耗时 `41.3694 s`、`36.7450 s`、`18.5833 s`，最坏值仍低于 60 s；每次均为 6,120 accepted steps、maximum CFL 0.7、minimum dt 9.7288555 s、retry 0、归一化水量误差 0。

该门只证明全湿非规则 lake-at-rest 的吞吐基线。带轻微动态洪峰的 100 断面/24 h 探针仍超过 60 秒，未完成结果不记为通过。

## 4. 验证

- `tests/model02`：`267 passed`；
- `tests + backend/tests`：`575 passed / 71 skipped / 0 failed`；
- 71 项 skip：既有 PostGIS、GeoServer、GDAL、QGIS 等外部环境门；
- `git diff --check`：通过；
- API/OpenAPI：本轮未变更，无需生成客户端同步。

## 5. 路径差异说明

任务书要求的基线内容保存在 `docs/review/HYDRO-MODEL-02-B-solver-baseline.md`，文件名比任务书多 `solver-`，内容职责一致。自动测试集中在 `tests/model02/`，没有机械复制为七个根目录测试文件；覆盖关系由测试函数和报告矩阵维护。
