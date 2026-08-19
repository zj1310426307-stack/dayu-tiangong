# ADR-HYDRO-0001：Network–Branch–Reach–Chainage 权威模型

- 状态：Accepted
- 日期：2026-08-18

## 决策

`hydraulic` schema 是同一 PostGIS 内的水动力权威语义层。Network 声明 display CRS 和米制 engineering CRS；Node 表示水力端点/汇分流/结构节点；Branch 保留业务身份、方向与整体桩号；Branch Vertex 保留源坐标和转换溯源；Reach 是在确认节点和结构物处分割的求解边。

所有版本化外键同时包含 `dataset_version_id`，不依赖应用层过滤防止串版。旧 `public.river` 继续作为 GIS/API 兼容投影，不另建第二空间数据库。

## 不变量

- engineering CRS 必须是投影 CRS，不得是 4326/4490。
- Branch 长度、拓扑容差和 chainage 全部在 engineering CRS 中按米计算。
- Branch 方向状态是 `confirmed|inferred|unknown`；只有 confirmed 可进入正式 v3 快照。
- 普通折线顶点不会自动成为水力节点。
- 拓扑重建只删除目标 Network 的 Node/Reach，同一输入必须得到稳定编码和确定性结果。

## 兼容写边界

写入编排只能由 hydraulic service 拥有。旧 River/CrossSection service 调用同一兼容投影函数，不分别实现两套独立业务规则。在 v3 成为默认且旧 API 迁移完成之前保留同事务兼容投影；移除时需新 ADR 和版本化 API 公告。
