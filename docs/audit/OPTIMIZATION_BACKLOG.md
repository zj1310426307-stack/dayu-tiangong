# 大禹·天工持续优化 Backlog

更新日期：2026-08-24  
等级定义：P0 安全/数据/核心不可用；P1 主要业务或重要架构；P2 一般维护性；P3 体验与非关键优化。

## P0

| ID | 问题位置与表现 | 根因与影响 | 处理方式 | 兼容/迁移 | 验收 |
|---|---|---|---|---|---|
| OPT-P0-001 | 全部 171 个 API operation；84 个写操作无 security | 后端无 Principal/OIDC/RBAC，匿名用户可调用控制面 | 引入真实 OIDC/JWT 适配器、逐 operation scope、默认拒绝匿名 mutation | API 增加 401/403；不必先迁移业务表 | 无/伪/过期 token=401，缺 scope=403，OpenAPI 含 security |
| OPT-P0-002 | GIS Governance、调度、AI、水动力中的 actor/reviewer/operator/user 由请求体自报 | 审计身份不可信，可伪造审核/发布人 | 从服务端 Principal 派生，旧字段 deprecated 且不允许覆盖 | 需兼容期；可能增加审计迁移 | 持久化 actor 等于 token subject，伪造值=403 |
| OPT-P0-003 | QGIS Bridge 任意非空 token 即显示 IAM/OIDC 并启用 mutation | 客户端把“有字符串”误当“已认证” | 只依据服务端 `/auth/me` 和 scope；无 IAM 显示 `UNVERIFIED LOCAL IDENTITY` | QGIS 插件配置迁移 | 任意字符串不能启用生产动作 |
| OPT-P0-004 | `import_service` 与 `data_converter` 先无界 `read()`，再检查 20/100 MB | 直接 backend 请求可造成进程内存资源耗尽 | 统一 `read_limited_upload`，只读 `limit + 1`；应用与代理双重限额 | 路径/请求字段不变，无 DB 迁移 | 超限在落盘/解析前拒绝；读取调用参数精确为 `limit+1` |
| OPT-P0-005 | 任务、数据、治理对象没有 tenant/project/owner 权限维度 | 多租户产品边界未定义 | 负责人先决定单租户/多租户；再设计 claim 与行级授权 | 可能需要 DB 迁移 | 跨 tenant/project 的 ID 访问全部拒绝 |

## P1

| ID | 问题位置与表现 | 根因与影响 | 处理方式 | 兼容/迁移 | 验收 |
|---|---|---|---|---|---|
| OPT-P1-001 | 水动力/优化任务与调度运行列表读取全库 | Dataset Version 只在 UI 局部过滤，状态所有权错误 | 增加可选 `dataset_version_id` 并在 SQL 查询层过滤，前端总是传当前版本 | 仅加可选查询参数，无迁移 | 不同版本任务互不可见，旧不传参数调用仍兼容 |
| OPT-P1-002 | imports/conversions/ai-reports 三套硬编码根目录 | 无统一文件平台所有者，部署/备份/配额漂移 | `DAYU_STORAGE_ROOT` + 命名空间 + 原子写入 + 路径边界 | 默认路径保持不变，无迁移 | env override、生存路径、路径逃逸和临时文件测试通过 |
| OPT-P1-003 | Nginx 默认约 1 MB，而应用合同为 10/20/100 MB | 代理与应用配置未同步；经 UI 的合法大文件失败 | API location 设置略高于最大 multipart 上限；应用保留逐接口精确限额 | 配置兼容性改进 | 代理配置静态门 + 容器实测 10/20/100 MB 边界 |
| OPT-P1-004 | backend 镜像不含水动力 Excel 模板 | Dockerfile COPY 集不完整 | 只复制受控模板目录 | 无 API/DB 变化 | 容器内两个模板下载为 200 |
| OPT-P1-005 | 只有 basic logging，无 request-id/principal/task/file 关联 | 无统一可观测性所有者 | request context、结构化事件、任务关联和敏感字段脱敏 | 日志格式变更 | 请求、权限、任务和文件可用同一 correlation id 追踪 |
| OPT-P1-006 | 三套任务投递与失败补偿；retry broker 失败可能留 queued | 任务状态所有权分散 | 建立统一 enqueue coordinator、条件更新、outbox/幂等键和补偿 | 不改历史结果语义；可能迁移 outbox | 并发投递、broker 失败、重启恢复、重复消费测试 |
| OPT-P1-007 | 无 CI；71 项集成测试默认跳过 | 环境依赖未自动编排 | 分层 CI：离线门、PostGIS/Redis、GeoServer/GDAL、浏览器门 | 无运行 API 变化 | PR 自动执行并保留报告，失败阻断合并 |
| OPT-P1-008 | 生成 client 的 operation 模板手工维护，已出现查询类型漂移 | OpenAPI 仅生成 schema，函数仍复制粘贴 | 逐步改为 operation 驱动生成，并增加 required operation/parameter 门 | 生成文件变化，不改服务端字段 | 生成后 `git diff --exit-code`、类型检查通过 |
| OPT-P1-009 | 旧 GIS 读路由可绕过 published Catalog 状态检查 | 双读链兼容期没有统一门禁 | 旧路由复用 `_public_version` 或仅对授权内部用户开放 | 可能使 draft 读取返回 404/403 | 匿名只能读取 published，Catalog/WMS 正常 |
| OPT-P1-010 | README 已收敛 GIS，但 DGIS 历史能力仍注册 | 兼容路由未标识生命周期 | 建立 deprecated 清单、调用统计和删除门；禁止新增第二 GIS 链 | 分阶段兼容 | 核心运行只依赖 PostGIS/GeoServer/OpenLayers |

## P2

| ID | 问题 | 推荐处理 | 验收 |
|---|---|---|---|
| OPT-P2-001 | Ant Design/ECharts chunk 超过 1 MB | 按页面/图表注册按需拆分并设性能预算 | 可复现构建产物对比，无功能回归 |
| OPT-P2-002 | 三类任务轮询重复且防旧响应不一致 | 抽取统一 task polling hook，使用 sequence/abort | 切版与慢响应不覆盖新状态 |
| OPT-P2-003 | Data/Model/Dispatch/Optimization 页面头重复 | 复用现有设计系统抽取 PageHeader | 视觉回归与可访问性检查 |
| OPT-P2-004 | 前端无 lint/单测；后端 Ruff 未锁入依赖 | 增加锁定工具和最小门禁 | 本地与 CI 命令一致 |
| OPT-P2-005 | FastAPI、系统接口与前端包版本不一致 | 定义单一发布版本来源 | OpenAPI、健康、UI 和 release note 一致 |

## P3

- 统一空状态、网络错误和重试提示；
- 键盘操作、焦点、移动端和高对比度验收；
- 历史阶段文档建立“当前/归档”索引；
- 增加依赖更新机器人、覆盖率趋势和非阻断性能报告。

## 本轮完成标识

- `OPT-P0-004`：本轮实施；
- `OPT-P1-001`：本轮实施；
- `OPT-P1-002`：本轮实施基础层，文件登记/配额/保留仍后续；
- `OPT-P1-003`：本轮实施配置门，真实容器边界待有 Docker 环境验证；
- `OPT-P1-004`：本轮实施，容器下载待有 Docker 环境验证；
- 其余条目保持 backlog，不以计划冒充完成。

