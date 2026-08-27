# HYDRO-MODEL-02-D1-RC1 CI 验证报告

- 日期：2026-08-28
- 测试候选：`e85c95c4bad675eb404b439f696f53dccb7ac47a`
- 状态：本地与 GitHub hosted matrix 均 PASS

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

| 项目 | 结果 |
|---|---|
| Run | [`33102252587`](https://github.com/zj1310426307-stack/dayu-tiangong/actions/runs/33102252587) |
| Head | `e85c95c4bad675eb404b439f696f53dccb7ac47a` |
| Ubuntu MODEL-02 | 355 passed，artifact `model02-ubuntu-py311` |
| Windows MODEL-02 | 355 passed，artifact `model02-windows-py311` |
| Legacy hydraulic | 26 passed，artifact `legacy-hydraulic-ubuntu-py311` |
| Frontend contract | Node 24 typecheck/build PASS |

两个 MODEL-02 artifacts 的 canonical byte count 均为 13901，五类 hash 完全一致：

```text
authoritative_input_hash  96eb4e4d28bc05c865c3f5e8f24e3b0169b4d29f95bfe515e22e72237bf2bec1
runtime_projection_hash   76123a26e539fbf5775be3ea8feb9570dc7e864a3c475036e383ae8ea8230312
mesh_hash                 056f3bc492bf64a12ecb9c1be66d0f2935ff941214c8c0e8c318db90d433f4ea
solver_policy_hash        c788c33c40f800fc469af1260a4a94150d16623a800c0083b56e15ad9c032618
validation_policy_hash    bb70c5a3af5942d16c43ec8c7f490333653e7efa2051d2e734c66aa8d3f17795
```

首次失败和 RC1 通过历史均已保留。D1 RC1 判定 PASS；`main` 仍未合并。
