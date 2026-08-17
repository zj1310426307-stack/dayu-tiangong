# GIS-OPT-2 Final Review

> 历史基线：本报告记录 2026-08-16 的 GIS-OPT-2 验收。2026-08-17 起当前架构以 ADR-0014 和 `GIS_RESET_COMPLETION_REPORT.md` 为准。

日期：2026-08-16

分支：`agent/gis-opt2-full-remediation`

远端 `main` 基线：`f72b675e4681823e35cf74219a0721825dca8082`

最终判定：**GIS-OPT-2: COMPLETE**

GeoServer 决策：**KEEP**

Print 决策：**PRINT_NOT_READY**

## 1. 审查结论

GIS-OPT-2 的源码、合同、生成物、前端切换、数据库迁移、权限收口和 QGIS 3.44.13 Desktop 启动链已完成。PostGIS 仍是唯一空间事实源；Desktop 工程是唯一人工专业制图源；Server QGZ 由 Builder 确定性生成；Registry/Catalog 已进入数据库、API 和 Web runtime；Bridge 不直连核心表；横断面采用 ADD ONLY 扩展。

Docker Desktop 4.84.0、Engine/CLI 29.6.2 和 Compose 5.3.1 已可用。本轮先在独立 Compose project/新卷完成迁移往返、全栈、权限和双版本 WMS/FeatureInfo 验证，再对持久库做备份并执行 0012→0014 迁移、seed 和权限初始化。持久全栈已启动，QGIS GUI 已人工打开并确认工程、图层、EPSG:4490 和 Bridge API 在线状态。

经用户明确授权，持久库已通过治理链新增 `DEMO-RIVER-D`：Batch 6 经 stage→validate→submit-review→approve→promote→publish 生成 Dataset Version 58。版本 1 仍保持原哈希和三条河道；版本 58 含四条河道。持久 GetMap 图像哈希不同，GetFeatureInfo 要素 ID 不相交，QGIS health 五个分项均 PASS，总体状态为 `healthy`。

## 2. Architecture

| 问题 | 结论 | 证据 |
|---|---|---|
| PostGIS 是否仍为唯一事实源 | PASS | Registry 只指向同库 `publish/tiles`；QGIS Server 不持有第二数据库 |
| QGIS Project 是否为专业制图权威 | PASS | 只人工维护 Desktop QGS；Server QGZ 由 Builder 生成 |
| Server Project 是否自动生成 | PASS | QGIS 3.44 原生 Builder 输出 QGZ + canonical manifest 并回读 |
| Registry 是否统一业务身份 | PASS | 0013 + 22 图层 seed + 1 底图；启动校验源对象和 role SELECT |
| Catalog 是否统一目录 | PASS | `/api/v1/gis/catalog` 合并 Registry/manifest/runtime/version，不泄露内部 relation/URL |
| Frontend 是否去业务图层硬编码 | PASS | 三大组件无固定业务层数组；`levee` fixture 无需修改组件 |
| GeoServer 是否可退役 | NO | 仍承载 8 个过渡静态层和 rollback/A-B baseline；Print 未启用 |

## 3. QGIS Desktop 与 Bridge

- QGIS 3.44.13 Desktop 主工程保持 3 个受控分组和 14 个图层，Builder 没有改写原文件。
- Windows 启动器通过受控短盘符隔离中文路径，重建 OSGeo 环境，挂载本机 `pg_service`/凭据，安装并启动内置 Bridge。
- GUI 人工验收已确认：窗口正常打开，EPSG:4490、3 分组图层树和数据库图层可见，无 SIP/PyQt 错误和数据库口令弹窗；Bridge 显示 API 在线。
- GUI 已刷新到 Dataset Version 58 / Batch 6，显示 API 在线、Validation `run=2 · passed`、Review `published`、Publish `published`。本批次 0 error/0 warning，因此 issue 表为空；问题定位和高亮由专项合同测试覆盖。
- Bridge 只调用 FastAPI；没有 DB/admin 连接。无 IAM token 时生产 mutation fail closed。

