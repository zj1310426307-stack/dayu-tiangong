# 大禹·天工持续优化现状审查

> **2026-08-24 基线归档：** “当前”仅指下述审查日期；其中 v1–v4-lite 自研 Solver 状态已由 [HYDRO-1D-RESET-01](../migration/HYDRO-1D-RESET-01.md) 取代。

审查日期：2026-08-24  
审查基线：`main@07948e663fedc220d8ca6cdbdb34fd3fb4e2beee`  
工作分支：`feature/continuous-optimization-01`

## 1. 审查结论

当前仓库已经形成可运行的 FastAPI、SQLAlchemy/PostGIS、Celery/Redis、React/Ant Design、OpenLayers/GeoServer 主链，数值模型与主要业务回归也有较好的离线测试基线；但它还不是一套已经接入统一 IAM、统一文件生命周期、统一审计日志和持续集成门禁的生产平台。

本次静态生成的 OpenAPI 共 137 条路径、171 个 operation，其中 84 个为写操作；`securitySchemes` 为空，受安全策略保护的 operation 为 0。数据库服务角色的最小权限不能替代终端用户身份与 RBAC。现有 `actor`、`reviewer`、`operator`、`created_by` 等字段由客户端自报，不能作为生产审计证据。

因此当前生产结论为：

- 统一数据库和 GIS 主链：`GO`，继续复用；
- Celery/Redis 任务底座：`LIMITED GO`，任务状态与投递所有权仍需收敛；
- 统一文件管理：`LIMITED GO`，本轮先完成入口与存储根收敛；
- 统一 IAM/RBAC：`NO-GO`；
- 多租户/项目级隔离：`NO-GO`；
- 生产部署、高可用、灾备与真实 IAM 联调：`NO-GO`。

## 2. 当前系统架构

```text
React + Ant Design + OpenLayers
            |
   generated OpenAPI client
            |
         FastAPI
  | 数据/GIS | 模型 | 调度 | 优化 | AI |
            |
 SQLAlchemy Session + PostgreSQL/PostGIS/TimescaleDB
            |
 GeoServer       Redis + Celery Worker
```

GIS 权威链为 `PostGIS -> publish 只读视图 -> GeoServer -> FastAPI Gateway/Catalog -> OpenLayers`。QGIS Desktop 只承担 `staging_qgis` 专业生产，不得建立第二 GIS 数据库或第二 WebGIS 渲染体系。

## 3. 主要模块与所有权

| 能力 | 当前所有者 | 当前状态 |
|---|---|---|
| HTTP 装配 | `backend/app/main.py`、`backend/app/api/router.py` | 171 个 operation，缺统一安全依赖 |
| 数据库会话 | `backend/app/database/session.py` | 单一 SQLAlchemy Session；API/Worker 复用 |
| 数据库权限 | `database/bootstrap_app.py`、`database/bootstrap_qgis.py` | 服务账号最小权限较完整；不是用户 RBAC |
| GIS | `app.gis_catalog`、GeoServer、PostGIS `publish` | 主链已收敛；仍有旧读路由和历史 DGIS 语义 |
| 文件基础 | `app.files` | 四类 HTTP 上传统一有界读取、本地根、路径约束与原子替换；不是完整文件生命周期 |
| 水动力任务 | `app.model_engine` + `app.worker.lifecycle` | 有 claim/heartbeat/cancel/recovery；监控列表可按 Dataset Version 过滤 |
| 调度任务 | `app.dispatch` | 自有双任务投递和补偿语义 |
| 优化任务 | `app.optimization` | 自有投递、取消和候选状态语义 |
| 日志 | `app.utils.logging` | 仅 `basicConfig`，无 request/principal/task/file 关联 |
| 前端设计 | Ant Design + 全局主题 + 公共 CSS | 技术体系统一；页面头、轮询和错误状态有重复 |
| API 客户端 | `frontend/scripts/update-openapi.mjs` | schema 来自 OpenAPI，但 operation 模板仍手工维护 |

## 4. 前后端调用链

页面基本通过 `frontend/src/api/generated/client.ts` 调用后端，未发现页面手写 `fetch/axios/XMLHttpRequest`。该文件由 `npm run openapi:update` 生成，任何 API 变化必须先修改 FastAPI 契约，再重新生成并运行类型检查。当前唯一明显绕行是普通导入模板使用原始 `href` 下载；后续应进入统一下载客户端。

任务页存在状态所有权错误：水动力任务、优化任务和调度运行原先读取全库，再由部分页面在浏览器过滤。Dataset Version 是平台的权威业务版本边界，过滤必须在数据库查询层完成，前端只显式传递当前版本。

## 5. 数据库结构与数据风险

- Alembic 当前为单一 head：`20260818_0019`。
- 核心数据、GIS、hydraulic、治理和任务数据位于同一 PostgreSQL/PostGIS 实例，按 schema 与服务角色隔离。
- `dayu_backend` 是非 owner 运行账号并继承发布组；这能限制服务进程权限，但匿名 HTTP 可调用时会放大控制面风险。
- 任务表已有 `dataset_version_id` 或可经计划关联到 Dataset Version，本轮任务过滤不需要迁移。
- 当前没有 tenant、organization、project owner 或用户角色表；不得宣称已具备多租户隔离。

## 6. 启动与部署

标准启动为：

```powershell
docker compose --env-file .env -f docker/docker-compose.yml up -d --build
```

初始化链为 database、migrate、seed、QGIS/App bootstrap、GeoServer、Catalog、backend/worker、frontend。审查发现：

