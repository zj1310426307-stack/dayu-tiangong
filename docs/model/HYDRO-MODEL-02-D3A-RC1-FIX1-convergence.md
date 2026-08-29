# HYDRO-MODEL-02-D3A-RC1-FIX1 Convergence

## 同一物理问题与固定位置

三层使用同一连续 bed/profile/Manning/initial state、边界、Gate/Pump 参数与控制。
空间网格为运行前冻结的 18/54/162 cells，`r=3/3`。Gate face 始终为 3040 m，
Pump control-volume centroid 始终为 6000 m，monitor centroid 始终为 2850 m；三类
位置误差在各层均为 0 m。

## 空间层结果

| level | cells | Gate open | Gate downstream peak H | Pump source peak H | peak Q | Gate volume | Pump volume | Pump energy |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| coarse | 18 | 2853.750000 s | 9.860192099 m | 9.816321883 m | 0.221990672 m3/s | 3903.328310 m3 | 54.678149 m3 | 0.325622622 kWh |
| medium | 54 | 2932.584888 s | 9.868826890 m | 9.818960120 m | 0.245413157 m3/s | 3815.107834 m3 | 54.901574 m3 | 0.326806899 kWh |
| fine | 162 | 2949.090091 s | 9.871131026 m | 9.819547894 m | 0.262216662 m3/s | 3793.068046 m3 | 54.946939 m3 | 0.327060914 kWh |

## Smooth metrics、观测阶与 Richardson 估计

| metric | `|M-C|` | `|F-M|` | p | asymptotic limit | fine estimated error | fine relative error |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Gate downstream peak H | 0.008634791 m | 0.002304135 m | 1.202512 | 9.871969650 m | 0.000838624 m | 0.00850% |
| Pump source peak H | 0.002638238 m | 0.000587774 m | 1.366746 | 9.819716382 m | 0.000168488 m | 0.00172% |
| peak Q | 0.023422485 m3/s | 0.016803505 m3/s | 0.302299 | 0.304875461 m3/s | 0.042658800 m3/s | 13.99221% |
| Gate volume | 88.220475 m3 | 22.039788 m3 | 1.262492 | 3785.728258 m3 | 7.339789 m3 | 0.19388% |
| Pump volume | 0.223425 m3 | 0.045365 m3 | 1.451225 | 54.958497 m3 | 0.011558 m3 | 0.02103% |
| Pump energy | 0.001184277 kWh | 0.000254015 kWh | 1.401308 | 0.327130275 kWh | 0.000069361 kWh | 0.02120% |

六项差值均严格下降，观测阶均为有限正数。除 peak Q 外均高于 `0.7` 偏好值；
peak Q 的正阶和较大外推误差如实保留，不通过改网格或调案例掩盖。

## Non-smooth event

Gate event 差为 `78.834888→16.505203 s`，经验事件阶 `1.423323`，外推事件时间
`2953.460749 s`，fine-grid mesh-induced estimated error `4.370658 s`。该误差与单次
事件定位器的 `5 s` tolerance 独立。Pump start 三层均为 schedule-locked `4000 s`，
不作为空间收敛证据。详见
[event-error](./HYDRO-MODEL-02-D3A-RC1-FIX1-event-error.md)。

## Fine-grid 时间细化

fine 网格保持 162 cells，仅将 CFL `0.7→0.35`：

| metric | fine | fine CFL/2 | absolute / relative difference |
| --- | ---: | ---: | ---: |
| accepted maximum dt | 11.236486 s | 5.618243 s | ratio `0.500000` |
| Gate open time | 2949.090091 s | 2949.089918 s | 0.000173 s |
| Gate volume | 3793.068046 m3 | 3796.191608 m3 | 3.123561 m3 / 0.08235% |
| peak Q | 0.262216662 m3/s | 0.262237020 m3/s | 0.000020358 m3/s / 0.00776% |
| Pump volume | 54.946939 m3 | 54.934814 m3 | 0.012125 m3 / 0.02207% |
| Pump energy | 0.327060914 kWh | 0.326998128 kWh | 0.000062786 kWh / 0.01920% |
| Gate downstream peak H | 9.871131026 m | 9.870789982 m | 0.000341044 m |
| Pump source peak H | 9.819547894 m | 9.819396964 m | 0.000150930 m |

实际最大 dt 精确减半，全部稳定性阈值通过。

## 包络、平衡、残差与摩阻

四层 `runtime_envelope_status=pass`。最坏值：minimum depth `0.789331056 m`、
minimum Q `-1.64083e-14 m3/s`、maximum Fr `0.058066903`、maximum friction number
`0.099703930`、relative water-balance error `5.34533e-16`、Gate residual
`9.99105e-11 m`、Pump residual `9.99900e-11 m`。9517 个接受步只出现 1 次受控
friction retry，低于冻结比例门。

## 机器证据

完整 v2 证据为
[final-convergence-fix1.json](../../outputs/d3a/final-convergence-fix1.json)。旧
[final-convergence.json](../../outputs/d3a/final-convergence.json) 仅为
`superseded-pre-FIX1` 历史 smoke。
