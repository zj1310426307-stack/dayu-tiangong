# HYDRO-MODEL-02-D3A-RC1 基线审计

- 审计日期：2026-08-30
- RC1 base SHA：`0306e7b0388b4debffb6c8c66adfd962e99c0553`
- 分支：`feature/HYDRO-MODEL-02-D3A-engineering-single-river`
- PR：[#12](https://github.com/zj1310426307-stack/dayu-tiangong/pull/12)
- PR 状态：`OPEN / MERGEABLE / NOT MERGED`
- base：`main`
- D3A base：`a40a9f8a5728d6d03c127409491a38321540ac99`

## 1. 独立审查判定

2026-08-29 的 D3A 初始候选曾记录 `PASS / PR REVIEW READY`。RC1 独立审查没有否定 M1/M2、S1/S2/S3、P1/P2/P3 或 D1/D2 平台回归，但发现三项发布级证据未闭合，因此当前发布决策改为：

```text
D3A initial candidate: historical PASS claim
Independent review: CHANGES REQUESTED
D3A-RC1: PENDING
PR #12: NO-GO until RC1 closure
```

缺口为运行期 fully-wet/forward/Fr<=0.8 动态包络、FINAL 空间/时间收敛、实际 Python 3.12 shipping image science suite；另有 Manning friction dt predictor 性能改进。

## 2. 本地基线

- `python -m compileall -q model backend/app`：PASS；既有源码目录中的字节码缓存不可写，因此将 `PYTHONPYCACHEPREFIX` 定向到项目 `99_临时文件/d3a-rc1-pycache`，未删除或改写既有缓存。
- `tests/model02 tests/model_engine`：`519 passed, 35 skipped`，3 条 Alembic 配置弃用警告，无失败。
- 旧 D3A science、D1 frozen、D2 platform/fault/shipping、Frontend/OpenAPI 在最终 D3A head 上均已通过。

## 3. FINAL 基线

冻结的 20-section、6 h D3A-3 native-v4 案例实测：

| 指标 | RC1 前基线 |
| --- | ---: |
| 运行时间（本次本机观测） | 23.7647 s |
| 接受步 | 666 |
| 总 retry | 586 |
| friction retry | 586 |
| retry / accepted | 0.87988 |
| 最小接受步长 | 3.75 s |
| 最大 CFL | 0.689672676 |
| 最大摩阻数 | 0.0974940005 |
| Gate open | 2966.25 s |
| Pump start | 4020 s |
| Gate volume | 3882.879156 m3 |
| Pump volume | 54.4935866 m3 |
| Pump energy | 0.324649864 kWh |
| 相对水量误差 | 1.60389e-15 |
| Gate 最大能量残差 | 9.61186e-11 m |
| Pump 最大扬程残差 | 9.45835e-11 m |

该结果只有单一主要网格/时间策略，不能作为 FINAL convergence closure。

## 4. Hosted 基线

RC1 base SHA 的最新 PR 运行：

- `model02` run [`33254519748`](https://github.com/zj1310426307-stack/dayu-tiangong/actions/runs/33254519748)：SUCCESS；
- `hydraulic-platform` run [`33254519787`](https://github.com/zj1310426307-stack/dayu-tiangong/actions/runs/33254519787)：SUCCESS；
- 已有 `D3A scientific validation` 使用 Ubuntu Python 3.11；
- 尚无独立 `D3A shipping science` Python 3.12 check context。

## 5. RC1 冻结边界

不新增水动力能力，不修改 D1 时间步行为，不修改迁移 `0023`，不新建 PR，不合并 PR #12，不创建 D3A tag。RC1 仅关闭动态科学包络、FINAL 收敛、摩阻时间步预测和 Python 3.12 science 发布门。
