# Standard 1D 恒定流 / SARAP 证据记录

## 范围

Standard 1D 页面新增 `计算类型`。选择“恒定流（稳态）”后，任务冻结快照写入
`calculation_mode=steady` 与 `mascaret_kernel=sarap`，由 MASCARET v9.1.1 的
SARAP（Noyau 1）执行；默认的非恒定流任务仍使用原有内核选择逻辑。

## 结果语义

结果解析器对恒定流任务增加端点控制诊断：对恒定上游流量和恒定下游水位，报告
期望值、末时刻值、最大偏差、容差和 `satisfied`。如果某边界在超临界流态下失去
控制能力，任务仍保留真实 MASCARET 结果，但结果页显示校核警告，不把未实现的
边界条件伪装为已满足。

## 高明河当前工况

使用已批准数据版本 `高明河2`、方案 `P=5%2`、上游流量 405.43 m³/s、下游水位
29.721 m 的复现工作区时，官方 SARAP 进程返回成功，沿程流量保持 405.43 m³/s。
末端实际水位为 27.848 m；该断面 Froude 数约 1.49，说明给定下游水位低于此
流量和有效断面宽度的临界控制要求。该组合应作为“计算完成、边界需复核”处理，
不作为率定或边界满足的证据。

## 验证

- MASCARET Adapter/Parser/Task contract：25 passed。
- `tests/hydraulic_1d`：173 passed，2 skipped；4 个 D-Flow/NetCDF 测试仅因当前
  Windows 沙箱无法写入既有 `outputs/dflow-native-io` 而失败，非本次改动回归。
- 前端 TypeScript 直接检查（关闭增量缓存）通过；Vite 构建在当前沙箱写入
  `node_modules/.vite-temp` 时被 Windows 权限拒绝，需在 Docker/开发机容器内重建。

## 风险与后续

该案例仍是未率定方案计算。若工程要求严格满足下游水位，需要复核断面有效宽度、
边界所在断面和流态控制条件，再重新冻结数据版本；不得通过覆盖结果值消除警告。
