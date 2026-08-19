# HYDRO-MODEL-02-B 现有求解器基线审查

日期：2026-08-20
分支：`feature/HYDRO-MODEL-02-B-saint-venant-mvp`
起点：`0109245` (`HYDRO-MODEL-02-A` 升级路线审查)

## 1. 审查结论

仓库在 MODEL-02-B 前已有两类水力路径，但不能混为同一种能力：

| 输入 | 路由 | 方法 | 基线语义 |
|---|---|---|---|
| `dayu.model-input.v1` | `model/solver/saint_venant.py` | 一阶 Rusanov + hydrostatic reconstruction | 单河软件原型，输出 `hydraulic-result.v1` |
| `dayu.model-input.v2` | `model/network/solver.py` | continuity + Manning 准恒定河网 | 现有河网、闸泵和调度路径，输出 `hydraulic-result.v2` |
| `dayu.model-input.v3` | `adapt_v3_to_v2` 后进入 v2 | 同上 | 权威数据交换快照的旧求解投影 |
| `dayu.model-input.v4-lite` | `model/adapters/v4_lite.py` | 新 HLL 有限体积 + SSP-RK2 | MODEL-02-B 新增的单河 Saint-Venant MVP |

MODEL-02-B 没有删除旧 solver，也没有把 v4-lite 转回 v3/v2。`HydraulicEngine` 按 schema 精确分流，未知 schema 关闭失败。

## 2. v1 现状

- 支持单河 `U=(A,Q)` 显式求解。
- 已有 Rusanov 通量、CFL 缩步和静水重构原型。
- 不是本阶段的生产路径，不因 v4-lite 新增而更改输入或结果语义。

## 3. v2/v3 现状

- v2/v3 仍运行 `synchronous-network-continuity-manning-v1`。
- 它们不使用 MODEL-02-B 的 cell-centered 状态、HLL 通量或 SSP-RK2 子步。
- v3 中的粗糙率分区和 `K(h)` 表仍未被旧求解路径消费。
- 旧 `EngineResult` 及其 v1/v2 序列化未被改成 MVP 结果。

## 4. v4-lite 冻结边界

v4-lite 当前只允许一组有证据支持的软件 MVP 组合：

- 1 条方向已确认的 Branch；
- 不少于 3 个断面，严格递增 Chainage；
- 可使用单槽非矩形 Profile，但沿横向必须向唯一连续槽底单调收敛，且各 cell 必须是完全相同的棱柱断面；
- 显式初态，不从边界或默认水深猜测；
- 上游 Q(t) + 下游 H(t)，必须完整覆盖时域，禁止外推；
- 最多 1 座固定开度 Gate 和 1 座定流量外排 Pump；
- 唯一数值元组：`saint-venant / finite-volume-hll / ssp-rk2`。

禁止非棱柱 Profile 是显式的 fail-closed 门禁：当前 hydrostatic reconstruction 尚没有一般非棱柱几何源项，不允许在水量账平衡时仍产生伪静水而被误报通过。

## 5. 运行与持久化边界

v4-lite 本阶段是框架无关的 Python 引擎直连路由。HTTP 任务 DTO、Celery Worker 领取、数据库结果持久化和取消/进度回调没有半接入；传入这些回调时直接拒绝，避免静默忽略。

## 6. 基线判定

- 旧路径回归：`PASS`。
- v4-lite 软件 MVP 路由：`PASS`。
- 恒定均匀流 0.1% 科学候选线：`XFAIL / NO-GO`。
- 非棱柱断面、节点求解、闸泵强动量耦合、外部模型对比和生产率定：`NOT IMPLEMENTED / NO-GO`。

因此，本阶段可称为“大禹自主单河 Saint-Venant 软件 MVP 可运行”，不得称为 HEC-RAS/MIKE11 等级、实际工程率定或生产验收通过。
