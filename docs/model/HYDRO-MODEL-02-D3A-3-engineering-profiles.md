# HYDRO-MODEL-02-D3A-3 渐变工程断面能力

## 冻结身份

- 能力：`single-branch-gate-pump-engineering-profile-v1`
- 适配器：`v4-to-d3a-3-v1`
- 验证策略：`d3a-3-v1`
- 运行路由：`finite-volume-d3a-3-v4`
- 几何策略：`nonprismatic-engineering-linear-path-v1`
- 几何源：`hydraulic-function-linear-face-v1`
- 显式河床：`explicit-section-bed-elevation-v1`
- 结果：`dayu.hydraulic-result.v3`

## 实现边界

D3A-3 仅解锁一条 Branch 上的全湿、正向严格亚临界、正有效 Manning、显式下降河床、连续渐变非同表格断面、1 个 completed-interface Gate 和 1 个 external Q-H/Q-η Pump。求解仍使用原有 Saint-Venant 有限体积 HLL + SSP-RK2 核心，没有引入新求解器。

相邻单元面使用同一绝对水位评价两侧 A/T/P/I1，再沿相邻水力函数的线性路径构造面几何。匹配的单元压力源与面压力通量使静水平衡保持。Manning 源项、显式河床、闸门能量/动量闭合和泵外排源项均复用 D3A-1/2 已冻结实现。

Gate 必须分别使用上下游实际 Profile 的 A、T 和 I1，不得复制单侧几何。Pump 使用其绑定源单元的实际水位/面积响应；Q-H 工作点仍由源水位、出水位和系统损失决定。

## 渐变断面预检

每对相邻 Profile 在共同局部水深域的 25%、50%、75% 处计算 A/T/P/I1，对每项采用

`abs(left-right) / max(abs(left), abs(right), 1e-12)`

并取全部项的最大值。只有不大于 `0.25` 才可执行。合成扫描中，20 个断面的 12% 平滑渐缩—渐扩家族相邻变化小于 0.05，中部突然缩至 3 m 的断面超过 0.25 并被拒绝。

该阈值是保守的验证用途入口，不是对突扩、突缩或一般复杂河道的能力声明。不满足阈值时硬失败，不会通过警告降级执行。

## 明确禁止

- 干湿转换、反向流、临界/超临界流。
- 多 Branch、汇流点、分流点或一般河网。
- 突扩/突缩、断面闭合、多水道或不连通湿周。
- 桥梁、涵洞、堰、漫滩与横向分区糙率。
- 多 Gate、多 Pump、内部 Pump 或无权威河床高程。
- 率定、预报生产或真实调度决策。

## 产品行为

Registry、native-v4 投影、Worker capability、readiness API、OpenAPI 客户端和水动力页面使用同一能力身份。readiness 会在冻结任务前检查断面数量、显式河床权威、河床方向、断面差异与平滑度、Manning 范围、Gate/Pump 数量及位置、边界覆盖和完整数值策略。
