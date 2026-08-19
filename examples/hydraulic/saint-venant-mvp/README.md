# Saint-Venant MVP 合成示例

该目录是 `dayu.model-input.v4-lite` 的最小可运行软件示例，包含一条 1 km 合成河道、3 个非规则断面、动态上游 Q(t) / 下游 H(t)、1 座固定开度闸门和 1 座定流量外排泵。

在仓库根目录运行：

```powershell
$env:PYTHONPATH='backend;.'
backend\.venv\Scripts\python.exe examples\hydraulic\saint-venant-mvp\run_demo.py
```

脚本现场读取冻结 JSON，通过 `HydraulicEngine` 的 v4-lite 直连路由运行 HLL + hydrostatic reconstruction + SSP-RK2，并输出结果 schema、时间轴、CFL、最小步长、重试数、水量平衡、输入快照 hash 和网格 hash。
仓库中的 `result_summary.json` 是当前示例的可复核摘要；运行时应以现场输出为准，并核对两个 hash。

边界：

- 这是合成软件闭环，不是真实工程率定。
- Gate 只替换内部界面质量通量，动量/能头强耦合未完成，结果必须保留 `structure_momentum_closure_mass_only_mvp` 诊断。
- Pump 是定流量外排源汇，不是 Q-H 系统工作点。
- 当前 v4-lite 只在 Python 引擎直连路由启用；HTTP/Celery/数据库任务链仍仅允许 v1/v2/v3，避免未完整持久化协议被误标为成功。
