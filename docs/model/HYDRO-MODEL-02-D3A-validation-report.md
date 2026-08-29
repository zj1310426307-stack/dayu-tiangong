# HYDRO-MODEL-02-D3A 验证总报告

- 日期：2026-08-29
- 分支：`feature/HYDRO-MODEL-02-D3A-engineering-single-river`
- D2 main merge SHA / D3A base：`a40a9f8a5728d6d03c127409491a38321540ac99`
- D2 annotated tag：`hydro-model-02-d2-rc2`，解引用后指向上述 main merge commit
- FINAL PR：[#12](https://github.com/zj1310426307-stack/dayu-tiangong/pull/12)，`NOT MERGED`
- 总结论：`HYDRO-MODEL-02-D3A PASS`

## Capability registry

D1 的冻结 capability 语义未修改。新增并独立版本化：

- D3A-1 `single-branch-gate-pump-positive-manning-v1`；
- D3A-2 `single-branch-gate-pump-manning-slope-v1`；
- D3A-3 `single-branch-gate-pump-engineering-profile-v1`。

Readiness、runtime adapter、validation policy、结果 provenance、OpenAPI 和前端 selector 均由 capability ID 驱动；没有新增旁路 v4-lite 公共合同。

## D3A-1：Manning

- 摩阻积分使用现有有限体积路径的 semi-implicit per-SSP-stage 算子；
- M1 解析衰减在 30/15/7.5 s 步长上达到机器精度；
- M2 平床 standard-step 的 12/24/48 网格 H L1 误差为 `8.981e-3 / 4.533e-3 / 2.298e-3 m`，严格下降；
- 正糙率 Gate/Pump 6 h 案例相对水量误差 `6.372e-16`，结构能量/扬程残差均不大于 `1e-10 m`。

## D3A-2：显式床坡

- `bed_elevation_m` 及其来源元数据是唯一河床权威，禁止由 Profile 点自动回填；
- S1 斜床静水的 H/Q 残差不大于 `1e-10`，相对水量误差不大于 `1e-12`；
- S2 正常水深为 `1.7729062821012627 m`，数值水深/流量误差不大于 `1e-9`；
- S3 的 12/24/48 网格 H L1 误差为 `8.9159e-3 / 4.4399e-3 / 2.2038e-3 m`，空间与 CFL 加密均 PASS；
- 斜床 Gate/Pump 6 h 案例相对水量误差 `9.06e-16`，最大摩阻数 `0.0980445660`。

## D3A-3：连续非同断面

- 几何源为 `hydraulic-function-linear-face-v1`，相邻 A/T/P/I1 变化受 0.25 连续性门约束；
- P1 非棱柱斜床静水 H/Q 残差不大于 `1e-10`；
- P2 的 25/50/100 网格 H L1 相对误差为 `1.7180e-5 / 8.6457e-6 / 4.3352e-6`，观测阶约 1；
- P3 的 20/40/80 网格 H L1 误差为 `2.9361e-3 / 1.4728e-3 / 7.4882e-4 m`，Q L1 误差为 `2.6739e-2 / 1.4173e-2 / 7.3957e-3 m³/s`，观测阶均不低于 0.8；
- 不同 Profile Gate/Pump 与 6 h FINAL 综合案例 PASS。

## 回归与 Hosted

- 本地 `tests/model02 tests/model_engine`：`519 passed, 35 skipped`；
- legacy hydraulic：`26 passed`；
- frontend typecheck / production build：PASS；
- OpenAPI 生成客户端漂移门：PASS；
- Hosted `model02` run [`33254053757`](https://github.com/zj1310426307-stack/dayu-tiangong/actions/runs/33254053757)：SUCCESS；
- Hosted `hydraulic-platform` run [`33254053772`](https://github.com/zj1310426307-stack/dayu-tiangong/actions/runs/33254053772)：SUCCESS；
- D1 frozen、PostGIS migration、Worker integration、D2 fault recovery、RuntimeBuildIdentity 和 immutable Python 3.12 shipping runtime 全部 PASS。

## 判定

大禹·天工 native 1D Saint-Venant 模型已在单 Branch、全湿、正向严格亚临界边界内，通过独立科学门扩展到有效 Manning 摩阻、显式非零床坡和连续变化的非同 tabulated Profiles，并在一个 completed-interface Gate 与一个 external Q-H/Q-η Pump 综合 synthetic benchmark 中完成质量、收敛、水量和构建来源验证。

能力限制以 [D3A known limitations](./HYDRO-MODEL-02-D3A-known-limitations.md) 为准。
