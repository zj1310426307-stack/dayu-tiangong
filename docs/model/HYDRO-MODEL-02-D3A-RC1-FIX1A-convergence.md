# HYDRO-MODEL-02-D3A-RC1-FIX1A Convergence

## 结论

FIX1A 保持 FIX1 的物理函数、18/54/162 odd3 网格、Gate/Pump/monitor 精确位置、
边界、控制、求解器和容差不变，只修正 global peak-Q 的证据分类并新增可审计坐标。

global peak-Q 的 argmax 在空间层间漂移，因此分类为
`non-smooth-global-extremum`，不再进入 smooth Richardson acceptance。固定在 2850 m
monitor 的 peak Q 作为同一物理位置的 Q convergence 证据。

## Global peak-Q argmax

| level | abs peak Q (m3/s) | signed Q (m3/s) | time (s) | section id | section chainage (m) |
| --- | ---: | ---: | ---: | ---: | ---: |
| coarse | 0.221990672095 | 0.221990672095 | 7200 | 1 | 250 |
| medium | 0.245413157114 | 0.245413157114 | 4500 | 8 | 1250 |
| fine | 0.262216661618 | 0.262216661618 | 4500 | 18 | 972.222222222222 |
| fine CFL/2 | 0.262237020089 | 0.262237020089 | 4500 | 19 | 1027.777777777778 |

coarse→medium 同时时移与空间漂移；medium→fine 继续发生 chainage 漂移；同一 fine
网格的 CFL/2 复算也从 `972.2222 m` 移到 `1027.7778 m`。这些量是不同局部极值之间
的竞争，不是同一时空函数值的 smooth sequence。

FIX1 对这三个数值计算出的历史诊断为 `p=0.3022986331`，fine Richardson estimated
relative error `13.992205%`（对外固定披露 `13.99%`）。该数值保留在 v3
`known_limitations`，但 `legacy_fix1_diagnostic_is_valid_smooth_error_bound=false`。

若将来相同冻结策略下不再出现 argmax 漂移，FIX1A 规定 fail closed，并在运行前新增
更细空间层继续证明；不能自动把 global peak-Q 恢复为 smooth PASS。

## Fixed-monitor Q convergence

monitor 的 section chainage 与 control-volume centroid 在四层均精确为 `2850 m`：

| level | peak monitor Q (m3/s) | peak time (s) |
| --- | ---: | ---: |
| coarse | 0.185626630754 | 4500 |
| medium | 0.223881120602 | 3600 |
| fine | 0.227234800516 | 3600 |
| fine CFL/2 | 0.227367940719 | 3600 |

空间层 `|M-C|=0.038254489848 m3/s`、`|F-M|=0.003353679914 m3/s`，差值严格
下降，观测阶 `p=2.2157067924`。Richardson limit 为 `0.227557061489 m3/s`，fine
estimated error `0.000322260973 m3/s`，相对误差 `0.141618%`。

## 其余 smooth metrics

| metric | p | fine estimated relative error |
| --- | ---: | ---: |
| Gate downstream peak H | 1.202512 | 0.00850% |
| Pump source peak H | 1.366746 | 0.00172% |
| fixed-monitor peak Q | 2.215707 | 0.14162% |
| Gate transfer volume | 1.262492 | 0.19388% |
| Pump external volume | 1.451225 | 0.02103% |
| Pump input energy | 1.401308 | 0.02120% |

六项均为同一固定物理观测定义，层差下降且观测阶有限正。Gate threshold event 仍按
non-smooth event 单列，5 s locator tolerance 与 mesh-induced spatial error 分离；
Pump start 仍是 schedule-locked control knot，不作为空间收敛证据。

## 机器证据

现行 v3 artifact：
[final-convergence-fix1a.json](../../outputs/d3a/final-convergence-fix1a.json)。
v2 [final-convergence-fix1.json](../../outputs/d3a/final-convergence-fix1.json)
保留为 `superseded-FIX1-peak-Q-interpretation` 历史证据。
