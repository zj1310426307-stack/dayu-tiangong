# HYDRO-MODEL-02-D3B 真实小型单河闸泵工程验证计划

- 日期：2026-08-31
- 状态：`STARTED / INPUT GATE NO-GO`
- 基线 tag：`hydro-model-02-d3a-rc1`
- 开发分支：`feature/HYDRO-MODEL-02-D3B-real-small-river-gate-pump-validation`

## 目标

在不扩大 D3A-RC1 物理作用域的前提下，用一个权威、可追溯的小型真实单河案例验证
一个 completed-interface Gate 与一个 external Q-H/Q-efficiency Pump 的数据接入、
参数绑定、边界、运行记录、率定/独立验证和 native v4 平台闭环。

D3B 真实工程验证不等于生产发布，不授权 PLC/SCADA 控制、生产调度或防洪决策。

## 执行顺序

1. 审查数据授权、来源清单、脱敏和发布边界；
2. 冻结私有 manifest、来源 SHA-256、CRS、高程、单位和时间基准；
3. 选择天然单 Branch 案例，确认水流方向、断面/Profile、床高和 Manning 依据；
4. 绑定一个 Gate、一个 external Pump、上下游边界、观测点和实际运行记录；
5. 生成冻结 native v4 输入并通过 readiness/fail-closed negative controls；
6. 运行未率定基线，先审计 runtime envelope、水量、结构残差和事件时序；
7. 由水工/水文责任人事前冻结率定段、验证段、参数范围、指标和接受阈值；
8. 完成率定、独立验证、敏感性和不确定性报告；
9. 通过 Python 3.11/3.12、Worker/PostGIS/artifact/API/UI 与 build identity 一致性门；
10. 独立审查后再决定是否形成 D3B release candidate。

## 强制停止条件

- 数据授权、来源 hash、CRS/高程或时间基准不明确；
- 案例需要伪连接才能成为单 Branch；
- Gate/Pump、边界或观测来自猜测、合成替代或不同工况；
- 运行越出 D3A-RC1 envelope；
- 率定与验证数据混用，或接受阈值在看到结果后修改；
- 任一原始受控工程文件进入 Git 可达历史。

触发任一条件即保持 `NO-GO`，不得降级成 warning 后继续发布。

## 完成口径

分支创建、任务运行成功或 synthetic regression 全绿，都不能替代数据授权、模型率定和
独立验证。D3B 只有在输入、数值、平台、复现和工程结论五类证据同时闭合后，才可进入
release candidate 审查。
