# HYDRO-MODEL-02-D3A-RC1 正式发布记录

- 发布日期：2026-08-30
- 记录更新：2026-08-31
- 状态：`D3A RC1 RELEASED`
- PR：[#12](https://github.com/zj1310426307-stack/dayu-tiangong/pull/12)，`MERGED`
- PR head：`e574f57dbee88d9798032f156b626eb2998cffcb`
- merge commit：`eb6b1b41e5416fb5dbcec17ad9bdf7c1923807a9`
- annotated tag：`hydro-model-02-d3a-rc1`
- tag object：`3e9416caab34ab4c49459ea19a2dbf1c5f2722db`

## 发布验证

PR #12 使用普通双亲 merge commit 合并。第一父提交为旧 `main@a40a9f8`，第二父提交
为 PR head `e574f57`；merge tree 与 PR tree 均为
`58e4990277b67420d8e47368bd11f2a6bcf76b8d`。

合并后的 main workflows：

| Workflow | Run | 结果 |
| --- | ---: | --- |
| model02 | `33309205534` | SUCCESS |
| hydraulic-platform | `33309205538` | SUCCESS |

main 的 strict required checks 为 11/11 SUCCESS。Python 3.11 D3A science 为 82/82，
Python 3.12.14 shipping science 为 51/51；shipping
`RuntimeBuildIdentity.engine_commit` 精确等于 merge commit。

annotated tag 已通过 GitHub tag object 复核，解引用后精确指向
`eb6b1b41e5416fb5dbcec17ad9bdf7c1923807a9`，不是 lightweight tag。

## 冻结科学结论

FIX1A 将发生时空 argmax 漂移的 global peak-Q 重分类为
`non-smooth-global-extremum`。exact 2850 m fixed-monitor peak-Q 的观测阶为
`p=2.2157067924`，fine estimated relative error 为 `0.141618%`。

历史 global peak-Q `13.99%` 继续作为 known limitation 保留，并明确不是有效的
smooth Richardson error bound。

## 作用域

D3A-RC1 只冻结 single Branch、fully wet、forward、strictly subcritical、`Fr<=0.8`、
正有效 Manning、显式下降床高、连续渐变非同 tabulated Profiles、一个
completed-interface Gate 和一个 external Q-H/Q-efficiency Pump 的受限能力。

它不证明真实工程率定、一般河网、湿干、倒流、internal Pump、多闸多泵、第三方模型
等价或生产水利决策能力。

FIX1/FIX1A readiness 与 validation 文档保留当时的独立审查状态，是发布前历史证据；
本文件是合并、main CI 与 tag 完成后的当前发布事实。
