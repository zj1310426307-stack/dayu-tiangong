# HYDRO-MODEL-02-D1 已知限制

- 日期：2026-08-26
- 状态：限定单河闸泵闭环可用；以下能力仍为 `NO-GO`

## 1. 水动力作用域

- 只支持单 Branch，不支持 Junction、一般多节点 Saint-Venant、环网或任意结构网络；
- D1 强制全湿、正向、严格亚临界；不支持湿干、倒流、超临界和水跃；
- 联合能力只允许一个 completed-interface Gate 和一个 external Pump，且不能占用同一
  Gate face 控制体；
- completed Gate 仍限定平床、相同 Profile、零 Manning 系数、淹没正向孔流；
- Gate 控制是一次关闭→目标开度，没有回落关闭/减小、自由出流、多 Gate 连续调节；
- 上游必须全程正流；下游水位过程必须湿润且不高于末断面初始水位。

## 2. Pump 作用域

- 只实现 external sink；internal Pump runtime 与内部能量/动量闭环 `NOT READY`；
- 只支持同型并联，异型机组组合、变速、启停不同机组、泵站率定不支持；
- Q-H/Q-η 仅分段线性且禁止外推；没有样条、厂家包线、汽蚀/NPSH、淹没深度率定；
- 系统损失只含显式静扬程与二次项；没有管网瞬变、阀门、局部构件组合；
- Pump 控制只读取绑定 cell 水位，不是通用 PLC/SCADA 逻辑。

## 3. 结果与工程接入

- `v4-lite-7` 是纯模型输入/结果合同，尚未接入 v4 原生 SimulationCase、Celery selector、
  进度/取消、结果持久化和 Gate/Pump UI；
- 没有修改 FastAPI/OpenAPI；现有 Web 任务链不会自动选择 D1；
- GitHub workflow 已创建，但本分支未上传，所以 hosted CI 为 `NOT RUN`；
- 没有 HEC-RAS、MIKE11/DHI 等外部模型对比，也没有真实河道和泵站率定；
- 没有 PLC/SCADA 下发，结果不得用于生产水利调度决策。

## 4. 不得宣称

本阶段不得宣称 HEC-RAS 等价、MIKE11 等价、一般多节点求解、完整 Pump station
率定、任意 Gate/Pump 网络或生产水利决策能力。

准确表述为：

> 在受限单 Branch、全湿、严格亚临界作用域中，大禹·天工实现了一个
> completed-interface Gate 与一个基于 Q-H/Q-η 曲线逐 SSP-RK2 stage 求工作点的
> Pump，并完成联合调度、水量与能量闭环。

## 5. 下一阶段

推荐进入 `HYDRO-MODEL-02-D2`：v4 原生任务链与调度平台接入，包括 SimulationCase
冻结、solver selector、Celery capability、progress/cancel、结果持久化、Gate/Pump UI
和 v3/v4 shadow。D2 不应顺带扩大 D1 的科学作用域。
