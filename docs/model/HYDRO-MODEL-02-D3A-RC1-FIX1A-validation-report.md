# HYDRO-MODEL-02-D3A-RC1-FIX1A Validation Report

- 日期：2026-08-30
- 基线 head：`4ecfd3bead769af38381f4d4b6a9b3523a64feef`
- 审计提交：`5e48c0a`
- PR：[#12](https://github.com/zj1310426307-stack/dayu-tiangong/pull/12)，OPEN / NOT MERGED
- 当前状态：`LOCAL FIX1A GATES PASS / HOSTED PENDING / PR NO-GO`

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

## 尚待 Hosted 闭合

- [ ] Hosted Python 3.11 `D3A scientific validation` push/PR SUCCESS；
- [ ] Python 3.12 `D3A shipping science` push/PR SUCCESS；
- [ ] shipping artifact 记录最终精确 head / PR merge ref；
- [ ] 下载后除 `runtime_seconds` 外与 checked v3 artifact 逐字段一致；
- [ ] PR #12 保持 OPEN / CLEAN / MERGEABLE。

Hosted 全部完成前，不得标记 `MERGE READY`，不得合并 PR、创建 D3A tag 或启动 D3B。

## 作用域

未修改核心水力方程、Manning、bed/nonprismatic、Gate/Pump、runtime envelope、
friction predictor、D2 任务平台、API/OpenAPI 或前端。FIX1A 只改变证据字段、分类、
collector、CI artifact 和文档。
