# Phase 6 AI 水利助手架构

## 当前数据流

`/ai-assistant → OpenAPI 生成客户端 → FastAPI AI 路由 → AI service → 安全门禁 / RAG / 只读工具 → 来源约束回答 → 会话与工具审计`

AI 层是 Phase 3–5 的只读解释消费者，不拥有模型、优化或设备状态。业务上下文只接受数据版本、河道、仿真任务、优化任务和知识文档主键；工具表由服务端固定，模型不能注册任意函数。

## 模块所有权

| 模块 | 责任 |
|---|---|
| `ai/assistant` | 将已核验证据组织为回答；可选 OpenAI-compatible 提供方 |
| `ai/retrieval` | 文本切分、稳定哈希向量、余弦检索 |
| `ai/knowledge` | regulations/hydraulic/dispatch/engineering/templates 五类内置知识 |
| `ai/tools` | 河道、仿真、优化、报告四个只读工具白名单 |
| `ai/guardrails` | 输入控制/篡改/审批绕过拦截与输出二次检查 |
| `ai/report` | 六章 Markdown 与 PDF 报告生成 |
| `backend/app/ai` | HTTP 契约、数据库编排、审计、受控下载 |
| `frontend/src/pages/ai` | 对话、来源、工具日志、知识检索/上传和报告下载 |

## RAG 与来源

知识文档支持 PDF、DOCX、Markdown 和 TXT，单文件最大 10 MB。入库时保存名称、分类、版本、来源、更新时间和 SHA-256；片段保存内容、字符位置和 192 维确定性向量。回答来源同时支持知识片段、数据版本、仿真任务和优化任务，业务来源包含模型/算法版本与输入快照。

默认 `AI_LLM_PROVIDER=local`，系统用确定性模板回答，无需外部密钥。管理员配置兼容端点后，外部模型只接收已脱敏证据；失败时回落到本地生成，输出仍通过同一门禁。

## 安全边界

- AI 不能写 `simulation_*`、`optimization_*`、`dispatch_*`、`gate` 或 `pump`。
- 真实设备控制、结果篡改、Pareto 重排和审批绕过在工具调用前阻断。
- 外部或本地回答均执行输出复核；缺来源时返回数据不足。
- 所有回答和报告声明 `execution_authorized=false`，不连接 PLC/SCADA。
- 工具输入、输出、会话、耗时和报告文件均可审计。
