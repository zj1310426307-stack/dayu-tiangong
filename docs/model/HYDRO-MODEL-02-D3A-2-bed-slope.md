# HYDRO-MODEL-02-D3A-2 显式河床坡降合同

## 冻结身份

- Capability：`single-branch-gate-pump-manning-slope-v1`；
- Runtime adapter：`v4-to-d3a-2-v1`；
- Validation policy：`d3a-2-v1`；
- Geometry policy：`prismatic-explicit-linear-bed-v1`；
- 范围：单 Branch、全湿、正向严格亚临界、正有效 Manning、相同局部 Profile、1 Gate、1 external Pump。

## 河床权威

`hydraulic.cross_section.bed_elevation_m` 及其 source、confirmed-by、confirmed-at 元数据是河床高程的唯一权威。历史记录保持未确认状态；禁止从 tabulated Profile 的最低点猜测或回填河床。

Profile 点与 Gate sill、控制阈值、边界及结果水位共享 Network `vertical_datum`。数值核使用 `local_z = absolute_profile_z - bed_elevation_m`，水深只由 `H - bed_elevation_m` 计算。

## 符号与门禁

- `chainage_m` 沿 confirmed 上游到下游递增；
- `S0 = -dz_b/dx`，河床沿程下降时 `S0 > 0`；
- D3A-2 只接受严格下降的线性河床；缺失确认、平床、逆坡、非线性或不同 Profile 均失败关闭；
- 关闭 Gate 是不透水壁面，打开 Gate 仍要求正向水头和非负流量。

## 数值路径

斜床静水重构在较高界面床面以上取 `h* = max(H-z*, 0)`，再用各单元局部 Profile 的面积律求 `A(h*)`，避免只对矩形成立的面积差假设。摩阻、结构与时间积分继续复用既有有限体积求解器。

数据库迁移 `20260829_0023` 位于 `20260828_0022` 之上的单一可逆 head，只增加可空河床权威字段和一致性约束，不改写历史数据或 D1/D3A-1 快照。

S1/S2/S3、Gate/Pump 和 Hosted 数值见 [D3A-2 验证记录](./HYDRO-MODEL-02-D3A-2-validation.md)。更完整的数据合同说明保留在 [显式河床实现说明](./HYDRO-MODEL-02-D3A-2-explicit-bed.md)。
