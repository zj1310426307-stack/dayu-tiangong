# HYDRO-MODEL-02-B/B2 Benchmark 报告

日期：2026-08-20
测试文件：`tests/model02/test_mvp_benchmarks.py`
实现提交：`48abdab`

## 1. 分级原则

5 个场景不共用“科学验证通过”标签：

- Case 001 是已冻结限定子集的严格静水门。
- Case 002 的严格科学候选门只在显式、解析校验的 `uniform-manning-reference` 子集内通过；默认 `standard` 仍作为未修正基线保留。
- Case 003 是传播因果行为回归；Case 004/005 同时覆盖固定工况和接受步一次性阈值动作，但仍不是结构物强耦合科学验证。

主 Benchmark 文件：`13 passed`；阈值控制专项：`10 passed`。B2 另以坡床、特征边界和非棱柱三个独立测试文件冻结端到端与反例证据。

## 2. 通用质量门

每个场景都检查：

- 状态、流速、dt 和 CFL 全有限；
- A≥0、depth≥0，干 cell 不携带 Q；
- 接受步时间严格递增并精确到达 end time；
- `maximum_cfl` 不超过配置；
- SSP-RK2 每接受步两个 stage；
- 用初末库容和边界/泵体积独立重算水量账。

## 3. 场景结果

| Case | 等级 | 结果 | 关键证据 | 不能证明 |
|---|---|---|---|---|
| 001 静水保持 | scientific subset | PASS | 同宽矩形变床；max |u| 约 1.25e-15 m/s，最大水位漂移 0，balance 约 2.75e-16 | 一般非棱柱非规则断面 |
| 002 标准离散基线 | diagnostic baseline | REPRODUCED / SCIENTIFIC NO-GO | 默认 `standard` 仍复现 Q 误差约 3.70699%、水深误差约 0.04484 m | 通用移动稳态精度 |
| 002 科学候选 | restricted scientific subset | PASS | v4-lite-2 端到端 Q/depth 误差 0；balance 约 2.67e-17 | 默认 standard、一般 moving equilibrium、全局 IMEX |
| 003 洪峰传播 | MVP behavior | PASS | 近/远 cell 首次响应约 420/600 s，峰时约 690/840 s，折点 300/600/900 s 精确对齐 | 解析波幅、峰时精度或收敛阶 |
| 004 Gate | MVP behavior | PASS | 固定开度公式与质量转移继续通过；水位严格超过阈值后在接受步末只开闸一次 | 连续 crossing 定位、动量/能头强耦合 |
| 005 Pump | MVP behavior | PASS | ON/OFF 质量账继续通过；高水位在接受步末只启动一次，外排仅从下一步积分 | Q-H/Q-η 工作点、能耗、连续事件定位 |

五个动态场景的归一化水量误差都在约 `1e-16` 量级，但这只证明当前离散质量账闭合，不代表动量、波速或结构物能量闭合已验收。

## 4. 特征边界与非规则断面附加门

`tests/model02/test_finite_volume_core.py` 另有一个平床、完全相同梯形 Profile 的 lake-at-rest 测试，证明 v4-lite 所允许的“非矩形但棱柱”子集可保持静水。

`subcritical-characteristic-v1` 已通过矩形解析 invariant 及非矩形、non-matching Q/H 的独立高分辨率 Simpson Φ 交叉校核；它仍拒绝干、临界/超临界、反向和无根状态。

已知旧算子反例显示，变宽或逐断面异形河道可在水量误差约 `1e-16` 时仍产生明显伪流。B2 新增 `hydraulic-function-linear-face-v1`，在 A/T/P/I1 确有差异的三断面 v4 案例中得到最大水位漂移 0、最大 |Q| 约 `2.29e-15 m3/s`。公开合同同时锁死为全湿 lake-at-rest；移动 Q、不同初始 H、动态/错误边界、结构物和策略混搭都被拒绝。共线冗余点或断面水平平移不能伪装成“非棱柱通过”。

边界空间支撑为最近 Section cell face。Case 002 末 Section 与 Branch 端点相差 25 m，连续坡床端点 H 与当前离散边界 H 相差约 0.019841 m；该差异被明确列为后续端点 face 几何工作，而不是隐藏在 node 身份中。

## 5. 总判定

- 5 个任务书场景的 MVP/限定科学门：`PASS`。
- Case 002：v4-lite-2 严格参考子集 `PASS`；默认 standard 和通用移动稳态仍 `NO-GO`。
- 非棱柱 lake-at-rest：严格静水子集 `PASS`；一般移动非棱柱、湿干和结构耦合仍 `NO-GO`。
- 湿干溃坝、网格收敛、闸泵强耦合、HEC-RAS/MIKE11 和真实率定：`NOT RUN / NO-GO`。

## 6. 2026-08-23 性能 Benchmark

新增可复跑的 `examples/hydraulic/saint-venant-mvp/benchmark_100_sections.py`，冻结以下吞吐 smoke case：

- 单河、100 个表格化 V 形非规则断面；
- 24 h、HLL、hydrostatic reconstruction、SSP-RK2；
- 全湿 lake-at-rest，Q=0、上下游完整覆盖且禁止外推；
- 结果保留全部 6,120 个接受步和 25 个整点输出。

当前机器三个全新进程实测分别为 `41.3694 s`、`36.7450 s`、`18.5833 s`，最坏值仍低于 60 s；maximum CFL `0.7`、minimum dt `9.7288555 s`、retry `0`、归一化水量误差 `0`，任务书 `<60 s` 门在该明确子集内重复 `PASS`。

作为反例，带轻微动态洪峰的 100 断面/24 h 探针仍超过 60 秒，未完成结果不记为通过。因此该性能门只证明静水吞吐下限，不证明一般非恒定流、Gate/Pump 或生产容量。
