# HYDRO-MODEL-02-C 开发报告

- 日期：2026-08-23
- 当前分支：`feature/HYDRO-MODEL-02-C3-foundation`
- 基线：`f5975a2`
- C1 提交：`b7b5084`
- 状态：C1、C2a、C2b、C2c 与 C3a 基础门完成；完整科学与生产能力继续 `NO-GO`

## 1. 本阶段完成内容

### C1：受限移动非棱柱参考流

`v4-lite-3` 以显式策略开放一个严格子集：平床、无摩阻、全湿、正向严格亚临界、均匀 cell-centre 网格、恒定 Q 与 Bernoulli 能头、特征边界且无结构物。API 与内核均独立执行作用域检查，并对每个接受态执行 H/Q/能头质量门。

### C2a：保守连续越阈值定位

`v4-lite-4` 新增 `one-shot-stage-above-bracketed-v1`，不改写历史 `one-shot-stage-above` 的接受步离散语义。新路径：

1. 从最后接受态以旧命令试算完整 SSP-RK2 步；
2. 只在 `H_pre <= threshold < H_post` 时识别上升 crossing；
3. 若括区间宽度超限，丢弃试算状态与水量预算，从同一接受态将步长减半重放；
4. 仅在右括端区间宽度不大于容差时接受守恒状态与预算；
5. Gate/Pump 从同一 pre-action 状态原子锁存，新命令只影响后续子区间；
6. 细分超限或触及最小步长时关闭失败，不接受粗糙事件时刻。

结果事件新增前/后时刻与水位、定位容差、细分次数、监测断面、空间支撑和 locator policy；`v4-lite-1/2/3` 不接受这些字段。

### C2b：固定 Gate completed-interface

`v4-lite-5` 新增 `submerged-orifice-energy-momentum-v1`，只允许单 Gate、固定开度、平床同断面、全湿正向亚临界、零摩阻、特征边界且无 Pump。每个 SSP-RK2 stage：

1. 以两侧当前水位、面积和孔口损失联立求唯一正向流量；
2. 质量通量在界面两侧使用同一 `Q_g`；
3. 左右动量分别使用 `Q_g²/A_L + gI1_L` 与 `Q_g²/A_R + gI1_R`；
4. 下游减上游的动量通量差记录为单位密度结构反力；
5. 淹没、正向、亚临界、方程残差和迭代上限任一不满足即失败，禁止回退到 mass-only；
6. 结果保存每个接受步的两个 RK stage，DTO 独立复算孔口损失、能头残差、动量通量、反力和 Gate 内部转输体积。

### C2c：bracketed control + completed-interface 组合门

`v4-lite-6` 只允许一个 `one-shot-stage-above-bracketed-v1` Gate，并同时要求 C2a 的保守事件策略和 C2b 的 completed-interface 策略。组合语义为：

1. 触发候选与细分重放期间 Gate 始终保持已接受的关闭命令；
2. 被接受的事件右括端仍以关闭 Gate 完成两个 RK stage，不把目标开度回填到已走过的时间段；
3. 事件与 Gate latch 在接受态原子提交，目标开度只从下一接受子区间开始进入 completed-interface；
4. 关闭阶段使用 `Q=0`、左右独立 `gI1` 动量与结构反力，不伪造孔口根求解；
5. 开启阶段逐 RK stage 求解总能头/淹没孔流，保存实际开度、残差、迭代、左右动量和反力；
6. 结果 DTO 反向核对事件、命令生效边界、stage 对、转输体积和开/关两类物理证据，缺任一链路即拒绝。

### C3a：多分支、结构物强闭合与分区糙率基础门

C3a 不新增公开输入版本，也不启动多 Branch 时间推进。它先建立三组可执行的内部合同：

