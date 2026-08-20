# HYDRO-MODEL-02-C Benchmark 报告

## 分级

| 门禁 | 级别 | 状态 | 不得外推的能力 |
|---|---|---|---|
| C1 光滑变宽、平床、无摩阻 Bernoulli 稳态 | 科学参考门 | PASS | 一般非恒定、变床、摩阻、湿干 |
| C2a Gate/Pump 同阈值保守括区间 | 软件/守恒事件门 | PASS | 连续根精确值、Gate 动量闭合、Pump Q-H |
| C2b Gate completed-interface | 科学门 | NOT RUN | 结构反力、能头损失、左右动量 |
| C3 湿干/溃坝/端点 face | 科学门 | NOT RUN | Ritter/Stoker、正性前沿、显式端点断面 |
| C4 v4 后端任务链 | 系统门 | NOT RUN | HTTP/Celery/DB 生产调度 |

## C1 门禁

- 网格 N=`25/50/100`，H 观测阶均大于 `0.99` 左右，Q 观测阶为 `0.985/0.998`。
- N=100 的 H/Q L1 相对误差均小于 `1e-4`，能头 L∞ 小于 `1e-4 m`。
- `dt=0.4/0.2/0.1s` 时误差不恶化；该稳态案例不用于声称 SSP-RK2 时间二阶。

## C2a 门禁

- 事件证据同时满足 `pre <= threshold < post` 和 `post_time-pre_time <= tolerance`。
- 粗/细 maximum dt 下事件时刻差不超过冻结容差。
- Gate/Pump 同时 crossing 以同一 pre-action 状态原子提交，稳定排序为 Gate 后 Pump。
- 触发区间不前向回填新命令，丢弃 probe 不累加水量或 accepted-step telemetry。
- 该门不证明 Gate/Pump 物理强耦合，仅证明时间轴、守恒重放与审计证据一致。
