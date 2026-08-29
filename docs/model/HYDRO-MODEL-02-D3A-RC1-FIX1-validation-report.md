# HYDRO-MODEL-02-D3A-RC1-FIX1 Validation Report

- 日期：2026-08-30
- PR：[#12](https://github.com/zj1310426307-stack/dayu-tiangong/pull/12)，OPEN / NOT MERGED
- 本地结构对齐空间证据：PASS
- Python 3.12 shipping identity：PASS（CPython 3.12.13，CI build）
- 完整四层 shipping test：PASS
- Hosted Python 3.11 / Python 3.12：PASS（evidence head `d0aa74860471acfeb92a6cccaae5385059702cd9`）

## 已闭合门

| 门 | 结果 |
| --- | --- |
| 运行前固定 grid family | PASS，18/54/162，ratio 3/3，三个 frozen mesh hashes |
| Gate/Pump/monitor 位置 | PASS，各层 0 m error |
| 6 smooth metrics | PASS，差值下降且 p 有限正；peak Q p=0.302299 低于偏好值并已披露 |
| Gate threshold event | PASS，空间差下降；locator tolerance 与 spatial error 独立 |
| 旧 v1 artifact | `superseded-pre-FIX1 / historical-smoke-only` |
| v2 fail-closed collector | PASS，只接受四层、status pass、全部 completion gates true |
| 核心/平台/API 作用域 | PASS，无相关源文件变更 |

## 发布镜像身份

本地不可变镜像使用实际 Git SHA
`e5a274b81b430fb8897b7b2603fb02e375741ea8` 构建，运行诊断为：

| identity | value |
| --- | --- |
| Python | CPython 3.12.13 |
| build mode | `ci` / verified |
| Registry SHA-256 | `0920e124fa07c764d5086d3d4e2d6723d4f5abfed857a4bb37309eae553029a4` |
| Solver build ID | `dayu.solver-build.v1:38205d7b03a839dfeace058d83234d1201932fb75baa4e9f7df818b410dd3e7b` |

一次以错误完整 SHA 参数构建的本地镜像在运行科学门前即被核对发现并作废；所有后续
发布验证只使用上表实际 SHA 镜像。这是 build identity fail-closed 的预期应用。

## Hosted 证据

| event | model02 | hydraulic-platform |
| --- | --- | --- |
| push | `33272555233` SUCCESS | `33272555234` SUCCESS |
| pull_request | `33272557735` SUCCESS | `33272557769` SUCCESS |

Python 3.11 `D3A scientific validation` 与 Python 3.12 `D3A shipping science` 在 push
和 PR 两种事件均成功；Ubuntu/Windows MODEL02、Legacy、Frontend contract、D1、
D2 fault/shipping、PostGIS/Worker 与 Frontend OpenAPI 同时成功。

push shipping artifact：id `9721109268`，digest
`sha256:e1dabeca444cbda77fd9f0303c3ba46fa019d049cc8e1fe016817dfe43927791`，
CPython `3.12.14`，`ENGINE_COMMIT=d0aa74860471acfeb92a6cccaae5385059702cd9`，
49/49 tests。下载后 v2 artifact 除 `runtime_seconds` 外与 checked artifact 逐字段完全
一致，三个 grid hashes 与七个 completion gates 全部一致。

PR shipping artifact：id `9721041489`，digest
`sha256:00ce795fbd99584a781121a39dde3da5b8c0203397f5bc56aff5402260ec5610`，
使用 GitHub pull-request merge ref `92a81f5894551622d0a605828f7654f6f0a93c63`，49/49 tests。

## 本地完整结果

| suite | result |
| --- | --- |
| FIX1 Python 3.12 shipping | 7 passed / 0 failed / 0 skipped，1277.166 s |
| MODEL02 | 375 passed / 0 failed |
| D2/native-v4 contracts | 152 passed / 33 external-service skipped / 0 failed |
| legacy/D1 | 26 passed / 0 failed |
| OpenAPI | regenerated client 0 drift |
| frontend | typecheck + production build PASS |

时间细化 `accepted_maximum_dt_ratio=0.5`，七个 completion gates 全为 true。最坏
包络为 minimum depth `0.789331056 m`、minimum Q `-1.64083e-14 m3/s`、maximum
Fr `0.058066903`、maximum friction number `0.099703930`；最大水量相对误差
`5.34533e-16`，Gate/Pump 残差分别不大于 `9.99105e-11 / 9.99900e-11 m`。

正式 v2 artifact SHA-256：
`90fb93102d46604b37751b4f3d3b1fdeb99d9333512d80748739355e10c13f0a`。

FIX1 的实现/证据 head 已满足全部机器门。当前状态为
`FIX1 GATES PASS / MERGE READY FOR INDEPENDENT REVIEW`。PR #12 仍 OPEN / NOT
MERGED；本任务不创建 D3A tag，不创建或启动 D3B。
