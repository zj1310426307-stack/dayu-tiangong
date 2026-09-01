# 一维闸泵调度规则 DSL

规则是结构化白名单数据，不是 Python/JavaScript 表达式，任何路径都不得使用 `eval`。

## 白名单

- 观测：`elapsed_time`、`node_water_level`、`section_water_level`、`gate_head_difference`、`pump_intake_level`
- 操作符：`>`、`>=`、`<`、`<=`
- 动作模板：`structure_type/structure_id/command_type/target_value`

动作模板只允许上述四个键；Gate 只能使用 `gate_opening_m/gate_opening_ratio`，Pump 只能使用 `pump_enabled/pump_unit_count/pump_target_flow`。冻结前校验观测对象、动作设施和统一结构映射均属于计划数据版本，且设施为 `online`、统一结构为 `active`。

## 确定性语义

`minimum_hold_seconds` 要求条件连续满足后激活；`hysteresis` 使用反向恢复阈值避免临界值抖动；`cooldown_seconds` 限制再次触发。每个时间点先汇集人工动作与规则候选，再按较高 priority、规则优先于人工动作、较高冻结 rule id 的固定次序裁决；每次多候选裁决计入冲突统计。

选中目标仍须经过冻结设施约束：Gate 应用开度范围、变化率和最短保持时间；Pump 的 `pump_enabled/pump_unit_count` 应用机组范围、最短运行/停止时间和最大启动次数。输出明确标记 `selected`、`limited` 或 `rejected` 及原因。离散泵命令只允许 step；`pump_target_flow` 只检查泵站总设计流量上限，不改变合成启停状态，也不应用启停约束，更不表示已经计算或实现该流量，响应原因固定提示其没有 switching/hydraulic 语义。

规则只读取请求中逐时间点显式提供的合成观测或 `elapsed_time`，不访问数据库、文件、网络或任意代码环境。动态规则要求每个时间点提供全部所需观测；系统不填补、不外推缺失值。触发/恢复和目标裁决只返回预演响应，不写入运行事件表。

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

该示例只定义软件规则。若用合成水位驱动，它仍属于 `SYNTHETIC_DEVELOPMENT_ONLY`，不能作为工程率定、验证或设备控制依据。
