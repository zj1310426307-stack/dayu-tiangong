# HYDRO-DATA-REAL-01 审核记录

审核状态：`FRAMEWORK_READY_DATA_REQUIRED`

## 已核实

- PR #24 已在 REAL-01 开始前合并到 `main`；本任务从其合并提交创建独立分支。
- 工作区识别到的可疑真实资料只覆盖单条河道的部分中心线和横断面，未以五河两闸资料、边界过程或闸门资料入库。
- 不将原始工程文件、坐标、横断面值或哈希写入 Git；测试只使用代码构造的非工程样例。
- `pilot_execution_enabled` 未启用；本任务未运行 D-Flow、生产、优化或 PLC/SCADA。

## 本次实现审查点

| 项目 | 结果 | 说明 |
|---|---|---|
| 统一 Domain 复用 | PASS | 不引入平行试点库。 |
| 自动缺失清单 | PASS | readiness 接口只读、拒绝默认补齐。 |
| 全图 hash | PASS | 与旧 GIS core hash 分离并可冻结保存。 |
| 完整工程图克隆 | PASS | 版本内外键重映射；不复制任务/结果。 |
| 真实五河两闸入库 | DATA_REQUIRED | 当前没有完整受控来源。 |
| QA、审核、冻结实操 | DATA_REQUIRED | 必须待真实资料齐备。 |
| 率定/验证/MIKE11 比对 | DATA_REQUIRED | 未提供观测或外部成果。 |

下一步为资料责任人提供完整五河两闸来源包后，按 `real-01-import-workflow.md` 执行，不得跳过 Inventory、Hash、Manifest、QA 和 Review。
