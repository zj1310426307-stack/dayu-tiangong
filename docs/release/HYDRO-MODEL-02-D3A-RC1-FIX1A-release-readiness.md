# HYDRO-MODEL-02-D3A-RC1-FIX1A Release Readiness

- 当前：`FIX1A GATES PASS / MERGE READY FOR INDEPENDENT REVIEW / PR NOT MERGED`
- PR：[#12](https://github.com/zj1310426307-stack/dayu-tiangong/pull/12)，NOT MERGED
- D3A tag：未创建
- D3B：未创建、未启动

## 已完成

- [x] 在修改前审计 coarse/medium/fine global peak-Q argmax；
- [x] artifact 每层记录 peak-Q absolute/signed value、time、section 与 chainage；
- [x] 观测到 argmax 漂移后重分类为 `non-smooth-global-extremum`；
- [x] global peak-Q 从 smooth acceptance 移除；
- [x] 新增 exact 2850 m fixed-monitor peak-Q convergence，`p=2.215707`；
- [x] `13.99%` 在 v3 known limitations 显式记录；
- [x] collector 只接受 classified four-level v3 PASS；
- [x] 旧 v2 被 negative control 拒绝；
- [x] 本地 Python 3.12 science 9/9 PASS；
- [x] 本地 Python 3.11 science 9/9 PASS；
- [x] MODEL02 375、legacy 26、D3A model-engine 43（双版本）回归 PASS；
- [x] 核心水力、D2、API/OpenAPI 与前端保持不变。

## Hosted 与治理闭合

- [x] Hosted Python 3.11 science push/PR 82/82 PASS；
- [x] Python 3.12.14 shipping science push/PR 51/51 PASS；
- [x] push 与 pull_request 两种事件的 model02/hydraulic-platform 全绿；
- [x] 五份 v3 artifacts 在机器相关字段规则下与 checked artifact 一致；
- [x] push identity 绑定 `d20275a39c63336c2b24e68a483c52a0d877b351`，PR identity 绑定 merge ref `bc27f97c2a3b210340b029c83c127a27b3d7f1b0`；
- [x] PR #12 仍 OPEN、未合并；无 D3A tag、无 D3B 分支。

运行编号：model02 push `33304871002`、hydraulic push `33304871124`、model02 PR
`33304874227`、hydraulic PR `33304874197`，全部 SUCCESS。

任何 argmax 字段、fixed-monitor Q 趋势、known limitation、时间细化、包络/平衡/残差/
摩阻或 shipping identity 失败，均保持 `FIX1A FAIL / PR NO-GO / D3B NO-GO`。
