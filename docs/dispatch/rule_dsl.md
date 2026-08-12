# Phase 4 规则 DSL

规则是结构化白名单数据，不是 Python/JavaScript 表达式，运行时从不使用 `eval`。

## 白名单

- 观测：`elapsed_time`、`node_water_level`、`section_water_level`、`gate_head_difference`、`pump_intake_level`
- 操作符：`>`、`>=`、`<`、`<=`
- 动作模板：`structure_type/structure_id/command_type/target_value`

动作模板只允许上述四个键；`gate` 只能使用 `gate_opening_m/gate_opening_ratio`，`pump` 只能使用 `pump_enabled/pump_unit_count/pump_target_flow`。冻结前还会校验观测对象、动作设施和闸泵拓扑均属于计划数据版本，且设施状态为 `online`。

## 语义

`minimum_hold_seconds` 要求条件连续满足后才激活；`hysteresis` 使用反向恢复阈值，避免临界值抖动；`cooldown_seconds` 限制再次触发；priority 更高者覆盖同设备同命令目标，同优先级后注册策略胜出并增加冲突计数。

激活、恢复、约束拒绝和冲突均进入诊断/事件。规则只能读取引擎显式提供的观测，不访问数据库、文件、网络或任意代码环境。

## 示例

```json
{
  "observation_type": "node_water_level",
  "observation_object_id": 101,
  "operator": ">=",
  "threshold": 12.5,
  "hysteresis": 0.2,
  "minimum_hold_seconds": 120,
  "cooldown_seconds": 600,
  "action_template": {
    "structure_type": "gate",
    "structure_id": 1,
    "command_type": "gate_opening_ratio",
    "target_value": 0.8
  },
  "priority": 20
}
```
