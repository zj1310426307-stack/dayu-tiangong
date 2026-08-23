# HYDRO-MODEL-02-C3a 基础门审查

- 日期：2026-08-23
- 分支：`feature/HYDRO-MODEL-02-C3-foundation`
- 父提交：`4202caa`
- 结论：基础合同 `GO`；多 Branch Saint-Venant 与 Gate/Pump 完整强耦合 `NO-GO`

## 已关闭的基础门

1. 多 Branch 拓扑：精确身份、方向、弱连通 DAG、确定性顺序、全局 cell 唯一和同步接受态。
2. Junction 预闭合：精确 incidence、共同水位、有符号质量残差和不可伪造的 preliminary pass。
3. 分区 Manning：Branch 全覆盖、无缺口/重叠、cell-face 对齐、逐 cell 解析和摩阻消费。
4. 结构布置：Gate 有序相邻界面，Pump 外排或 source/target 网络 cell 的稳定身份绑定。
5. 强闭合证据：内部 Gate/Pump 统一质量流，并同时核验总能头、设备扬程/损失、左右动量和结构反力。

## 兼容边界

- 未新增 `v4-lite-7`；`v4-lite-1..6` 输入、结果、hash 和路由保持不变。
- 未改 backend API、OpenAPI、数据库、Celery/Worker 或前端。
- legacy `model/network` continuity-Manning 不作为 C3a 实现，也没有被重命名成 Saint-Venant。
- C3a 只增加内部可组合合同和证据门；现有单 Branch 求解器行为未改变。

## 明确 NO-GO

- Branch 同步 SSP-RK2 时间推进、Junction 特征/动量相容与网络边界闭合；
- Gate 多结构、倒流、自由出流、湿干和非棱柱强耦合；
- Pump Q-H/Q-η 工作点、设备功率和 source/target conservative update；
- 分区 conveyance `K(h)`、滩槽复合糙率、公开 v4 输入与工程率定；
- 湿干、端点 Profile face、v4 后端任务链和真实工程对比。

## 后续状态

`C3b-J1` 已在后续分支实现全湿、正向、亚临界、无结构的 1-in/2-out Junction 特征相容 trace；详见 `docs/review/HYDRO-MODEL-02-C3b-junction.md`。C3a 的 `JunctionPreclosureEvidence` 仍保持 preliminary 语义，没有被重解释为强耦合结果。
