# 一维水动力模型 QA

生产 QA 的唯一规则实现是 `HydraulicModelQA`。前端只呈现结果，不能复制或绕过规则。`ERROR` 会令 `run_allowed=false`；正式任务创建时由 Backend 生成与输入快照哈希绑定的 QA 封套，Worker 在调用 MASCARET 前重新计算 QA、核对封套哈希和模型实体身份。

## 检查内容

- CRS：engineering CRS 必须是已确认的投影坐标系，水平单位必须为 m；高程基准不能为 UNKNOWN。
- Network：Branch ID、方向、端点 Node、中心线重复点与空网络。
- Cross Section：Branch/chainage、重复位置、offset 单调性、方向、断面轴与中心线相交、投影距离、断面间距、河底跳变与反坡。
- Boundary：外部端点覆盖、重复条件、侧向流位置、全模拟时段的 GOOD 数据覆盖。
- Structure：Branch、chainage、高程基准和版本化 Solver Capability；active 的 UNVERIFIED/UNSUPPORTED 结构 fail closed。
- Observation：H/Q 变量、Branch/chainage、垂直基准、GOOD/MISSING 质量语义。

QA 输出包含稳定 code、ERROR/WARNING/INFO、类别、实体类型/ID、说明、建议、上下文和可选 GeoJSON location。生产工作台可从有 location 的问题跳转 GIS 定位；无可靠几何时保持 null，不制作假坐标。

项目可配置断面最小/最大间距、最大投影距离、河底跳变和反坡警告阈值。阈值是项目策略，不是系统暗含的通用工程标准。对 QA 的人工例外必须形成独立 `QA_OVERRIDE` 审计；当前第一版不提供静默忽略按钮。

## 能力限制

Bridge、Culvert 和 CASIER 仍为 `UNVERIFIED`；Gate、Pump、Sluice 为 `UNSUPPORTED`。只有真实项目确实因 Bridge/Culvert/Pump 被 Capability Gate 阻断时，才记录 `SECONDARY_ENGINE_REQUIRED` 并评估后续 D-Flow 阶段；本阶段不接入第二求解器。
