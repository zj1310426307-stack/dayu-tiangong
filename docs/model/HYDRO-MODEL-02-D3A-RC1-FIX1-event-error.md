# HYDRO-MODEL-02-D3A-RC1-FIX1 Event Error

## 两类误差必须分开

Gate 开启是阈值事件，属于非光滑 observable。FIX1 分别记录：

1. **event-locator tolerance**：单次仿真在已接受步内定位事件的数值策略容差，固定
   `5 s`；
2. **mesh-induced spatial error**：在 locator 策略完全相同、结构位置完全相同的
   三层网格之间观察到的事件时间变化。

`5 s` 不能作为空间误差，也不能因为两层差小于 5 s 就宣布空间收敛。机器证据明确
写入 `locator_tolerance_is_spatial_error=false`。

## Gate event 空间趋势

| cells | Gate open time |
| ---: | ---: |
| 18 | 2853.750000 s |
| 54 | 2932.584888 s |
| 162 | 2949.090091 s |

| 比较 | absolute difference |
| --- | ---: |
| 18→54 | 78.834888 s |
| 54→162 | 16.505203 s |

差值严格下降，经验事件阶为 `1.423323`。按 `r=3` 的三层外推，事件时间渐近估计为
`2953.460749 s`，fine-grid mesh-induced estimated error 为 `4.370658 s`。这里的经验
阶只描述 threshold-event trend，不解释为 smooth PDE order。

该 `4.370658 s` 来自空间层差和外推；即使它恰好小于 `5 s` locator tolerance，两者
仍是独立字段和独立判据。CFL 时间细化的 locator 稳定性另在最终收敛报告记录。

## Pump event 分类

Pump start 在三层均为边界 knot/schedule-locked 的 `4000 s`。零差值不提供空间收敛
阶，因此 FIX1 把它列为 `schedule_locked_events`，明确
`used_as_spatial_convergence_evidence=false`，不把有利的零差冒充网格证据。
