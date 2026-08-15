# GIS 数据库角色矩阵

## 角色定义

| 角色 | 类型 | 主要用户 | 默认事务 | 责任 |
|---|---|---|---|---|
| `dayu_qgis_editor` | LOGIN | QGIS 数据生产人员 | 可写 | 读取参考/治理数据，只编辑四张暂存表 |
| `dayu_qgis_reviewer` | LOGIN | QGIS/平台审阅人员 | `read_only=on` | 查看暂存、问题、核心参考和发布视图 |
| `dayu_publisher` | NOLOGIN 组角色 | 受控后端服务 | 按服务事务 | 晋级和发布所需的最小表/序列权限 |
| `dayu_backend` | LOGIN | API 与 Worker | 应用事务 | 非 owner；继承 publisher，并按应用白名单读写 |
| `dayu_geoserver` | LOGIN | GeoServer | `read_only=on` | 只读 `publish` 兼容视图，不读取核心表 |
| `dayu_martin` | LOGIN | Martin | 只读 | 读取 MVT 来源并执行 `tiles.*` |
| 本地 `POSTGRES_USER` | LOGIN/owner | 一次性管理任务 | owner | 仅迁移、seed 和角色引导，不承载 backend/worker |

## 权限矩阵

| 对象/操作 | editor | reviewer | publisher | GeoServer | Martin |
|---|:---:|:---:|:---:|:---:|:---:|
| 连接 `dayu_tiangong` | ✓ | ✓ | ✓（通过成员服务） | ✓ | ✓ |
| 读核心参考表 | ✓ | ✓ | ✓ | ✗ | 白名单 ✓ |
| 写核心 `river/cross_section/gate/pump` | ✗ | ✗ | 受控晋级 ✓ | ✗ | ✗ |
| 读 `staging_qgis.*` | ✓ | ✓ | ✓ | ✗ | ✗ |
| 写 `staging_qgis.*` | ✓ | ✗ | ✗ | ✗ | ✗ |
| 读 validation/issues | ✓ | ✓ | ✓ | ✗ | ✗ |
| 写 review/publication | ✗ | ✗（经 API 决策） | 受控服务 ✓ | ✗ | ✗ |
| 读 `publish.*` | ✓ | ✓ | ✓ | ✓ | 非当前路径 |
| 执行 `tiles.*` | ✗ | ✗ | ✗ | ✗ | ✓ |
| schema/table DDL | ✗ | ✗ | ✗ | ✗ | ✗ |
| 桌面直接登录 | ✓ | ✓ | ✗ | 服务专用 | 服务专用 |

“reviewer 经 API 决策”表示 reviewer 的直连数据库会话仍然只读；审核写入由平台控制面完成。当前平台尚未接统一 OIDC/IAM，调用 API 前必须由受控环境限制访问，不能仅信任请求体中的 reviewer 字符串。

## 引导与凭据

`database/bootstrap_qgis.py` 幂等创建/轮换 editor、reviewer，并创建 `dayu_publisher` NOLOGIN 角色；它会先撤销宽泛权限，再应用允许清单。`database/bootstrap_app.py` 创建/轮换 `dayu_backend`、清理陈旧成员关系并显式授予 publisher 成员资格。GeoServer 和 Martin 由各自引导脚本维护只读权限。

- 所有密码来自环境变量、被忽略的 `.env` 或 secret manager；
- QGIS 工程只写 `service='dayu_qgis'`，不写密码；
- 用户级 PostgreSQL service 只保存连接参数，口令放 QGIS Auth Manager 或本机凭据设施；
- 不把 editor 凭据用于 GeoServer，也不把 publisher/owner 交给 QGIS 用户。

## 验收要求

权限不能只靠文档判断。集成测试至少证明：editor 可写暂存但不能写/DDL 核心；reviewer 可读暂存和问题但不能写；GeoServer 可读 `publish`、不能读 staging、不能 DML，WFS capabilities 没有 Transaction/LockFeature。

生产部署仍需后续完成：统一身份、端点 RBAC、集中密码轮换/吊销流程和审计告警。应用运行账号从 owner 降权已经完成。
