# HYDRO-MODEL-01 浏览器可视化验收记录

日期：2026-08-19

## 结论

本轮已建立并实跑“FastAPI → Redis/Celery → `HydraulicEngine` → PostgreSQL 16
→ 前端同源 API”的 24 h 真实软件验收环境，但 **未完成内置浏览器视觉验收，
也未生成页面截图**。阻断发生在进入项目页面前：Codex 内置 Browser 插件的受信
运行路径校验失败。

用户已明确要求所有浏览器任务均使用 Codex 内置浏览器。因此本轮在清空浏览器会话后
以显式 `iab` 选择器重试，仍获得同一运行时错误；不再使用 Chrome、Windows 界面工具
或独立 Playwright 替代，也未用脚本截图伪造浏览器证据。

因此，本记录可作为真实 PostgreSQL/Celery/API/HTTP 数据闭环证据，但不能作为
已完成浏览器 DOM、视觉渲染、交互或控制台验收的声明。

## 本轮临时验收环境（已清理）

- 前端页面：`http://127.0.0.1:5174/dispatch/runs/4?datasetVersionId=2`
- 同源 API：`http://127.0.0.1:8003/api/v1`
- 数据库：PostgreSQL 16.14 / PostGIS 3.6.4 / TimescaleDB 2.28.3，Alembic `20260818_0019`
- 队列：Redis 7.4.10 + 独立 Celery 5.5.3 solo Worker
- 验收数据：仓库确定性 PostGIS 验证 fixture，不是现场实测资料或生产率定数据
- 空间边界：Gate 桩号为 `null/unconfirmed`，Pump 桩号为
  `null/unavailable_not_inferred`，不能据此认定真实工程闸泵定位通过
- 输入协议：`dayu.model-input.v3`
- 结果协议：`dayu.hydraulic-result.v2`
- 求解器：`synchronous-network-continuity-manning-v1`

运行 #4 由真实 `POST /api/v1/dispatch/plans/{plan_id}/runs` 创建。baseline task #6 和
controlled task #7 均由 Redis 分发给外部 Worker，并通过生产持久化入口写回 PG16。
早先的 engine-driven UI fixture 仍保留为纯前端合同证据，但不再作为本轮真实 API 页面数据源。

## 计算与 HTTP 证据

| 检查项 | 实测结果 |
| --- | --- |
| 模拟时长 | 86400 s（24 h） |
| 输出帧 | 1,441 帧，60 s 间隔 |
| 断面结果 | baseline/controlled 各 4,323 行 |
| 闸门结果 | 1,441 行，0–24 h |
| 泵站结果 | 1,441 行，0–24 h |
| 节点结果 | 2,882 行 |
| 精确里程碑 | 0、6、12、24 h 均存在原始样本 |
| 调度事件 | 4 行，来源均为 `rule`；规则触发计数 2 |
| 水量平衡 | `pass`，相对残差 0 |
| 最大 CFL | `0.3938789038` |
| 前端入口 | HTTP 200，返回 Vite SPA `#root`；这不等于视觉渲染通过 |

24 h 最终状态数据：

| 设施 | 开度 / 机组 | 流量 | 累计能耗 | 流态 | UI 控制来源 |
| --- | ---: | ---: | ---: | --- | --- |
| 闸门 #1 | 1.000 m | 0.040 m³/s | 0 kWh | `submerged_orifice` | 本次调度 / 控制规则 |
| 泵站 #1 | 1 台 | 0.010 m³/s | 9.948169 kWh | `running` | 本次调度 / 控制规则 |

自动化核验同时从 API 和 PostgreSQL 交叉读取：两个 task 均有独立 `queue_job_id`、
Worker ID 和 64 位快照哈希；API 的 2,882 条结构物结果和 4 条事件与数据库计数一致。

## 已执行检查

- `python -m pytest tests/test_gate_pump_ui_fixture.py tests/test_hydro_model_frontend_contract.py -q`：4 passed。
- `npm run typecheck`：通过。
- `npm run build`：通过，3927 modules transformed，最新复验 52.24 s；只有既存的大包体积警告。
- 全仓回归：`308 passed / 71 skipped / 0 failed`，最新复验 17.60 s。
- 真实外部队列 run #4 与第二次运行 run #5 均成功；两轮数量、CFL 与水量门禁一致。
- 两轮共享同一 Redis 队列；run #5 的 `engine_commit=uncommitted`，因此不把它写成
  第二条隔离 Worker 链或已锁定源码提交的复现证据。

## 浏览器阻断证据

内置浏览器按技能规定初始化；在用户再次明确“只用内置浏览器”后，
清空会话并以 `agent.browsers.get("iab")` 显式重试，仍得到受信路径校验失败。
为避免公开本机用户名和插件缓存绝对路径，原始错误仅保留在本地受控运行记录中；
公开错误摘要为：

```text
Trusted RPC dependency must resolve within a configured trusted code path:
[local plugin cache path redacted]
```

该错误来自 Browser 插件自身运行时，发生在浏览器发现、页面导航和 DOM 检查之前，
因此没有点击、输入、截图或控制台证据。
待内置 Browser 运行时恢复后，需要按同一流程重建隔离环境，打开新生成的真实 run 页面并补做：
四曲线实际绘制、状态摘要、
0/6/12/24 h 标记、24 h 覆盖标签、控制来源文字、控制台错误以及整页截图检查。
