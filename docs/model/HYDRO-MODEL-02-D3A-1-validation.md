# HYDRO-MODEL-02-D3A-1 验证报告

- 日期：2026-08-29
- 本地结论：`PASS`
- Hosted 结论：`PASS`
- 总结论：`D3A-1 PASS`，允许按顺序进入 D3A-2

## 1. M1：friction-only 解析衰减

固定 `A=25 m²`、矩形宽 `10 m`、`Q0=20 m³/s`、`n=0.035`、时长 `900 s`。
独立解析式为 `Q(t)=Q0/(1+K Q0 t)`，终值 `3.7184119530084923 m³/s`。

| dt (s) | 数值终值 (m³/s) | 绝对误差 (m³/s) |
|---:|---:|---:|
| 30.0 | 3.7184119530084923 | 0.0000000000000000 |
| 15.0 | 3.7184119530084923 | 0.0000000000000000 |
| 7.5 | 3.7184119530084920 | 4.44e-16 |

三组时间步均达到机器精度；全过程 `Q` 单调下降、不变号，面积为正。`n=0` 与
`Q=0` 的精确退化也分别通过。

## 2. M2：平床恒定流独立 standard-step 对照

测试为长 `1200 m`、宽 `10 m` 的矩形棱柱河段，平床、`n=0.03`、上游恒定
`Q=20 m³/s`、下游水位 `2.5 m`、全湿亚临界。参考解由测试专用、仅依赖 Python
标准库的逆流 standard-step 能量方程求解；参考模块不导入 production solver。

| Cells | CFL | L1 H (m) | L∞ H (m) | L1 Q (m³/s) | 相对水量误差 | 最大摩阻数 | 能量损失 (m) |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 12 | 0.6 | 8.981e-3 | 1.640e-2 | 6.551e-1 | 2.864e-16 | 3.664e-2 | 2.615e-1 |
| 24 | 0.6 | 4.533e-3 | 8.438e-3 | 3.317e-1 | 1.143e-16 | 1.816e-2 | 2.779e-1 |
| 48 | 0.6 | 2.298e-3 | 4.279e-3 | 1.659e-1 | 1.712e-16 | 9.042e-3 | 2.863e-1 |
| 48 | 0.3 | 1.768e-3 | 4.262e-3 | 1.636e-1 | 5.137e-16 | 4.512e-3 | 2.854e-1 |

`dx/dx/2/dx/4` 的水位 L1 误差严格下降；48-cell 半 CFL 没有劣化误差，最大摩阻数
约减半。参考解与生产解都显示沿流向机械能下降，水量门通过。

## 3. 摩阻 retry 证据

专项高糙率案例将门设为 `mu <= 0.01`，初始 trial 超限后必须缩步，并断言：

- `friction_retry_count > 0`；
- 每个 accepted step 的摩阻数都不超过门限；
- 被丢弃 trial 不进入最终最大值与结果证据；
- 总 retry 数不小于摩阻 retry 数。

## 4. 六小时 Gate/Pump 正糙率案例

D3A 案例从冻结 D1 案例复制，只把所有断面的 `n` 从 `0` 改为 `0.025`，并更换
显式 capability/policy provenance；平床、相同 Profile、Gate/Pump、边界和控制类型
保持不变。

| 证据 | 实测值 | 门限/判定 |
|---|---:|---:|
| Pump start | 3000 s | 因果顺序 PASS |
| Gate open | 3015 s | 因果顺序 PASS |
| 最大摩阻数 | 0.0672134 | `<= 0.1` |
| 摩阻 retry | 0 | 可解释；全部 trial 在门内 |
| 相对水量误差 | 6.372e-16 | `<= 1e-10` |
| Gate 最大能量残差 | 9.982e-11 | `<= 1e-10` |
| Pump 最大扬程残差 | 9.973e-11 m | `<= 1e-10 m` |
| Pump 外排体积 | 85.6767 m³ | 正值 |
| Pump 输入能量 | 0.476218 kWh | 正值 |

所有 Section 的 H/Q/V 均有限，体积严格为正。Gate strong interface 与 Pump
stage operating point 均由 accepted-stage evidence 复核。

## 5. 回归与平台合同

- `tests/model02`：`361 passed`；
- `tests/model_engine`：`138 passed, 35 skipped`；skip 是外部 PostGIS/服务门，不计作
  科学通过；
- OpenAPI 生成结果与提交客户端一致；
- frontend typecheck 与 production build：PASS；
- D1 的 `n=0` 路由仍显式存在，D3A-1 不覆盖或自动替换 D1；
- D3A-2 与 D3A-3 继续在 capability catalog 中保持 `blocked`。

## 6. Hosted 封口

候选 `13bb729` 的 `model02` run `33250092402` 首次全绿；同一候选的
`hydraulic-platform` run `33250092381` 暴露真实 PostGIS/Redis/Shipping 测试夹具仍按
旧合同创建 v4 任务、缺少显式 D1 capability。没有放宽新合同；修复提交 `19f5da5`
将所有 D2 夹具显式固定回 D1。

修复后：

- `model02` run `33250290994`：SUCCESS；
- `hydraulic-platform` run `33250291019`：SUCCESS；
- 新增 `D3A scientific validation`、Ubuntu/Windows MODEL02、Legacy、Frontend、
  Backend v4、PostGIS migration、real Worker、D2 fault recovery、D1 regression、
  Python 3.12 shipping runtime 全部通过。

因此 M1、M2、空间/时间细化、正糙率 Gate/Pump、D1/D2 回归与 Hosted 门均已满足，
D3A-1 判定为 `PASS`。
