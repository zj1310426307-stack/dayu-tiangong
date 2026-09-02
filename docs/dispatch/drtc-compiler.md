# D-RTC 编译器与闭环控制边界

更新日期：2026-09-02
编译器合同：`dayu.drtc-compiler.v1`
固定 Runtime 基线：`DIMRset_2026.02`
当前结论：动态规则未闭合，真实 D-RTC coupling 未验证

## 权威边界

Dayu `DispatchPlan`、Manual Schedule、Threshold Rule、Priority、约束与初始执行器状态始终是业务权威。RTC XML、FBC config 和 DIMR config 只是 Adapter/Runtime 产物，不能反向成为数据库 Domain，也不允许前端提交任意 RTC/XML/表达式。

目标链路是：

```text
Dayu DispatchPlan v3
        ↓ snapshot + hash
Manual Control Compiler / DRTCCompiler
        ↓ exact bindings + fail-closed report
DIMR + D-Flow FM + FBC/D-RTC
        ↓ observations / requested / resolved / applied
Controlled Hydraulic Result
```

当前只完成到确定性合同和编译审计。`DRTCCompiler` 不生成 RTC XML，不运行 FBC，也不在 Python 中实现逐时步水力耦合。

## Manual Schedule 编译

`HydraulicControlCompiler` 复用统一静态 replay 和闸泵约束层，要求：

- 每个执行器有且仅有一个 v3 规范化约束记录，且每个限制都带来源；场景覆盖、统一结构和 legacy 字段在这一边界合并，缺失值不得沿用 v2 默认值；
- 每个执行器具有显式初态，不能默认闸关/泵停；
- 动作全部位于计划 duration 内，命令有唯一 native binding；
- requested、constraint-resolved 与 native target 分开保存；
- 约束拒绝不转成一个看似成功的替代目标。

当前精确 binding 只有：

| Dayu command | D-Flow target | 转换 |
|---|---|---|
| `gate_opening_m` | `.../gateLowerEdgeLevel` | `reference_level_m + opening_m` |
| `gate_opening_ratio` | `.../gateLowerEdgeLevel` | 先乘显式 `gate_height_m`，再加基准高程 |
| `pump_target_flow` | `pumps/<native_id>/Capacity` | aggregate capacity identity |

`pump_unit_count`、`pump_enabled` 与 aggregate Capacity 不等价，当前返回 `HYDRAULIC_COMMAND_SEMANTICS_UNSUPPORTED`。编译成功只证明静态命令与约束合同可确定重放，不证明 FBC 已执行这些命令。

## DRTCCompiler 当前语义

`DRTCCompiler.compile()` 为每条 Rule 生成 `DRTCRuleCompileRecord`，报告 source semantics、候选 target semantics、warning 或完整 blocker，并对整个报告生成确定性 `artifact_hash`。

| 输入 | 当前结果 | 原因 |
|---|---|---|
| disabled Rule | `COMPILED`，省略 | 禁用规则明确不进入目标配置 |
| 任一 enabled Rule | `UNSUPPORTED` | Dayu inactive 时“无 target、保留其他策略或状态”的行为尚未证明等价于 FBC output |
| `minimum_hold_seconds > 0` | 追加 blocker | 无 runtime-verified exact mapping |
| `cooldown_seconds > 0` | 追加 blocker | 无 runtime-verified exact mapping |
| `hysteresis > 0` | 追加 blocker | `deadBand` 状态等价性未经过固定 FBC benchmark |
| 多规则控制同一执行器 | 追加 blocker | Priority 与 tie-break 语义未验证 |
| Manual 与 Rule 控制同一执行器 | 追加 blocker | fallback/merger tie-break 语义未验证 |

因此当前只有“无 enabled dynamic Rule”的报告可能为 `COMPILED`；所有报告都固定 `runtime_validated=false`。不得把候选 `standard/deadBand trigger + controlled output` 或 XSD 名称当作已生成/已运行的 D-RTC 配置。

## Observation bridge

`ObservationBinding` 使用白名单绑定 Dayu observation 与精确 D-Flow BMI 名称。当前 Builder 只为冻结模型中的 Cross Section 生成观测位置，因此所有 source id 还必须出现在该输出清单中：

- node water level → 显式且由 Builder 发出的 observation point；
- section water level → 显式 cross section；
- pump intake level → 显式且位于泵入口方向一侧的 observation point；
- gate head difference → 同一河段内、按上游到下游顺序且跨越闸址的两个 observation point，计算 `upstream - downstream`。

缺少变量、重复 Dayu identity、最近点推断、同一点组成水头差或方向不明确都拒绝。该 bridge 目前是合同与纯转换组件，不代表 DIMR coupler 已建立或 BMI 名称已通过所选 binary 的闭环运行验证。

## Compile、Freeze 与 Run 状态

Hydraulic v3 compile 是只读检查，会分别报告：计划、模型、Gate mapping、Pump mapping、Manual control、D-RTC、Observation 与 Runtime。状态必须保持分离：

- `ready_to_freeze` 需要所有静态语义检查通过，但不把 Runtime availability 当作冻结前提；
- `ready_to_run` 还必须同时满足 `runtime_available=true` 与 `controlled_runtime_accepted=true`；当前运行时信任与耦合验收均未建立，两项都固定阻断；
- 有 enabled dynamic Rule 时，当前 D-RTC report 为 `UNSUPPORTED`，所以既不能 freeze 也不能 run；
- manual-only snapshot 可在静态合同完备时 freeze，但当前真实 Runtime 缺失，仍不能 run。

Runtime unavailable 使用 `DFLOW_RUNTIME_BLOCKED`，规则等价性失败使用 `DRTC_RULE_SEMANTICS_UNSUPPORTED`。两者是不同问题，不能用“用户允许跳过真实验证”互相覆盖，也不能因编译成功自动降级到 MASCARET 或静态 replay。

## 解除 blocked 状态的最低证据

未来启用任何 enabled Rule 前，至少需要：

1. 固定 D-Flow FM、DIMR、FBC 与 HYDROLIB-core 完整 provenance；
2. 由类型化/白名单编译器实际生成可校验的 RTC、FBC 与 DIMR 文件；
3. 用官方 D-RTC coupling example 证明 Runtime 与解析链；
4. 用 Dayu benchmark 分别证明 trigger/recover、inactive retention、hysteresis、hold、cooldown、priority、manual fallback；
5. 记录 requested/resolved/applied、control event、structure result 和 runtime provenance；
6. 验证 timeout、cancel、process tree/container orphan 清理与并发 Workspace 隔离。

在这些证据完成前，UI/API 只能显示开发期编译报告，不得显示“D-RTC 已验证”或允许生产设备命令。

官方来源：

- [Delft3D FM suite components](https://github.com/Deltares/Delft3D/blob/DIMRset_2026.02/doc/development.md)
- [Official D-Flow FM examples](https://github.com/Deltares/Delft3D/tree/DIMRset_2026.02/examples/dflowfm)
- [Deltares Delft3D source tag](https://github.com/Deltares/Delft3D/tree/DIMRset_2026.02)
