# HYDRO-MODEL-02-D3A-RC1-FIX1A Validation Report

- 日期：2026-08-30
- 基线 head：`4ecfd3bead769af38381f4d4b6a9b3523a64feef`
- 审计提交：`5e48c0a`
- PR：[#12](https://github.com/zj1310426307-stack/dayu-tiangong/pull/12)，OPEN / NOT MERGED
- FIX1A 证据 head：`d20275a39c63336c2b24e68a483c52a0d877b351`
- 当前状态：`FIX1A GATES PASS / MERGE READY FOR INDEPENDENT REVIEW / PR NOT MERGED`

## 本地 FIX1A 证据

| 门 | 结果 |
| --- | --- |
| v3 schema/status | `dayu.d3a-final-convergence.v3` / PASS |
| global peak-Q argmax | time 与 chainage 漂移，`non-smooth-global-extremum` |
| global peak-Q smooth evidence | 禁用，`used_as_smooth_spatial_convergence_evidence=false` |
| fixed-monitor peak Q | 2850 m exact；`p=2.2157067924`；fine error `0.141618%` |
| known limitation | FIX1 legacy fine error `13.99%` 显式记录，非有效 smooth error bound |
| fine CFL/2 | dt ratio 0.5；既有时间稳定门与新增 monitor-Q 门通过 |
| completion gates | 10/10 true |
| Python 3.12 science | 9 passed / 0 failed / 0 skipped |
| Python 3.11 science | 9 passed / 0 failed / 0 skipped |
| MODEL02 non-long | 375 passed / 0 failed / 0 skipped |
| legacy hydraulic | 26 passed / 0 failed / 0 skipped |
| D3A model-engine contracts | Python 3.11：43 passed；Python 3.12：43 passed |
| v2 negative control | collector 按预期拒绝 |

checked v3 artifact SHA-256：
`60c6279d2675de6fbba30be806eb20bedc5a8e2044e425f4f1a09e6d00d6c149`。

Python 3.11 与 Python 3.12 v3 artifacts 的 argmax、fixed-monitor Q、smooth/event/time
comparisons、网格与 completion gates 完全一致。只存在三项约机器精度的
`relative_water_balance_error` 末位差异：medium `4.6733786548580604e-17` vs
`4.673378654858061e-17`、fine `4.893446311165272e-16` vs
`3.016402185493353e-16`、fine CFL/2 最后一位差异。它们均远低于冻结的 `1e-10`
门，按既有跨平台规则以科学容差验收，不冻结 libm/求和顺序的最后 bit。

## Hosted 闭合

- [x] Hosted Python 3.11 `D3A scientific validation` push/PR SUCCESS：82/82；
- [x] Python 3.12.14 `D3A shipping science` push/PR SUCCESS：51/51；
- [x] push shipping artifact 精确记录 evidence head `d20275a39c63336c2b24e68a483c52a0d877b351`；
- [x] PR shipping artifact 精确记录 merge ref `bc27f97c2a3b210340b029c83c127a27b3d7f1b0`；
- [x] checked、push Python 3.11/3.12、PR Python 3.11/3.12 五份 v3 artifact 在排除 `runtime_seconds` 与约机器精度 `relative_water_balance_error` 后逐字段一致；
- [x] PR #12 保持 OPEN / MERGEABLE / NOT MERGED。

Hosted runs：

- model02 push `33304871002`：SUCCESS；
- hydraulic-platform push `33304871124`：SUCCESS；
- model02 pull_request `33304874227`：SUCCESS；
- hydraulic-platform pull_request `33304874197`：SUCCESS。

以上结论只把 FIX1A 标记为可供独立审查；不得自动合并 PR、创建 D3A tag 或启动 D3B。

## 作用域

未修改核心水力方程、Manning、bed/nonprismatic、Gate/Pump、runtime envelope、
friction predictor、D2 任务平台、API/OpenAPI 或前端。FIX1A 只改变证据字段、分类、
collector、CI artifact 和文档。
