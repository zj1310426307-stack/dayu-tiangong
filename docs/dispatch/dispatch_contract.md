# Phase 4 调度领域契约

## 计划版本

计划状态为 `draft → validated → frozen → archived`。动作或规则修改会回到 draft；只有 validated 可冻结；冻结时规范化计划/动作/规则并写 SHA-256。冻结内容不可就地修改，后续迭代用 clone 生成递增版本。删除仅允许无运行的未冻结计划。

## 动作

动作字段包含时刻、序号、设施类型、唯一 gate/pump 外键、命令、目标、插值、优先级和说明。命令单位：

| 命令 | 单位/语义 |
|---|---|
| `gate_opening_m` | m |
| `gate_opening_ratio` | 0–1 比例 |
| `pump_enabled` | 0/1 |
| `pump_unit_count` | 整数机组数 |
| `pump_target_flow` | m³/s |

同设备同一时刻冲突、跨版本设施、缺失结构拓扑、超计划时长均拒绝。

## 运行与审计

一次运行创建共享冻结计划的 baseline/controlled 两个任务，异步入队。`dispatch_event` 记录来源、时刻、请求、实际、结果与原因；重复的持久控制状态不反复制造相同审计事件。结构结果与节点结果使用同一时间轴。

前端和 API 明确标识“仿真方案 / 未下发真实设备 / DEMO DATA”。当前系统只输出建议和模拟结果，不执行物理控制。
