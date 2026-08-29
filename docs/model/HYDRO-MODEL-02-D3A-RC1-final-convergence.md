# HYDRO-MODEL-02-D3A-RC1 FINAL Convergence

## 同一物理问题

所有空间层使用同一里程函数：

```text
z_b(x) = 9.0 - 1e-7*x
width(x) = 20*(1 - 0.12*sin(pi*x/7600))
n(x) = 0.025
H0(x) = 10.0 (x<3040), otherwise 9.8
```

Gate 固定在 `x=3040 m` 的物理 face，各层均精确映射；Pump 固定在 `x=6000 m`，按最近 section center 确定性映射。边界、Gate/Pump 参数、控制算法和 `event_time_tolerance=5 s` 相同。

20/40/80 预审已进入平滑量渐近趋势，但 40→80 Gate event 差仍为约 `21.56 s`，不能声明满足 5 s 门。最终采用 60/70/80；三层仍采样同一物理函数且 Gate face 精确一致，事件进入冻结容差范围。fine time refinement 保持 80 cells，将 CFL `0.7→0.35`；实际最大 accepted dt 从 `29.8206 s` 降到 `14.9126 s`。

## 冻结结果

| level | cells | runtime | steps | Gate open | Pump start | Gate volume | max Fr | min depth |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| coarse | 60 | 47.96 s | 750 | 2937.257 s | 4000 s | 3802.403 m3 | 0.05174 | 0.789879 m |
| medium | 70 | 88.12 s | 911 | 2940.669 s | 4000 s | 3799.706 m3 | 0.05307 | 0.789865 m |
| fine | 80 | 92.64 s | 1041 | 2943.227 s | 4000 s | 3797.233 m3 | 0.05395 | 0.789855 m |
| fine CFL/2 | 80 | 181.10 s | 2078 | 2943.218 s | 4000 s | 3805.451 m3 | 0.05411 | 0.789836 m |

Gate event differences 为 `3.4122 s → 2.5577 s`，Pump 为 `0→0 s`。Gate downstream peak H、Pump source peak H、peak Q、Gate volume、Pump volume 和 Pump energy 的 `|fine-medium|` 均小于 `|medium-coarse|`。时间细化后的 Gate volume 相对差 `0.2164%`，其余核心体积/能量/peak Q 差不大于 `0.2%`。

完整机器可读证据见 [final-convergence.json](../../outputs/d3a/final-convergence.json)。
