# QGIS Desktop Bridge Security Contract

- Contract status：Frozen for GIS-OPT-2 implementation
- Date：2026-08-15
- Decision baseline：远端 `main` / `f72b675e4681823e35cf74219a0721825dca8082`
- Runtime status：NOT IMPLEMENTED；当前仓库没有 QGIS Bridge plugin

## 1. Purpose and Trust Boundary

QGIS Bridge 是未来 QGIS Desktop 与平台 FastAPI 之间的受控辅助插件。它帮助编辑者查看批次、提交质检、查看问题、发起审核并定位平台对象；它不是数据库权限替代品，也不是 QGIS Server 管理器。

```text
QGIS Desktop plugin
      │ HTTPS + platform API token
      ▼
FastAPI governance/catalog API
      │ service-side authorization + state machine
      ▼
PostGIS governance records
```

插件永远不得持有数据库 owner、publisher、reviewer、GeoServer admin、QGIS Server admin 或服务间 credential。QGIS 对 staging 的数据库连接继续使用现有最小权限 `dayu_qgis_editor`/`dayu_qgis_reviewer`；Bridge 只走 API。

## 2. Current Identity Fact

现有治理请求中的 `actor/reviewer/published_by` 是本地开发审计字段，不是已验证 IAM 身份。任何客户端都可能自报这些字符串，文档和 UI 不得称其为“已鉴权用户”。

本地 DEMO 模式必须同时满足：

- UI 显示 `UNVERIFIED LOCAL IDENTITY`；
- 审计事件写入 `identity_assurance=unverified_local`；
- 日志不能称 `authenticated_user`；
- 不允许把该模式用于生产发布证据。

## 3. Production Authentication and Authorization

生产 Bridge 必须使用平台统一 IAM 签发的短期 token，经系统浏览器/OIDC PKCE 或等价桌面安全流程获得。token 的 subject、tenant、scope 和 assurance 由 FastAPI 验证，actor 由服务端从 token 派生；客户端提交的 actor 字段被忽略或必须与 subject 一致。

若生产 IAM 未接入：

- 可允许匿名/平台公开的只读 Catalog 和 published map；
- 必须拒绝创建/修改批次、质检、提交审核、review、promote、publish、retire 和管理 Registry；
- 不允许用本地 `operator` 文本、IP allowlist 或共享 token 冒充 IAM。

建议 scope：

```text
gis.catalog.read
gis.batch.read
gis.batch.edit
gis.validation.run
gis.review.submit
gis.review.decide
gis.version.promote
gis.version.publish
gis.version.retire
gis.registry.manage
```

职责分离：同一人是否可同时 edit/review/publish 由生产策略决定；首期生产默认不允许批次最后编辑者成为唯一 approver/publisher。

## 4. Operation Matrix

| Operation | Anonymous public | Local DEMO unverified | Editor | Reviewer | Publisher | Registry admin |
|---|---:|---:|---:|---:|---:|---:|
| Read published Catalog/map | Yes | Yes | Yes | Yes | Yes | Yes |
| Read own accessible batch/issues | No | DEMO only | Yes | Yes | Yes | As assigned |
| Create/stage/edit batch | No | DEMO only | Yes | No | No | No |
| Run validation | No | DEMO only | Yes | Yes | No | No |
| Submit for review | No | DEMO only | Yes | Yes | No | No |
| Approve/reject/request changes | No | DEMO only, unverified | No | Yes | No | No |
| Promote | No | DEMO only, unverified | No | Policy optional | Yes | No |
| Publish/retire | No | DEMO only, unverified | No | No | Yes | No |
| Modify Registry | No | No | No | No | No | Yes |

服务端 state machine、same-generation hash、row locks、RLS 和 DB grants 仍是最终门禁；隐藏按钮不构成授权。

## 5. Credential Handling

允许：

- 平台 API token 存入 QGIS Auth Manager 或操作系统凭据库；
- PostGIS 密码存入 libpq/OS 受控凭据机制；
- 内存中短期 access token；
- token 到期后重新登录。

禁止：

- `.qgs/.qgz`、QML、plugin config、项目 properties、日志、截图、异常、clipboard、URL query 保存 token/password；
- Git 仓库内 `pg_service.conf` 写 password；
- 插件提供“测试方便”的 owner/publisher credential；
- 把 token 转发给 GeoServer、QGIS Server 或数据库；
- 记录 Authorization header 或完整请求/响应 payload。

退出登录时必须清理内存 token；卸载插件不得删除用户其他 QGIS Auth Manager 条目。

## 6. API Allowlist

Bridge 首期只允许调用 generated client 覆盖的同源 HTTPS API：

- 统一 Catalog 与 Dataset Version 只读；
- GIS governance batch、stage、validate、issues、review、diff、promote、publish、retire；
- 后续专用 deep-link/feature detail 只读 API。

插件不得提供通用 URL、HTTP method、header 或 JSON body 调试器；不得直接调用：

- PostgREST/数据库 SQL；
- GeoServer REST admin；
- QGIS Server FCGI/WMS 管理路径；
- Docker daemon；
- 任意外部 URL 或本机文件上传，除非进入受控导入合同。

API schema/enum 必须由 OpenAPI 生成或经同一 JSON Schema 生成，禁止复制字符串状态机。

## 7. Deep Link Contract

浏览器和 QGIS 使用统一稳定身份：

```text
/gis?datasetVersionId={positive_integer}&selectedAsset={layer_key}:{feature_id}
```

要求：

