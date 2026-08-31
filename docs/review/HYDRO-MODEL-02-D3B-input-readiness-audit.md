# HYDRO-MODEL-02-D3B 真实工程输入就绪审计

- 审计日期：2026-08-31
- 分支：`feature/HYDRO-MODEL-02-D3B-real-small-river-gate-pump-validation`
- 基线：`hydro-model-02-d3a-rc1^{}` / `eb6b1b41e5416fb5dbcec17ad9bdf7c1923807a9`
- 当前结论：`INPUT GATE NO-GO`

## 当前已有证据

- HYDRO-DATA-02 受控中间成果已验证 3 个片段、40 个断面和 2,069 个 Profile 点；
- 每个已接纳片段的桩号连续性和断面/Profile 基础质量门已通过；
- 数据处理工具、私有 manifest/hash、PostGIS 导入和公开脱敏模板已经存在；
- D3A-RC1 已冻结可复用的单 Branch、单 Gate、单 external Pump 数值与平台边界。

## 阻塞项

1. 当前真实拓扑是 3 个不连通分量，不能通过放大吸附容差或手工补线伪造成一个工程河网；
2. 水流方向仍缺责任人确认；
3. 权威控制点和绝对平面精度尚未验收；
4. 当前项目的受控 raw 入口没有可用的真实 Gate/Pump 参数文件；
5. 上游 Q(t)、下游 H(t)、统一时间基准和初始状态尚未绑定当前片段；
6. 同工况水位/流量观测、闸泵运行记录和率定/验证分段尚未冻结；
7. 现有单区 Manning 只能作为 provisional 输入，不能冒充已率定工程糙率。

因此当前不允许生成真实案例 PASS、不允许启动率定，也不允许用 D3A synthetic fixture
替代缺失的真实结构、边界或观测。

## 允许的下一步

- 补齐一个天然单 Branch 片段的全部权威输入；或另选满足同一条件的小型案例；
- 冻结授权范围、来源 SHA-256、工程 CRS、高程基准、单位和统一时间基准；
- 一一绑定一个 Gate、一个 external Pump、边界、观测点和运行记录；
- 在任何求解前建立 readiness negative controls，缺字段、身份漂移或越出 D3A envelope
  必须 fail closed。

原始工程资料不得进入 Git 可达历史。公共仓库只保存脱敏合同、hash、失败关闭测试和
不泄露工程细节的机器证据。
