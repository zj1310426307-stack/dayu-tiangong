# HYDRO-MODEL-02-C3c-R1 分区 Manning 网络运行门审查与交付说明

- 日期：2026-08-23
- 阶段：HYDRO-MODEL-02-C3c-R1
- 结论：限定实现与科学合同 `PASS`；完整科学与生产能力继续 `NO-GO`
- 能力定位：在 C3b-J2 的单节点 1-in/2-out 同步网络上，可选启用纵向、cell-face 对齐的分区 Manning；一般河网与生产能力继续 `NO-GO`

## 1. 冻结作用域

C3c-R1 不改变 J2 的拓扑和水动力范围，只在既有三 Branch 同步推进中增加受控摩阻：

```text
Q(t) -> incoming Branch -> Junction -> outgoing Branch 1 -> H1(t)
                                  \-> outgoing Branch 2 -> H2(t)
```

仍只接受：

- 一个连通、无环、三 Branch、单 Junction 的 1-in/2-out 分流拓扑；
- 每条 Branch 内为平床、棱柱断面；不同 Branch 仍可使用不同的受支持断面；
- 全部 cell 全湿、正向、严格亚临界；
- 外边界使用既有 `subcritical-characteristic-v1`；
- 每个 SSP-RK2 stage 重新求解一次 J1 Junction trace；
- 无 Gate、Pump 或其他结构运行状态。

`OneInTwoOutRoughnessPlan` 是可选合同：不传计划时严格保持 J2 的全网 `n=0` 语义；传入计划时才启用 `piecewise-manning-junction-buffer-v1`。因此 R1 不会让历史 J2 调用静默进入有摩阻路径。

## 2. 糙率状态与 provenance 所有权

运行时唯一的 Manning 系数真值是 `FiniteVolumeNetwork` 内各 Branch mesh 的：

```text
network.branch(...).mesh.cells[i].manning_n
```

`OneInTwoOutRoughnessPlan` 不在 stage 中覆盖或解释另一套系数。它只持有三个 `ZonedRoughnessMesh`，用于证明这些逐 cell 系数来自已冻结的分区解析过程。计划必须与网络中的三个 mesh 精确一致，否则在推进前失败。

每个 `ZonedRoughnessMesh` 保存 `piecewise-manning-cell-face-aligned-v1` assignments。证据链检查：

- Branch、cell、section 和 cell 顺序一致；
- assignment 的 Manning 系数与 mesh cell 完全一致；
- 每段 assignment 长度等于对应 `dx`；
- assignment 首尾连续，没有空洞或重叠；
- 同一 zone 的系数唯一，且 zone assignments 不能离散回跳；
- zone 边界只能位于有限体积 face，禁止切穿一个控制单元。

这样，plan 负责“系数从哪里来”，mesh 负责“本次计算实际消费什么”，二者职责不重叠。

## 3. Junction 缓冲控制单元

J1 特征闭合继续要求 Junction 邻接端点 cell 不含 Manning 源项。R1 因此只把以下三个控制单元冻结为 `n=0`：

1. incoming Branch 的最后一个 cell；
2. outgoing Branch 1 的第一个 cell；
3. outgoing Branch 2 的第一个 cell。

三条 Branch 均至少需要三个 cells。除上述三个 Junction 邻接控制单元外，网络内其余所有 cells 都必须由 plan 显式给出严格正的 Manning 系数。外部 Q/H 边界邻接 cell 不属于这三个 Junction 缓冲单元，可以具有正糙率。

这一约束不是通用端点含源特征边界。它是在 J1 尚未建立“端点特征传播与 cell 内摩阻源联合闭合”之前的受限缓冲策略。

## 4. SSP-RK2 stage 摩阻更新

现有 Branch Euler stage 在完成 HLL/物理边界通量和其他已支持源项后，按 cell 使用后通量状态 `Q*` 计算半隐式 Manning 更新：

```text
k  = g n^2 / (A R^(4/3))
mu = dt k |Q*|
Q_after = Q* / (1 + mu)
```

摩阻在两个 SSP-RK2 Euler stages 中分别重新计算。第二 stage 使用第一 stage 得到的新面积、流量和水力半径，不复用第一 stage 的摩阻结果。

每个启用 R1 的接受步保留两份 `NetworkRoughnessStageEvidence`。每份 stage evidence 包含三个同步 Branch 记录，并将静态 zone assignments 与逐 cell `ManningCellStageEvidence` 一一绑定。逐 cell 证据至少保存：

- `cell_id`、`A`、`n`、水力半径和 `dt`；
- 摩阻前后的 `Q`；
- 系数 `k`、摩阻数 `mu` 和分母 `1+mu`；
- 可独立复算的代数残差及符号保持语义；
- 本 Branch 的 Junction 缓冲 cell 身份及其零源更新。

证据是接受 stage 的审计产物，不反向成为 `HydraulicState`，也不成为下一步系数来源。

## 5. `mu <= 0.1` 时间强度门与统一 retry

`OneInTwoOutRoughnessPlan.maximum_stage_friction_number` 默认且最多为 `0.1`，调用方只能选择更严格的正阈值。每个网络 Euler stage 取三条 Branch、全部 cells 的最大 `mu`：

```text
max(mu_cell) <= maximum_stage_friction_number <= 0.1
```

超过门限时，该 stage 抛出稳定性失败。既有统一 retry 所有权保持不变：整个三 Branch trial 和本次 trial evidence 一并丢弃，统一缩小 `dt` 后从同一接受态重算 Junction、通量、摩阻和证据。由于 `mu` 与 `dt` 成正比，该门为 split-source 时间强度控制，不替代 Saint-Venant CFL 门。

