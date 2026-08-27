# HYDRO-MODEL-02-D1-RC1 CI 验证报告

- 日期：2026-08-28
- 候选：`6175ab2`
- 状态：本地 PASS；GitHub hosted matrix 待运行

## 首次 hosted 运行

| 项目 | 结果 |
|---|---|
| Run | `33097599382` |
| Head | `9002f10b584ac8c95439e9e161027897f7e3d803` |
| Ubuntu hydraulic-model | FAIL：2 个跨平台合同问题 |
| Frontend contract | PASS |
| Legacy hydraulic | SKIPPED：与失败测试位于同一 job |

首次失败记录永久保留，不因 RC1 后续通过而覆盖。

## RC1 工作流

| Job | 平台 | 证据 |
|---|---|---|
| `MODEL02 Ubuntu Python 3.11` | ubuntu-latest | diagnostic JSON、JUnit、summary |
| `MODEL02 Windows Python 3.11` | windows-latest | diagnostic JSON、JUnit、summary |
| `Legacy hydraulic` | ubuntu-latest | JUnit、summary |
| `Frontend contract` | ubuntu-latest / Node 24 | typecheck、build |

MODEL-02 matrix 使用 `fail-fast=false`；legacy 和 frontend 不再被 MODEL-02 失败短路。测试无论成功或失败都先上传 artifacts，再由独立 enforce step 恢复 job 失败状态。

## 本地证据

- Windows 11 / Python 3.12.13 / Node 24.17；
- compileall：PASS；
- MODEL-02：355 passed；
- 根目录：521 passed、1 skipped；
- backend 聚合：680 passed、71 skipped；
- frontend typecheck/build：PASS；
- fixture canonical hash：`96eb4e4d28bc05c865c3f5e8f24e3b0169b4d29f95bfe515e22e72237bf2bec1`；
- D1 benchmark：PASS，物理结果未漂移。

本机唯一 root skip 为缺少 `qgis_process`；backend skips 属于未启动 PostGIS/TimescaleDB 或未安装 GDAL/QGIS 的既有外部门。

## Hosted RC1 结果

待候选推送后补录 run id、各 job conclusion、artifact 名与 Windows/Linux hash 对比。任何 required job 未通过时，RC1 结论保持 `FAIL/BLOCKED`，D2 为 `NO-GO`。