1. `FiniteVolumeNetwork` 冻结 Branch 有向端点、全局 cell 身份、弱连通 DAG、确定性拓扑顺序和接受态同步；环路、断网、缺 Branch 状态或异步时刻全部拒绝。
2. `inspect_junction_preclosure` 只核验精确 Branch incidence、共同水位和有符号质量残差；证据固定写入 `momentum_compatibility=not-implemented` 与 `strong_coupling_ready=false`，不能冒充 Junction Saint-Venant 求解。
3. `StructurePlacementPlan` 用 Branch/cell 身份绑定 Gate 相邻界面、Pump 外排或网络目标 cell；不使用最近邻或裸索引猜测。
4. `InternalStructureStageEvidence` 只有在 source/target 质量、总能头、设备扬程/水头损失、左右动量和结构反力同时闭合时才能构造；现有单 Branch integrator 尚未消费该对象。
5. `PiecewiseManningZoneSolver` 要求分区完整覆盖 Branch、无缺口/重叠且边界对齐 cell face，再复制生成每 cell `manning_n`；已有 SSP stage 摩阻会直接消费解析后的系数。
6. `v4-lite-1` 至 `v4-lite-6` 的输入、结果和哈希均未改变；未生成 OpenAPI，也未修改 backend/Worker/数据库/前端。

## 2. 身份、状态与哈希

- Gate/Pump 仍以显式 public asset ID 为结构身份，监测对象为绑定 hydraulic Section cell centre。
- controller lifecycle 与实际 opening/status 分离；retry 和 event probe 不得修改已接受 latch。
- C2 冻结输入 hash：`d8246f6a230e7a704ed376bfa0e80ab3f64d725ac16f215cf31cee9bd979b357`。
- C2 冻结 mesh hash：`8958707007115410c5b0998ceeb40d21c32f8a280ec869cf00776767cabc794b`。
- C2 冻结 solver-policy hash：`89c97d79a184faa2bbe54d173e8503e3eaaf5cd3f17e71cb0a8dc3620d034ece`。
- 事件容差影响 input/policy hash，不影响 mesh hash。
- C2b 输入 hash：`b3cdf80d199ea643fcc763254c8c4878a843b6fb725f475f21a298dca2b541af`。
- C2b mesh hash：`5be802aaa262a02deb2419c45b1e4b30d88ed1f9f12f7eb43ad3a8e29b9c1e33`。
- C2b solver-policy hash：`cb36f8c8989313a69261ab139471d8f05058a88383486033e29ebf5c71c55625`。
- Gate 耦合容差只进入 input/policy hash；断面与网格不变时 mesh hash 不变。
- C2c 输入 hash：`b49e8b6174aa8979f04f8a0e6e0ae6350854c22487dd8374c7065346e4dabe74`。
- C2c mesh hash：`5be802aaa262a02deb2419c45b1e4b30d88ed1f9f12f7eb43ad3a8e29b9c1e33`。
- C2c solver-policy hash：`dd0f87e60a87826d55cc2bb02de1ad56a1bf4e8ec8a1ffe9698cdfb7738aaac4`。
- 组合策略使用新的 policy-hash domain；事件/Gate 参数进入 input 与 policy hash，网格未变时 mesh hash 继续不变。

## 3. 实现边界

- C2a 不插值 A/Q，不声称已找到连续方程的精确根；事件时刻是误差有界的右括端。
- 仅检测步端已括住的首个上升 crossing；步内上升后下降的双 crossing 仍可能漏检。
- 历史 Gate 和 `v4-lite-4` Gate 仍保持 mass-only；只有显式 `v4-lite-5/6` 使用 completed-interface。
- C2c 只组合一个 Gate 的一次性上升阈值与 completed-interface，不是 Gate/Pump 完整强耦合：不含连续调节、自由出流、倒流、湿干、非棱柱 Gate、多个结构、Pump Q-H/效率或内部转输。
- C3a 是下一阶段的 fail-closed 基础合同，不是多 Branch Saint-Venant 计算结果；Junction 动量相容求解、Branch 同步 RK 推进和边界特征分配均未实现。
- 分区 Manning 已能确定性映射并进入现有 cell-local 摩阻，但尚未接入公开 v4 输入，也没有分区 conveyance `K(h)`、滩槽分区或率定能力。
- 内部 Pump 只完成稳定布置和强闭合证据合同；Q-H/Q-η 工作点、设备功率方程及对 source/target cell 的保守更新尚未实现。
- v4-lite 仍仅限 Python direct engine；HTTP/Celery/数据库持久化没有接线。
- 湿干、溃坝、显式端点 Profile face、Branch/Junction、外部模型比较和真实率定均继续 `NO-GO/NOT RUN`。
