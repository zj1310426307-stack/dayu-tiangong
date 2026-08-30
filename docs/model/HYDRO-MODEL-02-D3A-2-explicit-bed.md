# HYDRO-MODEL-02 D3A-2：显式河床与单河道纵坡

## 已解锁范围

- 能力：`single-branch-gate-pump-manning-slope-v1`
- 适配器：`v4-to-d3a-2-v1`
- 验证策略：`d3a-2-v1`
- 单 Branch、全湿、正向严格亚临界、每断面一个有效 Manning `n in (0, 0.10]`
- 严格下降的线性河床、相同局部 Profile 形状、1 个 completed-interface Gate、1 个 external Q-H/Q-efficiency Pump
- 仅用于验证；不包含非相同断面、干湿交替、反向流、率定或生产调度决策

## 河床权威数据契约

`hydraulic.cross_section` 是河床高程的权威所有者：

- `bed_elevation_m`：相对于 Network `vertical_datum` 的绝对高程，单位 m；
- `bed_elevation_source`：`surveyed`、`design` 或 `synthetic`；
- `bed_elevation_confirmed_by` 与 `bed_elevation_confirmed_at`：确认主体和时间；
- 历史数据迁移后保持 `unconfirmed + NULL`，不得从 `min(Profile)` 回填；
- D3A-2 readiness 对缺失或未确认河床失败关闭。

Profile 点仍是同一垂直基准下的绝对高程。进入数值核时先执行
`local_z = absolute_profile_z - bed_elevation_m`，再由显式河床平移到核的绝对水位坐标；河床从不由 Profile 反推。为保证当前单一连续槽断面契约，声明河床必须与 Profile 的连续最低槽相合，但 Profile 最低点不是权威来源。

## 方向、坡度与水位

- `chainage_m` 沿 Branch 的 confirmed 上游至下游方向递增，单位 m；
- 河床坡度定义为 `S0 = -dz_b/dx`，无量纲；
- 河床向下游下降时 `S0 > 0`；D3A-2 要求所有相邻断面的 `S0` 一致且严格为正；
- Gate sill、Gate/Pump 控制阈值、边界水位、结果水位均为同一 `vertical_datum` 下的绝对高程；
- 水深仅由 `H - bed_elevation_m` 得到，禁止二次叠加河床高程。

## 数值修正

斜床静水平衡暴露了旧重构对非矩形表格断面的矩形假设。D3A-2 将较高界面床面以上的剩余水深定义为 `h* = max(H-z*, 0)`，再用每个单元的局部 Profile 面积律计算 `A(h*)`。这替代了只对矩形成立的 `A(H)-A(z*)` 面积相减方式，使平移后的表格断面满足同一静水源项与通量闭合。

关闭 Gate 是不透水壁面；任意符号的瞬时水头差只产生壁面载荷，不构成反向流。Gate 打开后仍严格要求正向水头和非负流量。

## 数据库迁移

迁移 `20260829_0023` 是 `20260828_0022` 之上的单一可逆 head。它只新增可空河床权威字段和一致性约束，不更新历史行，也不改变 D1/D3A-1 输入快照的序列化形状。
