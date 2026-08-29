# HYDRO-MODEL-02-D3A-RC1-FIX1 Audit

- 日期：2026-08-30
- 分支：`feature/HYDRO-MODEL-02-D3A-engineering-single-river`
- PR：[#12](https://github.com/zj1310426307-stack/dayu-tiangong/pull/12)，保持 OPEN / NOT MERGED
- FIX1 base：`3570d39141fbb7095ee2c7aaedabe963ea06d0d6`
- 运行前审计：`d8984c4`
- 首个实现提交：`e5a274b81b430fb8897b7b2603fb02e375741ea8`
- 方案 SHA-256：`33ca24dbbcb5f0366812f0cbdfcd50cb4007e3ae9e7445f2a80dec02b428d23e`

## 审计结论

pre-FIX1 的 60/70/80 证据不能证明严格 FINAL 空间收敛：加密比小于 1.5，Pump
和 monitor 的物理位置随网格变化，Gate event 的 `5 s` locator tolerance 又被当成
空间误差门。旧 artifact 保留且标为 `superseded-pre-FIX1`，不得用于发布放行。

FIX1 在任何新结果产生前冻结 18/54/162 odd3 网格，三层 Gate/Pump/monitor 位置
误差均为 0 m。独立 v2 证据计算观测阶、Richardson 极限和 fine estimated error，
并把 threshold event 的空间误差与 locator tolerance 分开。发布收集器只接受 v2、
四层 PASS 且全部 completion gates 为 true 的 artifact。

## 受保护范围

本轮没有修改 `model/`、`backend/`、`frontend/`、数据库迁移、OpenAPI 或生成客户端。
因此没有改变 Saint-Venant/HLL/SSP-RK2、Manning、bed source、non-prismatic
flux/source、Gate、Pump Q-H/Q-η、runtime envelope、friction predictor 或 D2 任务
平台。变更仅涉及 reference/test、CI evidence collector、checked artifact 和文档。

## 位置与网格证据

| level | cells | ratio | Gate error | Pump error | monitor error |
| --- | ---: | ---: | ---: | ---: | ---: |
| coarse | 18 | — | 0 m | 0 m | 0 m |
| medium | 54 | 3 | 0 m | 0 m | 0 m |
| fine | 162 | 3 | 0 m | 0 m | 0 m |

三个 mesh hashes 与完整坐标见
[grid-family](../model/HYDRO-MODEL-02-D3A-RC1-FIX1-grid-family.md)。

## 初步空间证据

| metric | `|M-C|` | `|F-M|` | observed p | trend |
| --- | ---: | ---: | ---: | --- |
| Gate downstream peak H | 0.008634791 m | 0.002304135 m | 1.202512 | PASS |
| Pump source peak H | 0.002638238 m | 0.000587774 m | 1.366746 | PASS |
| peak Q | 0.023422485 m3/s | 0.016803505 m3/s | 0.302299 | PASS（低于 0.7 偏好） |
| Gate volume | 88.220475 m3 | 22.039788 m3 | 1.262492 | PASS |
| Pump volume | 0.223425 m3 | 0.045365 m3 | 1.451225 | PASS |
| Pump energy | 0.001184277 kWh | 0.000254015 kWh | 1.401308 | PASS |
| Gate open event | 78.834888 s | 16.505203 s | 1.423323 | PASS（non-smooth empirical） |

全部硬门要求有限正阶并满足。`peak Q` 的 `p=0.302299` 未达到文档的 `>=0.7`
偏好值，因此不美化为高阶结果；其 fine estimated relative error 约 `13.99%`，在
artifact 和收敛报告中显式披露。FIX1 不因该结果更换网格。

## Git/发布边界

- PR #12 必须保持 OPEN；
- 不合并，不创建 D3A tag，不创建或启动 D3B；
- `D3A scientific validation` 与 `D3A shipping science` check 名称保持不变，避免
  破坏 main 已有第 11 项 required context；
- 只有本地、Python 3.11 Hosted、Python 3.12 shipping、D1/D2、Frontend/OpenAPI
  与最终 PR head 全部通过后，才能把 FIX1 标记为 PASS。

运行前冻结记录见 [baseline audit](./HYDRO-MODEL-02-D3A-RC1-FIX1-baseline-audit.md)。

## 本地验收

实际提交 SHA `e5a274b81b430fb8897b7b2603fb02e375741ea8` 的不可变 Python 3.12.13
镜像完成四层长测：`7 passed / 0 failed / 0 skipped`，JUnit time `1277.166 s`。
v2 artifact SHA-256 为
`90fb93102d46604b37751b4f3d3b1fdeb99d9333512d80748739355e10c13f0a`。

| local gate | result |
| --- | --- |
| FIX1 shipping science | 7 passed，全部 completion gates true |
| MODEL02（排除独立长测） | 375 passed |
| D2/native-v4（无外部服务） | 152 passed / 33 environment-gated skipped |
| legacy/D1 | 26 passed |
| OpenAPI generated client | 重新生成后 0 drift |
| frontend | typecheck 与 production build PASS |

旧 v1 artifact 已作为负例输入新 collector，按预期以
`FIX1 FINAL convergence artifact is not a four-level v2 PASS` 拒绝。

## Hosted 审计

Evidence head `d0aa74860471acfeb92a6cccaae5385059702cd9` 的 push/PR model02
`33272555233 / 33272557735` 和 hydraulic-platform
`33272555234 / 33272557769` 全部 SUCCESS。精确 required context
`D3A shipping science` 未改名，main 保护保持 `strict=true` 且原 11 项全部保留。

push shipping artifact 使用精确 evidence head、CPython 3.12.14，49/49 tests；PR
artifact 使用 GitHub merge ref，两者 schema/status/gates/grid hashes 与科学值一致。
下载结果证明 checked artifact 与 push artifact 除机器相关 `runtime_seconds` 外逐字段
一致。

结论：`FIX1 GATES PASS / MERGE READY FOR INDEPENDENT REVIEW`。该结论不授权合并
PR #12、不授权 D3A tag、不授权创建或启动 D3B。