- Nginx 已声明 102 MiB 总门，应用仍按 10/20/100 MB 执行精确有界读取；
- backend 宿主端口已绑定 `127.0.0.1`，本机直连仍可绕过 Nginx，总请求体解析前限额仍需后续补齐；
- backend 镜像已复制 `outputs/HYDRO-DATA-01-20260818`，但当前环境没有 Docker CLI，容器内下载仍待验证；
- 当前审查环境没有 Docker CLI，不能把 Compose/镜像/容器验证写成已通过。

## 7. 已实现能力

- Dataset Version、GIS 暂存/质检/审核/晋级/发布状态机；
- PostGIS/GeoServer/OpenLayers 主链和受控 Catalog/WMS/FeatureInfo；
- 水动力数据导入、处理、校核、交换与 v1-v4-lite 模型原型；
- 模型、调度、优化 Celery 任务与结果展示；
- AI 只读检索、知识文档、报告与不可执行安全边界；
- 前端按业务域懒加载、统一 Ant Design 主题与生成 API 类型；
- 完整离线回归基线：620 项通过。

## 8. 未完成或不可用能力

- 统一 OIDC/JWT 身份验证、RBAC/scope、可信 actor 派生；
- 登录、退出、401/403 会话处理和权限导航；
- tenant/project/owner 数据隔离；
- 文件登记、可信操作者、配额、保留、成功产物清理、内容扫描和文件级授权的完整生命周期；
- request-id、结构化业务事件和安全审计；
- 默认 CI、前端测试/lint、依赖和镜像安全扫描；
- Docker、新卷迁移、GeoServer 和 PostGIS 多版本真实查询验证；
- 真实模型率定、生产 TLS/密钥托管、备份恢复和高可用。

## 9. 重复、历史与冲突模块

- `model_engine`、`dispatch`、`optimization` 各有投递与失败补偿，任务所有权尚未统一。
- 普通导入、GDAL 转换、AI 报告已统一派生本地根；水动力原件 BLOB、知识原件登记和完整生命周期仍未统一。
- README 宣告 Martin/TiTiler/GeoNode/Cesium 退出核心运行时，但历史 DGIS 路由仍暴露部分旧能力语义；必须按兼容期治理，不能再扩展第二 GIS 链。
- API client 的 schema 生成与手写 operation 模板混合，存在后端已变更而客户端模板未更新的漂移风险。
- 历史模型文档中的 `NO-GO` 多为显式科学边界，不是可以静默补齐的普通 TODO。

## 10. 性能现状

- 前端构建转换 3927 个模块；Ant Design 和 ECharts 各自产生超过 1 MB 的压缩前 chunk，Vite 发出大块警告。
- 三类任务页面仍使用不同的 3/4/5 秒轮询，但本轮均增加了切版迟到响应保护。
- 四类上传路由已统一为 `limit + 1` 读取；ASGI multipart 解析前的全请求体限制仍缺失。
- 本轮没有真实负载与数据库执行计划数据，不宣称任何性能提升比例。

## 11. 安全风险

1. 所有写接口匿名可达，GIS review/promote/publish、任务执行/取消/重试和知识上传均无 RBAC。
2. QGIS Bridge 只因本地存在任意 token 字符串就显示 IAM/OIDC 语义，而后端不验证 Bearer，属于假认证。
3. 审计身份由客户端填写，可伪造。
4. 应用级上传读取已有上限；本机直连 backend 仍可绕过代理总门，且 multipart 解析发生在路由读取前。
5. 旧 GIS 数据读接口未统一经过 published Catalog 门禁。
6. CORS 和安全响应头仍为开发基线；无速率限制和统一审计日志。

## 12. 测试覆盖与基线

本轮修改前实际执行：

- 后端/仓库：`620 passed, 71 skipped`；
- 前端 `npm run typecheck`：通过；
- 前端 `npm run build`：通过，存在现有大 chunk 警告；
- Git 工作树：干净。

71 项跳过项主要依赖真实 PostGIS、GDAL、QGIS、GeoServer、数据库角色或外部环境。仓库没有 CI 自动执行这些集成门。

## 13. 部署风险

- 生产 IAM 未配置，所有 mutation 必须保持 `NO-GO`；
- Dockerfile/Compose/容器内模板尚未在本机验证；
- worker recovery 未见 Compose 启动时调用，僵尸任务可能长期保留；
- 默认端口和开发口令策略不适合公网部署；
- 无自动备份、恢复演练、镜像 digest 固定或漏洞扫描。

## 14. 技术债务摘要

最高优先级依次为：统一 IAM/RBAC；可信审计身份；上传与文件生命周期；Dataset Version 任务隔离；统一请求/任务日志；任务投递协调器；CI 与真实集成门；旧 GIS 双出口清理；前端轮询/错误/头部组件收敛。

## 15. 本轮选择

真实 IAM 需要项目负责人提供 OIDC issuer、audience、claim/scope 映射、单租户或多租户决定及测试租户。缺少这些信息时实现共享 token、可信请求头或客户端自报角色会制造新的安全债务，因此本轮不伪造认证完成状态。

本轮实施两个不依赖外部服务且能立即降低风险的闭环：

1. 统一四类上传的有界读取、统一本地存储根与原子写入，协调 Nginx 限额并补齐容器模板；
2. 水动力、优化、调度任务列表按 Dataset Version 在数据库层过滤，OpenAPI 生成客户端和前端工作区同步。
