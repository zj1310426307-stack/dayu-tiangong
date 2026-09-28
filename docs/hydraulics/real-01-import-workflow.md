# REAL-01 导入、QA 与冻结工作流

真实资料只能按下面顺序推进。每步都有缺口即停留在当前步，不允许用后续计算来“验证”缺失输入。

1. **Inventory**：列出每个来源文件、责任人、日期、用途、资料域；仅在受控项目资料目录保存原件。
2. **Hash**：对每个文件计算 SHA-256，并登记解析配置、CRS、轴映射、单位和垂直基准。
3. **Manifest**：填写 `templates/real-engineering-pilot-manifest.yaml`，未确认项使用 `NEEDS_CONFIRMATION`。
4. **Parse / Normalize**：把河网、断面、闸门、边界和观测映射到统一 Domain；不得修改原始值。
5. **Import**：提交 `HydraulicImportJob` 或保留同等来源证据；原始文件不进入 Git。
6. **QA**：执行坐标、高程、拓扑、断面、Marker、糙率、建筑物和边界校核，修复后重新生成 QA。
7. **Review**：审核人处理缺失清单和假设记录，确认适用范围。
8. **Freeze**：读取 readiness；所有 blocker 消除后调用 REAL-01 freeze，写入完整工程图 hash。
9. **Clone / Case**：需要修改资料时克隆完整工程图；需要计算时从冻结版本另行创建方案和任务。

任何出现 `FRAMEWORK_READY_DATA_REQUIRED`、`MISSING` 或 `PARTIAL` 的域，均不得标记为已率定、已验证、生产就绪或真实 D-Flow pilot 就绪。
