# HYDRO-MODEL-02-D3A-RC1-FIX1 Baseline Audit

- 日期：2026-08-30
- FIX1 base / PR head：`3570d39141fbb7095ee2c7aaedabe963ea06d0d6`
- RC1 implementation head：`8da24aa12f05f9e13731c85b69ed864961c748dd`
- 分支：`feature/HYDRO-MODEL-02-D3A-engineering-single-river`
- PR：[#12](https://github.com/zj1310426307-stack/dayu-tiangong/pull/12)，`OPEN / MERGEABLE / NOT MERGED`
- FIX1 方案 SHA-256：`33ca24dbbcb5f0366812f0cbdfcd50cb4007e3ae9e7445f2a80dec02b428d23e`

## 旧发布证据

旧 `outputs/d3a/final-convergence.json` 使用 60/70/80 cells；80-cell CFL `0.7→0.35` 作为时间细化。连续物理函数、边界、Gate/Pump 参数和控制一致，但空间网格只按 uniform nearest-center 映射 Pump/monitor。

| cells | nominal dx | Gate target / mapped | Pump target / mapped | Monitor target / mapped |
| ---: | ---: | --- | --- | --- |
| 60 | 126.6667 m | 3040 / 3040 m | 6000 / 6016.6667 m | 2850 / 2850 m |
| 70 | 108.5714 m | 3040 / 3040 m | 6000 / 6025.7143 m | 2850 / 2877.1429 m |
| 80 | 95.0000 m | 3040 / 3040 m | 6000 / 6032.5000 m | 2850 / 2802.5000 m |

旧 Gate event 为 `2937.257 / 2940.669 / 2943.227 s`，coarse-medium 与 medium-fine 差分别为 `3.4122 / 2.5577 s`。该趋势可作为历史 smoke，但 medium-fine 差进入 5 s 只说明与单网格 event-locator policy 同量级，不能证明 fine-grid spatial error 小于 5 s。

因此 60/70/80 具有三个独立缺陷：

1. nominal refinement ratios 仅约 `1.1667`、`1.1429`，低于 FIX1 的 `r>=1.5`；
2. Pump control volume 和 monitor sample 的物理位置随网格漂移；
3. event-locator tolerance 与 mesh-induced event error 未分离。

结论：旧证据保留但立即降级为 `superseded-pre-FIX1`，不能继续作为严格 spatial convergence release evidence。

## 求解器非均匀网格兼容审计

D3A-3 工程路径没有 uniform-grid 门。当前实现逐 cell 使用 `FiniteVolumeCell.dx`：Euler 通量散度、Pump sink、几何压力源、Manning、CFL、蓄量和水量诊断均使用本 cell 长度；internal hydraulic face 以相邻 `dx` 计算插值权重。强制 uniform cell-centre 的检查只属于独立的 `nonprismatic-frictionless-energy-reference-v1` science scope，不适用于 FINAL D3A-3 工程案例。

输入适配器以相邻 section chainage 中点构造 FV faces。本 FIX1 因此不虚构独立 mesh：它冻结一组 section sites，并按 1D Voronoi 中点规则生成实际 cell boundaries、lengths 和 control-volume centroids，再把这些真实值写入 manifest/hash。

## 运行前冻结的新 grid family

网格族固定为 `structure-aligned-voronoi-odd3-v1`：

- base section sites 共 18 个；
- 每一级在每个旧 site gap 的 `1/3` 与 `2/3` 处加点，并在两端补齐边界 cell；
- cell counts 固定为 `18 / 54 / 162`，refinement ratio 固定为 `3 / 3`；
- 这是奇数加密：每个父 control volume 被三个子 control volumes 精确分割，父 site 与父 face 均保留；
- base sites 在 monitor/Pump 两侧使用等距邻点，分别固定 `2850 m`、`6000 m` control-volume centroid；
- Gate 的相邻 sites 关于 `3040 m` 对称，固定 exact face。

该规则在任何新仿真前冻结，不依据 Gate event 或其他结果挑选网格。若 18/54/162 不能同时满足所有 completion gates，FIX1 必须报告 FAIL，不得更换成“更接近”的三层结果。

## Shipping baseline

当前 `D3A scientific validation` 与 `D3A shipping science` 运行旧 `test_d3a_final_convergence.py`，Python 3.12 artifact 名为 `final-convergence.json`。FIX1 必须新增独立测试与 `final-convergence-fix1.json`，旧测试和旧 artifact 仅作为历史 smoke 保留。
