# HYDRO-MODEL-02-C 开发报告

- 日期：2026-08-20
- 分支：`feature/HYDRO-MODEL-02-C-transient-hardening`
- 基线：`f5975a2`
- C1 提交：`b7b5084`
- 状态：C1 与 C2a 软件/科学子门完成；完整科学与生产能力继续 `NO-GO`

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

## 2. 身份、状态与哈希

- Gate/Pump 仍以显式 public asset ID 为结构身份，监测对象为绑定 hydraulic Section cell centre。
- controller lifecycle 与实际 opening/status 分离；retry 和 event probe 不得修改已接受 latch。
- C2 冻结输入 hash：`d8246f6a230e7a704ed376bfa0e80ab3f64d725ac16f215cf31cee9bd979b357`。
- C2 冻结 mesh hash：`8958707007115410c5b0998ceeb40d21c32f8a280ec869cf00776767cabc794b`。
- C2 冻结 solver-policy hash：`89c97d79a184faa2bbe54d173e8503e3eaaf5cd3f17e71cb0a8dc3620d034ece`。
- 事件容差影响 input/policy hash，不影响 mesh hash。

## 3. 实现边界

- C2a 不插值 A/Q，不声称已找到连续方程的精确根；事件时刻是误差有界的右括端。
- 仅检测步端已括住的首个上升 crossing；步内上升后下降的双 crossing 仍可能漏检。
- Gate 仍是 mass-only 内部通量，Pump 仍是定流量 external sink；未完成 Gate 左右动量/能头闭合或 Pump Q-H 工作点。
- v4-lite 仍仅限 Python direct engine；HTTP/Celery/数据库持久化没有接线。
- 湿干、溃坝、显式端点 Profile face、Branch/Junction、外部模型比较和真实率定均继续 `NO-GO/NOT RUN`。
