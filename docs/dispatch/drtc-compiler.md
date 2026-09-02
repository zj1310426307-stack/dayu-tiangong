# D-RTC 编译器与闭环控制边界

更新日期：2026-09-02
编译器合同：`dayu.drtc-compiler.v2`
固定 Runtime 基线：`DIMRset_2026.02`
当前结论：单闸门、单水位阈值规则的合成数值闭环已验证；其余动态语义继续关闭

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

`DRTCCompiler` 逐规则判定兼容性；`DRTCFBCArtifactWriter` 只为验收子集生成 XSD 可接受的 RTC/FBC/DIMR 文件。运行时由 DIMR 唯一拥有时间推进，Python 不轮询或推进 Solver。

## Manual Schedule 编译

`HydraulicControlCompiler` 复用统一静态 replay 和闸泵约束层，要求：

- 每个执行器有且仅有一个 v3 规范化约束记录，且每个限制都带来源；场景覆盖、统一结构和 legacy 字段在这一边界合并，缺失值不得沿用 v2 默认值；
- 每个执行器具有显式初态，不能默认闸关/泵停；
- 动作全部位于计划 duration 内，命令有唯一 native binding；
- requested、constraint-resolved 与 native target 分开保存；
- 约束拒绝不转成一个看似成功的替代目标。

静态编译层仍识别以下 binding，但受控 Runtime 只开放第一项：

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
| 一个 Gate `gate_opening_m` 阈值规则 | `COMPILED` | FBC standard trigger 在目标值与冻结初态 fallback 之间选择，已由 DRTC-S01/G03 证明 |
| `minimum_hold_seconds > 0` | 追加 blocker | 无 runtime-verified exact mapping |
| `cooldown_seconds > 0` | 追加 blocker | 无 runtime-verified exact mapping |
| `hysteresis > 0` | 追加 blocker | `deadBand` 状态等价性未经过固定 FBC benchmark |
| 多规则控制同一执行器 | 追加 blocker | Priority 与 tie-break 语义未验证 |
| Manual 与 Rule 控制同一执行器 | 追加 blocker | fallback/merger tie-break 语义未验证 |

`runtime_validated` 由源码控制的 acceptance registry 计算，不是环境开关。Registry 必须同时绑定 Runtime manifest 字节哈希、reviewed image digest、编译器版本、官方 case 与 DF01/DRTC-S01/G01/G02/G03；任一漂移即回到 `false`。多规则 priority/tie-break、manual + rule、hysteresis、hold、cooldown 和 Pump dynamic control 均继续 `UNSUPPORTED`。

## Observation bridge

`ObservationBinding` 使用白名单绑定 Dayu observation 与精确 D-Flow BMI 名称。当前 Builder 只为冻结模型中的 Cross Section 生成观测位置，因此所有 source id 还必须出现在该输出清单中：

- node water level → 显式且由 Builder 发出的 observation point；
- section water level → 显式 cross section；
- pump intake level → 显式且位于泵入口方向一侧的 observation point；
- gate head difference → 同一河段内、按上游到下游顺序且跨越闸址的两个 observation point，计算 `upstream - downstream`。

缺少变量、重复 Dayu identity、最近点推断、同一点组成水头差或方向不明确都拒绝。单个 node/section water-level 到 Gate 规则的 BMI bridge 已在固定 binary 闭环验证；gate head difference 和 pump intake 虽有纯转换合同，尚未进入 runtime-accepted rule subset。

## Compile、Freeze 与 Run 状态

Hydraulic v3 compile 是只读检查，会分别报告：计划、模型、Gate mapping、Pump mapping、Manual control、D-RTC、Observation 与 Runtime。状态必须保持分离：

- `ready_to_freeze` 需要所有静态语义检查通过，但不把 Runtime availability 当作冻结前提；
- `ready_to_run` 还必须同时满足 `runtime_available=true` 与 `controlled_runtime_accepted=true`；仅配置本地 reviewed digest 时才可能成立；
- 一个满足最小 Gate 子集的 enabled Rule 可以 freeze/run；多规则、Pump 或任何未验收时序语义仍精确阻断；
- manual-only 单 Gate schedule 由 FBC `BLOCK` 表执行，G02 已验证；不得与 Rule 混用。

Runtime unavailable 使用 `DFLOW_RUNTIME_BLOCKED`，规则等价性失败使用 `DRTC_RULE_SEMANTICS_UNSUPPORTED`。两者是不同问题，不能用“用户允许跳过真实验证”互相覆盖，也不能因编译成功自动降级到 MASCARET 或静态 replay。

## 已关闭的门与仍关闭的门

已关闭：固定四组件 provenance、不可变 digest、官方 D-Flow/FBC case、严格 artifact writer、显式 false fallback、DRTC-S01/G02/G03、requested/resolved/applied、H/Q/Gate parser、水量平衡、取消/超时/并发/孤儿清理。

仍关闭：多规则 priority/tie-break、hysteresis/hold/cooldown、manual + rule、Pump dynamic control、真实工程验证、生产调度与 PLC/SCADA。UI 必须显示 `Multi-rule priority: Not verified`，生产按钮保持禁用。

官方来源：

- [Delft3D FM suite components](https://github.com/Deltares/Delft3D/blob/DIMRset_2026.02/doc/development.md)
- [Official D-Flow FM examples](https://github.com/Deltares/Delft3D/tree/DIMRset_2026.02/examples/dflowfm)
- [Deltares Delft3D source tag](https://github.com/Deltares/Delft3D/tree/DIMRset_2026.02)