- 使用 URL builder/encoder，不直接字符串拼接；
- `layer_key` 必须来自当前 Catalog；
- `feature_id` 是该 layer 的 opaque stable id，长度和字符受限；
- 详情响应必须回显相同 `dataset_version_id`；
- QGIS Bridge 从当前已选择要素读取业务 stable id，不使用 QGIS internal feature id/layer id；
- browser → QGIS 定位采用平台生成的一次性或短期请求标识，不能远程执行表达式、脚本、SQL 或打开任意工程路径。

未知、retired、跨版本或 inactive layer 深链路返回明确错误，不静默定位到“最新版本”。

## 8. Validation Issue Mapping

平台 severity 的权威枚举保持：

```text
error | warning | info
```

QGIS UI 映射：

```text
error   → ERROR
warning → WARNING
info    → INFO
```

不得引入 `CRITICAL` 改变后端阻断语义。是否阻断 approve/promote 只由服务端规则决定，插件颜色和过滤器没有决定权。

Issue geometry 以临时 memory layer 展示：

- 不保存回 staging/core/publish；
- 不自动写回 QGIS project；
- layer 名含 batch/run id；
- 切换 batch/run 或关闭项目时释放；
- 点击 issue 通过 `{batch_id, validation_run_id, issue_id}` 获取详情；
- 不能把旧 run 的 resolved 状态套到新 run。

## 9. Offline and Failure Behavior

- 离线时允许查看本地缓存的非敏感 Catalog 摘要和最后一次 issue 列表，但明确标记 stale；
- 离线时所有治理写操作禁用，不排队自动重放；
- 超时/401/403/409/410/422 分开显示，不将状态冲突重试成成功；
- 401 清理失效 session 并重新登录；403 不循环刷新；409 要求重新加载 batch/version；
- 网络恢复后必须重新获取 batch 状态、validation hash 和权限，不信任缓存按钮状态。

## 10. Logging and Audit

每个调用生成/传递 correlation id。客户端安全日志仅记录：时间、operation、HTTP status、结构化 error code、batch/version/layer 的非敏感 id、插件版本和 correlation id。

必须脱敏：token、password、Authorization、cookie、个人路径、DSN、完整 source_payload、完整 feature properties、用户输入备注和上游 response body。

服务端审计必须记录 token subject、assurance、scope、operation、目标、状态前后、content hash/revision 和 correlation id。审计记录 append-only；插件本地日志不是权威审计。

## 11. Threat Model

| Threat | Mandatory control |
|---|---|
| 客户端伪造 actor/reviewer | 服务端从 IAM token 派生 identity |
| token 泄露到工程/日志 | Auth Manager/OS store、日志脱敏、静态 secret scan |
| 插件绕过审核直接改 core | 无 core DB 权限；所有治理写经 FastAPI |
| 校验后篡改 staging | 现有 DB trigger/RLS/row lock/hash same-generation 门禁 |
| 恶意 deep link 注入 | Catalog layer allowlist、opaque id 验证、无表达式执行 |
| SSRF/任意 endpoint | 固定 API base；无通用 URL 字段 |
| 旧响应覆盖新 batch/version | request generation/abort + identity match |
| issue geometry 污染业务表 | memory layer only，无自动写回 |
| 本地 DEMO 被误当生产证据 | 显著 unverified 标记和 audit assurance |

## 12. Packaging and Updates

- 插件包必须版本化、可校验 hash、固定最低/最高兼容 QGIS 版本；
- 首期目标 QGIS 3.44 LTR；
- 发布包不得包含服务 credential、个人配置、缓存或 `.env`；
- 自动更新源必须 HTTPS、域名 allowlist 和签名/校验；未实现签名时关闭自动更新；
- 插件不能修改系统级 `pg_service.conf`，只能提供指引或创建用户明确选择的配置。

## 13. Acceptance Gates

- [ ] 生产 actor 由 IAM token 派生，客户端 actor 不能越权；
- [ ] 无 IAM 时所有治理 mutation fail closed；
- [ ] scope/role/state 三重门禁有正反测试；
- [ ] 包、工程、配置、日志和异常无 credential；
- [ ] 插件只能调用 API allowlist，不存在通用 HTTP/SQL/admin 控制台；
- [ ] deep link 对未知 layer、跨版本、恶意 id fail closed；
- [ ] severity 映射不改变后端阻断语义；
- [ ] issue memory layer 不持久化、不写业务表；
- [ ] 离线写入不可排队重放；
- [ ] correlation id 可从插件追踪到 append-only 服务端审计；
- [ ] QGIS 3.44 LTR GUI 安装、登录、失效 token 和卸载完成人工验收。

## 14. Rollback

Bridge 是可选客户端。禁用/卸载插件不改变 QGIS Desktop 的 staging 数据库编辑能力、已有工程、平台治理 API 或 Web GIS。发生安全或兼容问题时：

1. 服务端撤销 client id/token；
2. feature flag 禁用 Bridge mutation；
3. QGIS Plugin Manager 禁用/卸载插件；
4. 继续通过现有 FastAPI/Web 流程操作；
5. 不通过放宽数据库权限恢复功能。

## 15. Explicit Non-goals

- 本文不创建插件代码或包；
- 不实现统一 IAM；
- 不授予 QGIS 直接修改生产核心表或 publish 视图；
- 不引入 WFS-T、QGIS Server admin 或 GeoServer admin 功能；
- 不替代现有 QGIS Auth Manager、数据库最小权限和治理状态机。
