# HYDRO-MODEL-02-B 验证报告

验证日期：2026-08-20
验证对象：`feature/HYDRO-MODEL-02-B-saint-venant-mvp` 提交前快照
基线提交：`0109245`

## 1. 测试分层

本报告把软件回归、MVP 行为和科学候选门分开计数。`skip` 和 `xfail` 不计入通过数。

| 范围 | 结果 | 说明 |
|---|---:|---|
| `tests/model02` | 73 passed, 1 xfailed | 新数值核心、合同、示例、Benchmark |
| `tests` | 238 passed, 1 skipped, 1 xfailed | 仓库根测试，包含 MODEL-02 |
| `backend/tests` | 143 passed, 70 skipped | 后端回归；本阶段未改 API/DB |
| 不重叠总计 | 381 passed, 71 skipped, 1 xfailed | 0 failed |

精确命令：

```powershell
backend\.venv\Scripts\python.exe -m pytest -c backend\pyproject.toml -p no:cacheprovider tests\model02 -ra
backend\.venv\Scripts\python.exe -m pytest -c backend\pyproject.toml -p no:cacheprovider tests -ra
backend\.venv\Scripts\python.exe -m pytest -c backend\pyproject.toml -p no:cacheprovider backend\tests -ra
```

71 个 skip 为显式外部环境门：70 个后端 PostGIS/GeoServer/GDAL/QGIS/迁移环境门，1 个仓库根 `qgis_process` 门。本阶段没有把它们记为通过。

## 2. 合同与路由门

已验证：

- v4-lite 精确进入新 HLL 路由，不调用 `adapt_v3_to_v2`。
- v1/v2/v3 代表性输入仍返回原结果 schema。
- 未知 schema、旧镜像字段、多余字段、数字字符串、NaN/Inf 均关闭失败。
- 身份重复/错配、非相邻 Gate face、未知 Pump section、不完整边界和外推策略均被拒绝。
- 上下游不得复用同一 `public.boundary_condition` 身份。
- 非棱柱 Profile 和可产生多个分离湿区的 Profile 在 v4-lite 输入门被拒绝。
- 调用方在求解过程中修改原始 dict 时，结果仍对应运行前独立快照及 hash。
- 实际 Profile points 变化会改变 mesh hash，即使调用方伪造相同 `profile_hash`。
- v4-lite 传入 legacy overrides、cancel 或 progress callback 时明确拒绝，不静默忽略。

## 3. 数值质量门

所有新场景共用以下门禁：

- A、Q、水深、流速、dt、CFL 必须有限；
- A 和水深不得为负，干 cell 不得携带非零 Q；
- 输出时间和接受步时间必须严格递增并落在 end time；
- `maximum_cfl <= configured cfl`；
- SSP-RK2 接受步每步必须正好 2 个 stage；
- 水量账用动态库容差、上/下边界体积和 Pump 外排体积独立复算；
- 归一化水量误差达到或超过输入 tolerance 时不生成 `pass` 结果。

## 4. 可运行示例

```powershell
$env:PYTHONPATH='backend;.'
backend\.venv\Scripts\python.exe examples\hydraulic\saint-venant-mvp\run_demo.py
```

当前冻结输出：

| 指标 | 值 |
|---|---:|
| input/result schema | `dayu.model-input.v4-lite` / `dayu.hydraulic-result.mvp` |
| 断面/Gate/Pump | 3 / 1 / 1 |
| 输出时间 | 0, 60, 120 s |
| maximum CFL | 0.1485889384 |
| minimum dt | 10 s |
| retry | 0 |
| relative water-balance error | 1.3642420527e-16 |
| balance | pass |
| input snapshot hash | `b6502bb6e4c043e0fcfef96217057a09fe4e71c82b912f462a68725b3fb32d27` |
| mesh hash | `e0647e54e6444e641ad30bfe0eadae25471e4b666883677ade04f6419a15e551` |

`tests/model02/test_mvp_example.py` 现场重跑该输入并核对两个 hash、时间轴、诊断和关键数值，防止示例摘要漂移。

## 5. 未通过/未运行

| 项目 | 状态 | 原因 |
|---|---|---|
| Case 002 0.1% Manning 候选线 | XFAIL / NO-GO | 流量误差约 3.71% |
| 非棱柱静水 | BLOCKED | 几何源项未实现，输入已 fail-closed |
| 湿干溃坝/收敛阶 | NOT RUN | 无解析/高分辨率冻结参考 |
| Gate 强动量/能头耦合 | NOT IMPLEMENTED | 当前只有 mass flux |
| Pump Q-H/Q-η/内部转输 | NOT IMPLEMENTED | 当前只有定流量 external sink |
| 自动阈值调度 | NOT IMPLEMENTED | 本阶段不猜测控制合同 |
| HTTP/Celery/DB 持久化 | NOT RUN | direct-engine-only |
| HEC-RAS/MIKE11 结果级对比 | NOT RUN | 无冻结外部参考包 |
| 真实工程率定/浏览器闭环 | NOT RUN | 不在该 MVP 证据范围 |

## 6. 验收判定

- 代码与合成软件 MVP：`GO`。
- MODEL-02-B 任务书的科学 Benchmark 全绿：`PARTIAL`。
- 实际工程/生产 Saint-Venant：`NO-GO`。
