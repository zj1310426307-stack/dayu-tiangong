# HYDRO-MODEL-02-D3A-3 连续非同断面合同

## 能力边界

`single-branch-gate-pump-engineering-profile-v1` 只解锁单 Branch、全湿、正向严格亚临界流中的连续渐变 tabulated Profiles。有效 Manning 糙率必须为正，河床必须显式给出并沿程严格下降；公开 native-v4 路径要求恰好一个 completed-interface Gate 和一个 external Q-H/Q-η Pump。

## 几何权威与压力源

- 每个 Section 的 tabulated Profile 和显式 `bed_elevation_m` 是本地几何权威；不会从 Profile 最低点猜测河床高程。
- `hydraulic-function-linear-face-v1` 在相邻断面间使用水力函数连续面源；有限体积通量、静水重构和 Manning 算子仍复用现有生产求解器。
- 非棱柱压力源使用各侧实际 A、T、P、I1；Gate 两侧不会复用同一个 Profile 的几何量。
- Pump 从其绑定源 Section 的实际几何与绝对水位求工作点，并作为外部体积源汇进入水量闭合。

## 连续性门

相邻断面在本地水深比例 0.25、0.50、0.75 处比较 A、T、P、I1。任一量的最大相对变化不得超过 0.25；完全相同、突变或声明了不匹配 geometry source 的组合均失败关闭。

该门只确认 mild contraction/expansion，不覆盖急缩、跌坎、宽顶堰、桥涵局部损失或任意突变建筑物。

## 证据

- P1：不同 Profile + 显式斜床 lake-at-rest，水位和流量残差达到 `1e-10` 门限；
- P2：无摩阻变宽动水，对独立 Bernoulli 根呈约一阶空间收敛；
- P3：变断面 + Manning + 坡降，对独立 standard-step 呈不低于 0.8 阶收敛；
- native-v4：20 个渐缩—渐扩断面、1 Gate、1 external Pump、6 h 综合案例通过水量、结构耦合和 provenance 门。

详细数值见 [D3A-3 验证证据](./HYDRO-MODEL-02-D3A-3-validation.md) 和 [D3A FINAL benchmark](./HYDRO-MODEL-02-D3A-final-benchmark.md)。