## 4. QGIS Server

- Compose 镜像固定为 `qgis/qgis-server:3.44.12-trixie`；Desktop 3.44.13 工程原生回读和 Server runtime 都已通过。
- 容器仅在 Compose 私网，无宿主 `ports`；浏览器只能经 FastAPI `/qgis-server/wms` 访问。
- `dayu_qgis_server` 是独立默认只读 LOGIN，只授权四个 publish 视图；口令来自 Compose secret file，不进入 QGS/QGZ、源码或镜像环境变量。
- Gateway 只允许 GetCapabilities/GetMap/GetFeatureInfo/GetLegendGraphic 的平台字段。`MAP/FILTER/SQL/CQL/datasource/URL` 及未知 vendor 参数 fail closed。
- 独立环境两个发布版本为 1 和 56；GetMap 哈希不同，GetFeatureInfo 要素身份集不相交，双版本隔离 PASS。
- 持久环境版本 1/58 的 GetMap SHA-256 分别为 `09e8c8c0bd62804b283136076574cb9395cd180197a61cc2f6facf5dc3ffb088` 和 `9dec2f190980298e4517962111ad8e68cb2e609769abb0adf035fc842ffb1425`；FeatureInfo IDs 为 `[1,3]` 与 `[93,95]`，不相交。process/project/database/WMS/isolation 均 PASS，health 为 `healthy`。
- GetPrint 仍禁用；尚未取得 PDF/PNG 无路径/DSN/secret 且 legend/title/version 一致的完整证据。

## 5. Catalog、Web 与兼容性

- Catalog DTO 为 `gis-catalog/v1alpha1`，只接受 `published + content_hash`；unknown/draft-approved-rejected/retired 分别返回 404/409/410。
- 底图 URL 已从 Cesium 解耦；FastAPI 代理仅允许 deployment allowlist 中的 HTTPS host。
- 图层 adapter 按 `service_mode + render_mode` 穷尽选择；版本切换用 generation guard 阻断 stale resource，单层失败隔离，destroy 对称释放。
- 0014 新增 `cross_section_location/axis/point/profile` 和 `publish.cross_section_spatial`；旧断面字段、API 和 solver 读取合同不变。
- 新 GIS 版本不自动伪造边界、率定或 model-ready 状态；模型、调度和 AI 继续使用同一 Dataset Version 合同。

## 6. Database、权限与回滚

- Alembic 单一 head 为 `20260815_0014`。独立新库已完成 upgrade head→downgrade 0012→upgrade head，seed 重复执行结果稳定。
- 持久库已从 0012 升级到 0014，后续 seed 两次数量稳定；22 个 Registry 图层已在线。
- 持久升级前备份：`06_验证记录/backups/2026-08-16_GIS-OPT-2_pre_migration.dump`，大小 712184 字节，SHA-256 `775E72B43B33A0C68E29960ABD302DC7D57A88B432AE5A23C623980681A15FD8`；`pg_restore -l` 可读。
- `dayu_backend` 已是非 owner 运行账号并成为 `dayu_publisher` 组成员；backend/worker 不再使用本地 owner。迁移、seed 和 bootstrap 继续由一次性 owner 任务执行。
- editor/reviewer/qgis_server/publisher/backend 权限已在真实 PostGIS 验证。GeoServer store 已读 `publish` 兼容视图，不再读 `public` 核心表。
- 前端 flag 可回退 legacy；QGIS Server 路由/容器可停用；GeoServer 保留；0014/0013 downgrade 只删除自己的扩展对象。业务库回退以上述备份为前提。

## 7. Security

| 边界 | 结论 |
|---|---|
| DB 权限 | 独立 editor/reviewer/qgis_server/backend/publisher 角色和精确 allowlist 已实现并真库验证 |
| WMS injection | 浏览器 raw MAP/FILTER/SQL/CQL/URL/vendor parameter 被拒绝；版本 FILTER 只由服务端合成 |
| SSRF | 底图只使用 deployment allowlist HTTPS host，不跟随 redirect |
| Secrets | QGIS 资产无内嵌口令/authcfg/个人路径；Server 口令只通过 ignored local secret file 传入 |
| Internal URL | Catalog 只返回同源公开 endpoint，不返回内部 host/DSN/project path |
| IAM | 统一 IAM/OIDC/RBAC 不在本阶段范围；无 token 时 Bridge 生产 mutation fail closed |

