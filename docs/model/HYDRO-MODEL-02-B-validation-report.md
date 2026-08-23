# HYDRO-MODEL-02-B/B2 验证报告

验证日期：2026-08-20
验证对象：`feature/HYDRO-MODEL-02-B2-slope-boundary-hardening`
本轮基线提交：`048c31d`
实现提交：`48abdab`

## 1. 测试分层

本报告把软件回归、MVP 行为和限定科学门分开计数。`skip` 不计入通过数。

| 范围 | 结果 | 说明 |
|---|---:|---|
| `tests/model02` | 165 passed | 新数值核心、合同、示例、Benchmark、阈值控制与 B2 科学门 |
| `tests` | 330 passed, 1 skipped | 仓库根测试，包含 MODEL-02 |
| `backend/tests` | 143 passed, 70 skipped | 后端回归；本阶段未改 API/DB |
| 不重叠总计 | 473 passed, 71 skipped | 0 failed / 0 xfailed |

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
- v1 继续拒绝非棱柱 Profile；v2 非棱柱策略只接受 A/T/P/I1 确有差异的全湿 lake-at-rest，移动流、湿干、结构和混搭 policy 均被拒绝。
- `boundary_spatial_support=nearest-section-cell-face-v1` 是 v2 必填策略，并进入 policy hash 和结果诊断；不把节点身份当成已有端点测量断面。
- 绝对水位相等采用固定 `1e-12 m` 绝对容差，不随百万米级垂直 datum 放大；API 与 core 均有变形反例。
- 调用方在求解过程中修改原始 dict 时，结果仍对应运行前独立快照及 hash。
- 实际 Profile points 变化会改变 mesh hash，即使调用方伪造相同 `profile_hash`。
- v4-lite 传入 legacy overrides、cancel 或 progress callback 时明确拒绝，不静默忽略。
- 固定结构物输入仍产生原有 JSON 形状；阈值输入才增加 typed control events。
- 阈值动作只在初始或已接受状态原子提交；RK stage 和失败重试只读既有命令。
- v1 结果拒绝显式 `solver_policy_hash:null`，普通 `model_dump` 与 `to_dict` 都不泄漏 v2-only 字段。

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

## 5. B2 科学加固证据

| 门 | 结果 | 关键数值 | 冻结身份 |
|---|---|---|---|
| Case 002 v4 坡床 | PASS（严格参考子集） | Q/depth 最大误差 0；balance `2.6749844e-17`；CFL `0.21924477`；60 steps/0 retry | input `c801df9b...b1d24`；mesh `285ff28c...5dae0`；policy `b5725ce8...a4185` |
| 亚临界特征边界 | PASS（限定） | 矩形解析 R±；非矩形 non-matching Q/H 用独立 100,000 子区间 Simpson Φ，以 `2e-8` 绝对容差核对 | algorithm `riemann-invariant-phi-gl8-h2-bisection-positive-flow-physical-trace-v1` |
| 非棱柱静水 | PASS（严格静水子集） | max stage drift 0；max |Q| `2.29e-15 m3/s`；balance 0；30 steps/0 retry | input `0cf13e30...2cad0`；mesh `642f4253...45a2`；policy `abd28072...214eb` |

完整 64 位 hash 由自动测试冻结；表中缩写只用于阅读。非棱柱旧算子反例仍保留，证明“水量平衡 pass”不能替代静水科学门。

## 6. 未通过/未运行

| 项目 | 状态 | 原因 |
|---|---|---|
| Case 002 默认 standard / 一般移动稳态 | PARTIAL / NO-GO | standard 仍约 3.71%；reference 只接受严格解析子集 |
| 一般非棱柱移动流/湿干 | BLOCKED | 当前 public policy 只允许 lake-at-rest；无 manufactured solution 收敛证据 |
| 端节点连续坡床边界 | NOT IMPLEMENTED | 当前明确使用最近 Section cell face；Case 002 末端空间差 25 m |
| 湿干溃坝/收敛阶 | NOT RUN | 无解析/高分辨率冻结参考 |
| Gate 强动量/能头耦合 | NOT IMPLEMENTED | 当前只有 mass flux |
| Pump Q-H/Q-η/内部转输 | NOT IMPLEMENTED | 当前只有定流量 external sink |
| 连续阈值 crossing 定位 | NOT IMPLEMENTED | 当前是接受步离散一次性 latch，并强制输出诊断 |
| HTTP/Celery/DB 持久化 | NOT RUN | direct-engine-only |
| HEC-RAS/MIKE11 结果级对比 | NOT RUN | 无冻结外部参考包 |
| 真实工程率定/浏览器闭环 | NOT RUN | 不在该 MVP 证据范围 |

## 7. 验收判定

- 代码与合成软件 MVP：`GO`。
- MODEL-02-B/B2 冻结场景与三项科学加固：`GO`；均只在各自显式严格子集通过。
- 实际工程/生产 Saint-Venant：`NO-GO`。

## 8. 2026-08-23 当前基线复核

- `tests/model02`：`267 passed`；
- `tests + backend/tests`：`575 passed / 71 skipped / 0 failed`；
- 71 项 skip 仍为 PostGIS、GeoServer、GDAL、QGIS 等外部环境门；
- 精确恒等 hydrostatic reconstruction 快路径专项：`PASS`；
- 100 个表格化 V 形断面、24 h 静水吞吐：三个全新进程分别 `41.3694 s`、`36.7450 s`、`18.5833 s`，最坏值仍 `<60 s`；6,120 steps、0 retry、balance 0；
- 24 h 动态洪峰吞吐：`NO-GO`，本轮两种动态探针均超过 60 s 后终止，未伪造完成结果。

性能结论只适用于 `benchmark_100_sections.py` 冻结的全湿非规则静水 smoke case，不能外推到一般动态边界、Manning 长时程、Gate/Pump 或生产容量。
