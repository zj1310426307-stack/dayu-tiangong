# 持续优化 01 执行计划

计划日期：2026-08-24  
分支：`feature/continuous-optimization-01`  
基线：`07948e663fedc220d8ca6cdbdb34fd3fb4e2beee`

## 1. 目标

本轮不重写业务体系，完成两个独立闭环：

1. `FILE-FOUNDATION-01`：所有 HTTP 文件入口统一有界读取，落盘模块使用同一存储根与原子写入，代理限额和容器模板与应用合同一致；
2. `TASK-VERSION-BOUNDARY-01`：水动力任务、优化任务、调度运行的监控列表由后端按 Dataset Version 过滤，生成客户端与前端工作区同步；该切片不构成权限隔离。

## 2. 统一架构约束

- 数据库继续使用 `app.database.session` 和现有 PostgreSQL/PostGIS，不增加第二数据库；
- GIS 继续使用 PostGIS -> GeoServer -> FastAPI Gateway/Catalog -> OpenLayers，不增加新 GIS 技术链；
- 任务继续使用 Celery/Redis 和现有任务表，不引入第二队列；
- 前端继续使用 Ant Design、DatasetVersionContext 和生成 OpenAPI client；
- 文件模块只提供平台基础能力，不承担业务解析或数据库事务；
- API 层负责输入与响应，service/repository 负责状态与查询；
- 任何 API 变化先修改后端，再运行 `npm run openapi:update`；禁止手改生成文件；
- 统一 IAM 缺失继续标记 `NO-GO`，不使用共享 token、请求头或 body actor 冒充 OIDC/RBAC。

## 3. 实施范围 A：文件入口与存储基础

计划修改：

- 新建小型 `backend/app/files/` 平台模块；
- 提供唯一 `DAYU_STORAGE_ROOT` 配置和受控命名空间；
- 提供 `read_limited_upload`，固定只读取 `limit + 1`；
- 提供同目录临时文件 + 原子替换，并拒绝越出命名空间的路径；
- 普通导入、DGIS 转换、AI 知识上传、水动力导入复用同一读取器；
- imports、conversions、ai-reports 默认根统一派生，保留原路径和测试 monkeypatch 兼容；
- Nginx API 入口允许最大 100 MB 业务文件及 multipart 开销；
- backend 镜像复制两个水动力模板；
- `.env.example` 区分本地 `DAYU_STORAGE_ROOT` 和 Compose 宿主机 `DAYU_STORAGE_HOST_PATH`；容器内根固定并由 backend/worker 共用。

验收：

- 超限、空文件、后缀错误在解析/落盘前拒绝；
- 测试记录 `UploadFile.read` 的参数为 `max_bytes + 1`；
- 原子写入无残留临时文件；
- 路径逃逸被拒绝；
- 默认本地和容器路径保持现有语义；
- 旧 endpoint、字段和成功响应保持兼容。

## 4. 实施范围 B：Dataset Version 任务边界

计划修改：

- `/api/v1/model/tasks` 增加可选 `dataset_version_id`；
- `/api/v1/optimization/tasks` 增加可选 `dataset_version_id`；
- `/api/v1/dispatch/runs` 增加可选 `dataset_version_id`，通过关联计划在数据库过滤；
- service/repository 接受并执行 SQL 条件，不在前端加载后过滤；
- OpenAPI 生成器为三种查询产生准确函数签名；
- 水动力、结果、优化和调度页面总是传 `DatasetVersionContext` 的当前 ID；
- 切换版本时清理旧状态或使用 request sequence，避免迟到响应覆盖新版本。

兼容策略：

- 查询参数只增加不删除；旧调用不传时仍返回原全量结果；
- 生成客户端保留旧 `list*Tasks(baseUrl)` 调用，同时支持新的查询对象；
- 不改变任务、结果和计划的数据库字段或状态语义；
- 不改变 v1/v2/v3/v4-lite 模型输入与结果语义；
- 不做数据库迁移。

验收：

- service SQL 过滤正反例；
- 三个 list API 的 OpenAPI 参数存在；
- 生成客户端函数参数与后端一致；
- 前端不再对调度运行做全量拉取后本地版本筛选；
- 快速切换版本时旧响应不覆盖新列表。

## 5. 明确不在本轮实施

- OIDC/JWT provider、登录页、RBAC scope 与 tenant/project 模型；
- 将客户端 actor 字段改为可信 Principal；
- 文件 metadata 表、对象存储、杀毒、配额、保留和清理 worker；
- 任务详情、结果、取消、重试和候选等 ID 接口的版本/权限授权；
- 统一任务 outbox/投递协调器；
- 旧 GIS 路由退役；
- 完整 CI、生产部署、备份恢复和高可用；
- Saint-Venant 新科学能力、真实工程率定或 v4 后端任务链。

这些事项保持在 backlog；尤其 IAM/RBAC 在真实 issuer、audience、claim/scope 和租户决策缺失时不得用临时实现替代。

## 6. 验证计划

1. 新增文件/任务边界单元与 API 契约测试；
2. 运行相关后端测试；
3. 运行 `npm run openapi:update` 并检查生成差异；
4. 运行前端类型检查与生产构建；
5. 运行全量后端/仓库测试；
6. 运行 `git diff --check` 和密钥/临时文件检查；
7. 若环境有 Docker，再运行 Compose config、镜像构建、模板下载与上传边界；本机无 Docker 时必须记录为未验证。

## 7. 提交计划

1. `audit: establish continuous optimization baseline`
2. `fix: unify bounded file intake and storage root`
3. `fix: scope task listings to dataset versions`
4. `docs: record compatibility verification and release`

每次提交前确认没有密钥、缓存、构建产物或无关格式化。

## 8. 回滚

- 代码回滚按上述逻辑提交逐个 `git revert`；
- 本轮无数据库迁移，无数据 downgrade；
- `DAYU_STORAGE_ROOT` 未设置时继续使用历史 `backend/storage`；
- 删除新增查询参数或调用时，服务端旧全量 list 行为仍可工作；
- Nginx/Docker 配置可独立回滚，不影响数据库数据。
