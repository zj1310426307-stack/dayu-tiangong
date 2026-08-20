# HYDRO-MODEL-02-C 开发报告

- 日期：2026-08-20
- 分支：`feature/HYDRO-MODEL-02-C-transient-hardening`
- 基线：`f5975a2`
- C1 提交：`b7b5084`
- 状态：C1、C2a 与 C2b 限定子门完成；完整科学与生产能力继续 `NO-GO`

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

## 3. 实现边界

- C2a 不插值 A/Q，不声称已找到连续方程的精确根；事件时刻是误差有界的右括端。
- 仅检测步端已括住的首个上升 crossing；步内上升后下降的双 crossing 仍可能漏检。
- 历史 Gate 和 C2a Gate 仍保持 mass-only；只有显式 `v4-lite-5` 固定 Gate 使用 completed-interface。
- C2b 不是 Gate/Pump 完整强耦合：不含阈值事件组合、自由出流、倒流、湿干、非棱柱 Gate、多个结构、Pump Q-H/效率或内部转输。
- v4-lite 仍仅限 Python direct engine；HTTP/Celery/数据库持久化没有接线。
- 湿干、溃坝、显式端点 Profile face、Branch/Junction、外部模型比较和真实率定均继续 `NO-GO/NOT RUN`。
