# HYDRO-MODEL-02-D3A-RC1-FIX1 Release Readiness

- 当前：`FIX1 GATES PASS / MERGE READY FOR INDEPENDENT REVIEW`
- PR：[#12](https://github.com/zj1310426307-stack/dayu-tiangong/pull/12)，NOT MERGED
- D3A tag：未创建
- D3B：未创建、未启动

## 已完成

- [x] pre-FIX1 defect 与旧 artifact 独立审计；
- [x] 旧证据标记 `superseded-pre-FIX1`；
- [x] 运行前冻结 18/54/162 odd3 nested grid；
- [x] Gate/Pump/monitor 全层 exact location；
- [x] smooth metrics 正阶、Richardson limit 与 fine estimated error；
- [x] Gate event spatial trend 与 5 s locator tolerance 分离；
- [x] 新增 `dayu.d3a-final-convergence.v2` reference/test/collector；
- [x] `D3A scientific validation` / `D3A shipping science` 切换到 FIX1 长测；
- [x] 核心水力、D2 平台、API/OpenAPI/前端保持不变。

## 发布前必须完成

- [x] fine CFL/2 四层完整 artifact PASS；
- [x] 本地 D1/D2/MODEL02/Frontend/OpenAPI 回归；
- [x] 实际 SHA 的 Python 3.12 shipping image 完整科学门；
- [x] push/PR Python 3.11 `D3A scientific validation` SUCCESS；
- [x] push/PR Python 3.12 `D3A shipping science` SUCCESS；
- [x] MODEL02 Ubuntu/Windows、Frontend contract、hydraulic-platform 与 D2 required checks SUCCESS；
- [x] evidence head 所有检查 SUCCESS，push/PR shipping artifacts 已核对；
- [x] PR 仍 OPEN、未合并；无 D3A tag、无 D3B 分支。

Evidence head `d0aa74860471acfeb92a6cccaae5385059702cd9` 的四个 Hosted runs
`33272555233 / 33272555234 / 33272557735 / 33272557769` 全部成功。本文仍不是
merge 或 tag 授权；最终文档 head 也必须重新通过同一组保护门。

任何位置、空间趋势、事件分离、时间细化、包络/水量/残差/摩阻或 shipping 门失败，
均应保持 `FIX1 FAIL/BLOCKED / PR NO-GO / D3B NO-GO`，不得改选有利网格。