只有最终接受步的两个 roughness stage records 进入 `NetworkStepResult`。运行诊断另存接受步最大摩阻数、roughness stage 数和版本化 policy；拒绝 trial 不得混入接受证据。

## 6. 水量账与动量证据边界

Manning 更新只修改守恒状态中的流量/动量变量，不修改面积。因此：

- `NetworkStageBudget` 继续只记录外边界质量通量和 Junction 质量闭合；
- `NetworkStepBudget` 继续只积分 source/sink 和内部 Junction 转输体积；
- 摩阻 decrement 不得解释为外排流量、边界体积或水量损失；
- roughness evidence 与水量账分开存放。

全网水量关系仍为：

```text
Delta S = V_source - V_sink1 - V_sink2 + residual
water_balance_residual + junction_mass_residual_volume ~= 0
```

水量闭合只能证明质量账一致，不能单独证明摩阻、节点动量或能量物理正确。

## 7. Junction 端点摩阻省略与网格依赖

每条入射 Branch 省略一个 Junction 邻接完整 cell 的摩阻。对局部摩阻坡度 `Sf`，未计入的能头量级约为：

```text
Delta H_omit ~= Sf * dx_control
```

因此该缓冲策略具有显式网格依赖：改变 Junction 邻接 cell 的 `dx` 会改变被省略的摩阻长度和局部水位/流量响应。R1 结果必须携带 `junction_endpoint_full_cell_friction_omitted_grid_dependent_v1` 语义，不得把当前结果外推为网格无关的端点含源特征解。

后续若要取消这一省略，必须单独建立并验证端点非零源项的特征相容合同，而不是简单删除 `n=0` 门。

## 8. 科学解释

C3c-R1 的 Branch 仍为平床。正 Manning 摩阻没有床坡重力分量与之平衡，所以原 J2 的 compatible 正向均匀流在启用 R1 后应演化为耗散瞬变，而不是保持移动稳态。

本阶段可以验证：分区系数被正确消费、摩阻耗散方向正确、两 stage 均重算、统一 retry 有效，以及水量账不受动量源污染。不能据此声称坡床 Manning 正常水深、率定可用或长期稳态精度。

同样，当前公式是每个 Euler stage 的符号保持半隐式 source update。它不是已经证明的全局二阶 IMEX 离散；`SSP-RK2` 标签不能扩张为“含 Manning split source 的全局二阶精度”声明。

## 9. 验证矩阵

| 验证项 | 预期证据 | 当前结果 |
|---|---|---|
| plan 与三个 network meshes 精确匹配 | 完整覆盖、face 对齐、身份/顺序/系数一致 | PASS；缺支、重复、mesh 矛盾均拒绝 |
| Junction 三个缓冲 cells | 仅三者 `n=0`，其余 cells 均 `n>0` | PASS |
| 两个 SSP-RK2 stages | 每接受步两份同步三 Branch roughness evidence | PASS |
| 半隐式公式独立复算 | `Q_after=Q*/(1+mu)`，归一化残差 `<=1e-12` | PASS；固定两 stage 解析参考一致 |
| 摩阻方向 | 正向流不翻转且 `|Q_after|<=|Q*|` | PASS；更大 `n` 阻尼更强 |
| `mu` retry | 超过 `0.1` 的 trial 整网拒绝，缩步后重新计算 | PASS；`1s -> 0.5s`，只保留接受证据 |
| 耗散瞬变 | 有摩阻结果相对零摩阻基线产生可解释的动量衰减 | PASS |
| 外部与 Junction 水量账 | 摩阻不进入质量账，存储与边界体积闭合 | PASS；冻结相对门 `<=1e-11` |
| J2 默认兼容 | 未传 plan 时全零摩阻原语义保持 | PASS；不生成 R1 evidence |
| C3c-R1 专项测试 | 通过数与失败数 | `13 passed / 0 failed` |
| MODEL02 回归 | 通过数与失败数 | `312 passed / 0 failed` |
| 全仓回归 | 通过、跳过与失败数 | `620 passed / 71 skipped / 0 failed` |

## 10. 明确 `NO-GO`

以下能力没有由 C3c-R1 完成或证明：

- Junction endpoint 非零摩阻源项的特征相容闭合；
- 坡床 Manning 正常水深、移动稳态或相应收敛门；
- 分区 conveyance `K(h)`、同一横断面内主槽/滩地复合横向糙率；
- Branch angle、节点控制体和矢量动量闭合；
- 一般 N-in/M-out、多节点、环网或任意网络拓扑；
- 湿干、倒流、超临界及跨流态；
- Gate/Pump、结构节点或完整强耦合；
- 公开 v4 输入/结果、HTTP、Worker、数据库和前端任务链；
- 真实工程率定、外部模型对比或生产调度决策。

## 11. 主要实现位置

- `model/solver/finite_volume/roughness.py`：zone、assignment 和 face-aligned provenance；
- `model/solver/finite_volume/friction.py`：半隐式 Manning 与逐 cell stage evidence；
- `model/solver/finite_volume/integrator.py`：每个 Euler stage 消费摩阻并返回 evidence；
- `model/solver/finite_volume/network_solver.py`：可选 plan、Junction 缓冲门、同步 stage evidence、`mu` retry 和运行诊断；
- `model/solver/finite_volume/junction.py`：继续保留 Junction 邻接端点零摩阻门。

R1 是 J2 之上的受限纵向分区摩阻运行门，不改变 characteristic-only Junction 的物理等级，也不解除任何既有生产 `NO-GO`。
