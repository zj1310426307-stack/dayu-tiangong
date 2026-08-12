# Phase 5 优化契约

## 目标配置

`dayu.objectives.v1` 定义三个非负权重：`flood_risk`、`energy_cost`、`operation_cost`。运行时按权重总和归一化；物理量归一化尺度同目标配置一起冻结。

防洪包含全网最高水位、警戒超限时长与保证超限时长；能耗包含泵站能耗、运行时间和启动次数；操作包含闸门动作、累计开度变化、泵启停。

## 候选与约束

PSO 粒子表示完整时域调度方案。闸门基因映射为 `gate_opening_ratio`，泵站基因映射为 `pump_unit_count`。约束检查稳定返回：

```json
{"valid": false, "reasons": ["gate:1:opening_rate_exceeded"]}
```

无效候选保留审计记录并施加版本化惩罚；有效候选生成独立 `simulation_task`。

## Pareto 与推荐

三个目标都按最小化进行非支配分层。第一层是前端展示的 Pareto 前沿；其中加权总分最低者标记为 `recommended`。推荐没有设备执行权限，必须人工复核。
