# HYDRO-MODEL-02-D1 Pump 方程与数值策略

- 日期：2026-08-26
- 能力版本：`v4-lite-7`
- 能力 ID：`hydro-model-02-d1-pump-strong-coupling`

## 1. 曲线与并联机组

单机 Q-H 与 Q-η 均采用输入顺序不变的分段线性插值：

```text
pump_curve_policy      = piecewise-linear-qh-v1
pump_efficiency_policy = piecewise-linear-q-efficiency-v1
```

流量节点必须严格递增，Q-H 扬程必须有限且非负，效率必须满足
`0 < η <= 1`。两个曲线域取交集，域外不外推、不钳位、不选最近点。

N 台同型泵并联时：

```text
q_single = Q_total / N
H_station(Q_total, N) = H_single(q_single)
η_station(Q_total, N) = η_single(q_single)
```

异型泵组合不在 D1 作用域内。

## 2. 系统扬程与工作点

外排泵的系统扬程定义为：

```text
H_system(Q) = H_outlet - H_source + H_static + K * Q * |Q|
```

`K` 的单位固定为 `s²/m⁵`。每个 SSP-RK2 stage 独立求解：

```text
f(Q) = H_station(Q, N) - H_system(Q) = 0
```

求解区间来自 Q-H/Q-η 公共曲线域，经并联台数缩放后使用确定性二分法。
区间端点没有异号根或达到最大迭代次数仍不满足扬程残差时立即失败；绝不回退
`design_flow`。

## 3. 功率与能量

同一 stage 工作点同时生成流量、扬程、效率和功率：

```text
P_hydraulic_kW = ρ * g * Q * H / 1000
P_input_kW     = P_hydraulic_kW / η
ρ              = 1000 kg/m³
g              = 9.81 m/s²
```

一个已接受 SSP-RK2 步的外排体积与输入能量为：

```text
V_step   = 0.5 * dt * (Q_stage1 + Q_stage2)
E_step   = 0.5 * dt * (P_stage1 + P_stage2) / 3600
```

只有已接受的 stage pair 进入累计量。失败试算、事件探测和 retry 的临时证据不进入
结果或能量账。

## 4. 有限体积源项

D1 只实现 external sink：

```text
A_new = A_old - dt/dx * (... + Q_pump)
Q_new = Q_old - dt/dx * (... + Q_pump * u_local)
```

动量策略 ID 为 `local-advective-external-sink-v1`。质量和动量使用同一 stage
工作点；若导致负面积，先按已有 positivity/retry 路径缩步，耗尽后失败，不减小泵流量。

## 5. 控制语义

`stage-hysteresis-min-runtime-v1` 只在 accepted state 提交：

```text
OFF 且 H >= start_level 且最小停机时间满足且未超过最大启动次数 -> START
ON  且 H <= stop_level  且最小运行时间满足                       -> STOP
否则保持
```

RK stage 只读取已提交命令。Gate 与 Pump 同一接受时刻发生动作时，稳定顺序为 Gate
后 Pump，二者都读取同一个 pre-action accepted state；动作只影响下一接受子区间。

## 6. 可审计证据

每个 Pump stage 记录 source/outlet stage、运行台数、总/单机流量、泵扬程、系统扬程、
残差、效率、两类功率、迭代数、曲线段和全部 policy ID。结果合同独立复算：

- `H_pump - H_system = residual`；
- `P_input = ρgQH/η`；
- stage pair 连续覆盖完整模拟时段；
- stage 数等于 `2 * accepted_step_count`；
- 累计水量和能量等于 stage 梯形积分；
- 最大残差不超过输入容差。

这些证据是审计输出，不是下一时间步的第二套物理状态。
