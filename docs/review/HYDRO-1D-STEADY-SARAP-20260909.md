# Standard 1D 恒定流 / SARAP 证据记录

## 范围

Standard 1D 页面新增 `计算类型`。选择“恒定流（稳态）”后，任务冻结快照写入
`calculation_mode=steady` 与 `mascaret_kernel=sarap`，由 MASCARET v9.1.1 的
SARAP（Noyau 1）执行；默认的非恒定流任务仍使用原有内核选择逻辑。

页面同时提供“高水位处理”。选择“全归槽（竖直岸壁）”时，Mapper 以冻结初始
水位包络和水位边界的最大值加 1.0 m 数值余高，在每个有效断面左右端点生成同站距
竖直墙。该墙只存在于任务快照，可删除并重建；数据库 Raw Station、Raw Elevation、
Marker 和已批准 Profile 均不修改。快照在 `vertical_bank_extension` 中记录来源、
顶高程、余高和原始数据不可变声明。

## 结果语义

结果解析器对恒定流任务增加端点控制诊断：对恒定上游流量和恒定下游水位，报告
期望值、末时刻值、最大偏差、容差和 `satisfied`。如果某边界在超临界流态下失去
控制能力，任务仍保留真实 MASCARET 结果，但结果页显示校核警告，不把未实现的
边界条件伪装为已满足。

SARAP 会先在 `t=0` 写稳态解，再从前一计算步开始应用输出存储间隔，因此原生时标
可能为 `0, 50, 110, ...`。仅当任务明确为 SARAP 稳态、全部边界值恒定、原生输出
数量完整时，Parser 才按顺序映射为请求的 `0, 60, 120, ...` 展示轴，并记录
`time_axis_mode=sarap-steady-normalized`；其他不完整或非恒定情形继续失败关闭。

## 高明河当前工况

使用已批准数据版本 `高明河2`、方案 `P=5%2`、上游流量 405.43 m³/s、下游水位
29.721 m 的复现工作区时，官方 SARAP 进程返回成功，沿程流量保持 405.43 m³/s。
末端实际水位为 27.848 m；该断面 Froude 数约 1.49，说明给定下游水位低于此
流量和有效断面宽度的临界控制要求。该组合应作为“计算完成、边界需复核”处理，
不作为率定或边界满足的证据。

## 验证

- MASCARET Adapter/Parser/Task contract：25 passed。
- 全归槽派生竖墙与 SARAP 稳态时标回归加入后，上述聚焦测试：27 passed。
- `tests/hydraulic_1d`：173 passed，2 skipped；4 个 D-Flow/NetCDF 测试仅因当前
  Windows 沙箱无法写入既有 `outputs/dflow-native-io` 而失败，非本次改动回归。
- 前端 TypeScript 直接检查（关闭增量缓存）通过；Vite 构建在当前沙箱写入
  `node_modules/.vite-temp` 时被 Windows 权限拒绝，需在 Docker/开发机容器内重建。

## 风险与后续

该案例仍是未率定方案计算。若工程要求严格满足下游水位，需要复核断面有效宽度、
边界所在断面和流态控制条件，再重新冻结数据版本；不得通过覆盖结果值消除警告。
