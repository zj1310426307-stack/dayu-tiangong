# HYDRO-MODEL-02-C3b-J2 Junction 同步阶段推进审查

- 日期：2026-08-23
- 分支：`feature/HYDRO-MODEL-02-C3b-junction-stage`
- 父提交：`8237c15`
- 结论：受限 1-in/2-out 同步 SSP-RK2 与网络水量账 `GO`；一般河网、矢量动量和结构节点 `NO-GO`

## 冻结作用域

J2 只接受一个连通、无环、三 Branch、单 Junction 的分流拓扑：

```text
Q(t) -> incoming Branch -> Junction -> outgoing Branch 1 -> H1(t)
                                  \-> outgoing Branch 2 -> H2(t)
```

全部 Branch cell 必须全湿、正向、严格亚临界、零 Manning，且每条 Branch 内部为平床棱柱断面。不同 Branch 可以使用不同矩形或表格断面。外边界固定使用 `subcritical-characteristic-v1`；Gate、Pump 和任何结构运行状态均拒绝。

## SSP-RK2 接线

每个接受步执行：

```text
同步 U^n
  -> J1 solve at t^n
  -> 三 Branch 同步 Euler stage
  -> 全网中间态 CFL/作用域检查
  -> J1 solve at t^n + dt
  -> 三 Branch 同步 Euler stage
  -> U^(n+1) = 0.5 * (U^n + U_stage2)
```

Junction 的完成 trace 直接走现有特征边界的 physical-flux 路径 `F=(Q,Q²/A+gI1)`，不再次与端点 cell 做 HLL 混合。入流 Branch 使用节点 trace 作为 downstream face；两条出流 Branch 使用各自 trace 作为 upstream face。J1 的共同水位、质量和 `R+/R-` 特征相容语义保持不变。

## 状态与失败所有权

- `FiniteVolumeNetwork` 继续只拥有静态拓扑和 Branch mesh；
- 三个 `HydraulicState` 分别拥有 Branch 守恒量，但接受时间和 `SolverDiagnostics` 必须完全同步；
- Junction solution 是阶段证据，不回写成 cell 状态；
- 任一 Branch 的正性/CFL/作用域或任一 Junction solve 失败，整组三 Branch trial 一并丢弃，统一 `dt/=2`；
- `OneInTwoOutNetworkResult` 只保存输出快照、接受步和诊断，不能反向成为运行状态。

## 水量账

节点没有独立蓄量，内部转输不计入外部边界体积：

```text
Delta S = V_source - V_sink1 - V_sink2 + residual
```

每个接受步对两个 RK stage 的外部通量做梯形积分。另存节点质量残差体积 `Vj`，并检查离散恒等式：

```text
water_balance_residual + Vj ~= 0
```

这样既不会把 Junction 流量重复计作外部入流，也不会隐藏节点根容差造成的极小质量差。

## 验证证据

- J2 专项：`13 passed`；
- J1 + J2：`22 passed`；
- MODEL02：`299 passed`；
- 全仓：`607 passed / 71 skipped / 0 failed`；
- `compileall` 与 `git diff --check` 通过；当前环境未安装 Ruff。

Compatible `H=2m, 10=4+6m³/s`、20s 短时运行结果：12 个接受步、24 次 Junction stage solve；最大面积漂移 `8.28e-13m²`，最大流量漂移 `4.05e-12m³/s`，相对水量误差 `1.41e-14`，最大 CFL `0.09859`。

10s 小幅上游洪量过程 `10 -> 10.5 -> 10m³/s`：存储由 `18000` 增至 `18002.49999642m³`；外部水量残差 `8.85e-10m³`，节点残差体积 `-8.86e-10m³`，闭合修正后 `-1.72e-12m³`，相对水量误差 `4.92e-14`。

## 明确 NO-GO

- 节点矢量动量、Branch angle、局部损失、能量/动量控制体和一般 N-in/M-out；
- 多节点、环网、倒流、超临界、湿干、端点实测 face；
- Junction Gate/Pump、Pump Q-H、Gate/Pump 完整强耦合；
- 网络运行中的分区糙率、坡床/非棱柱移动流；
- v4 公开输入/结果、HTTP、Worker、数据库、前端和真实工程率定。

## 下一最小切片

建议独立选择其一：

1. `C3c-R1`：只在 Branch 内部 cell 接入已冻结的分区 Manning，节点端控制 cell 继续零摩阻，先证明同步阶段与水量账不变；
2. `C3b-J3`：先新增 Branch angle/节点控制体和独立矢量动量科学合同，再讨论结构节点；
3. 独立 Pump Q-H 或 v4 后端任务链。

任一路线都不能把本次 characteristic-only Junction 改写为完整强耦合。
