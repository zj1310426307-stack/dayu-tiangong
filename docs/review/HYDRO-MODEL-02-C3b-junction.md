# HYDRO-MODEL-02-C3b-J1 Junction 特征相容审查

- 日期：2026-08-23
- 分支：`feature/HYDRO-MODEL-02-C3b-junction`
- 父提交：`6900c7a`
- 结论：局部 1-in/2-out 特征相容 `GO`；多 Branch 时间推进与矢量动量 `NO-GO`

## 方程与符号

Branch 正方向均为 upstream 到 downstream。入流 Branch 在节点处使用下游端 trace，保留内部 `R+=u+Phi(A)`；两条出流 Branch 使用上游端 trace，各自保留 `R-=u-Phi(A)`。对共同绝对节点水位 `Hj`：

```text
Qin(Hj)   = Ain(Hj)  * (R+in  - Phi_in(Hj))
Qout_i(Hj)= Aout_i(Hj) * (R-out_i + Phi_out_i(Hj))
Rmass(Hj) = Qin - Qout_1 - Qout_2 = 0
```

`Phi(A)` 与现有 `subcritical-characteristic-v1` 边界使用同一矩形解析/非规则断面 GL8-H² 数值定义。根用 sign-preserving bisection，只有 stage bracket、质量、不变量、Froude 和局部负导数全部通过才接受。

## 已通过

1. compatible 矩形 `H=2m`、`10=4+6m³/s` round-trip；
2. 扰动矩形与测试侧独立 `2sqrt(gH)` 二分结果一致；
3. 三种不同表格 Profile 在 compatible state 下回到共同 `H=2.2m`；
4. `1e-4/1e-6/1e-8m` 容差递进均满足自己的 bracket/质量门；
5. 2-in/1-out、倒流、超临界、endpoint 摩阻、无共同域、岸顶外根和不收敛全部关闭失败；
6. evidence 不能伪造 sign bracket、质量、局部单调、vector momentum 或 strong-coupling 标签；
7. MODEL-02 `286 passed`，全仓 `594 passed / 71 skipped / 0 failed`。

## 状态与责任边界

- `OneInTwoOutJunctionSolver` 只读取 `FiniteVolumeNetwork` 和全部 Branch 的同步 `HydraulicState`，不拥有或推进 Branch 状态。
- 输出是节点 boundary trace 与 evidence，不是 `HydraulicState`，也不是河网结果 DTO。
- `NodeSolver` Protocol 已收紧为 network/node/states 到 typed Junction solution；未更改 backend API 或 OpenAPI。
- per-branch `Q²/A+gI1` 已保存，但节点没有方向角、二维速度或控制体，故没有矢量动量闭合。

## 明确 NO-GO

- Junction trace 写入各 Branch 的 SSP-RK2 stage flux、同步 CFL/retry 与网络水量账；
- 2-in/1-out、一般 N-in/M-out、环网、多节点同步和超临界/倒流/湿干；
- Junction Gate/Pump、Pump Q-H、分区糙率与节点的组合运行；
- v4 公开输入/结果、Worker/数据库/HTTP、真实工程率定及外部模型对比。

## 下一最小切片

建议 `C3b-J2`：在同一全湿、正向、无结构的 1-in/2-out 限定域内，把 J1 trace 作为三条 Branch 的物理边界通量接入一个同步 SSP-RK2 stage，建立全网统一 CFL/retry、节点质量账和短时 compatible-state 保持门。矢量动量和一般拓扑继续后置。