## 8. Tests

| 真实执行 | 结果 |
|---|---|
| 独立 Docker 全量 Python 回归 | **276 passed, 6 skipped** |
| 持久 PostGIS 权限/迁移完整性专项 | **20 passed** |
| QGIS project contract，显式使用 3.44.13 `qgis_process` | **11 passed** |
| QGIS launcher/Bridge 专项 | **7 passed** |
| 独立双版本 GetMap/FeatureInfo 隔离 | PASS，versions 1/56，图像哈希不同，要素 ID 不相交 |
| 0014 upgrade→downgrade 0012→upgrade | PASS，仅在独立新库执行 |
| 持久 0012→0014 + seed 幂等 | PASS |
| QGIS GUI | PASS，工程/图层/CRS/DB/Bridge API 在线 |
| `npm run openapi:update` / `typecheck` / `build` | PASS，仅既有大 chunk warning |
| Compose config / 全栈 health | PASS，持久 QGIS health 为 `healthy` |
| compileall / `git diff --check` / secret scan | PASS |

独立全量中的 6 个 skipped 是可选环境探测；`qgis_process` 另以明确 executable 的专项命令完成 11 项。独立验收环境和持久环境分开记录，不相互冒充。

## 9. Docker 与在线状态

- Docker CLI/Engine/Compose：**AVAILABLE**。
- 独立 Compose：**PASS**，业务服务健康，one-shot bootstrap 成功退出。
- 独立 PostGIS：**PASS**，迁移往返、seed、role/bootstrap、Registry、全量回归和双版本隔离完成。
- 持久 PostGIS：**PASS**，已备份、迁移到 0014、seed、role/bootstrap 并完成 20 项真库专项。
- 持久全栈：业务服务已启动；QGIS process/project/database/WMS/isolation 均 PASS，health `healthy`。
- 持久双版本：**PASS**，versions 1/58；运行证据绑定 project revision `663fe0473c783342c16d09dc1b729d1c4f794ff9005a7c52d3a7471550a7842e`。
- QGIS GUI Bridge：**PASS**，已读取 Batch 6 的 validation/review/publish 状态。

## 10. Known Issues

### BLOCKER

无。

### HIGH

1. 生产统一 IAM/OIDC/RBAC 尚未建立；当前 actor 字段不等于受信身份。
2. GetPrint 在 PDF/PNG 内容、图例/标题/版本一致性和无敏感信息证据完成前必须保持关闭。

### MEDIUM

1. QGIS Server 容器为 3.44.12，Desktop 为 3.44.13；同属 3.44 LTR，已通过原生回读和运行门禁，仍应在升级后重跑证据。

### LOW

1. 前端仍有 Cesium/Ant Design/ECharts 大 chunk warning，不影响本轮功能和安全门禁。

## 11. GeoServer Decision

**KEEP**

GeoServer 已收口为 `publish` 只读发布器，不再读核心表；但它仍承载 8 个尚未迁移的静态层，并作为 rollback/A-B baseline。QGIS Server 只承载首批四类专业二维图层，Martin/TiTiler 职责不变。本阶段不删除 GeoServer，不开放 WFS-T。

## 12. 下一个安全执行点

1. 复核所有差异和最终回归，提交并推送分支。
2. 创建 Draft PR，检查 PR diff/checks，确认后转 Ready 并合并到 `main`。

## 13. Final Status

```text
GIS-OPT-2: COMPLETE
```

任务书最终硬门禁已全部 PASS。GetPrint 的额外内容安全门禁未完成，因此仍为 PRINT_NOT_READY；GeoServer 按迁移策略 KEEP。
