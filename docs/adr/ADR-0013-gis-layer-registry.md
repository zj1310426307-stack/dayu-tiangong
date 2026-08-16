# ADR-0013：GIS Layer Registry 与多服务统一目录

- Status：Accepted
- Date：2026-08-15
- Decision baseline：远端 `main` / `f72b675e4681823e35cf74219a0721825dca8082`
- Baseline tree：`a9d6750c2e0c7f7834c8bac64acc955d6e7da020`
- Scope：GIS-OPT-2 Step 3，仅冻结架构和合同；Registry 尚未建表或接入运行时

## Context

当前图层语义分散在 QGIS 工程、GeoServer bootstrap、后端静态数组和 `CesiumMap.tsx` 中：

- QGIS Desktop 工程维护 14 个专业制图层、样式、标注、分组和比例尺；
- GeoServer 以两组 Python 常量维护 12 个发布层、7 个缓存层和标题；
- `/api/v1/gis-analysis/layers` 返回另一套 22 行静态业务目录；
- `/api/v1/dgis/catalog` 面向 MVT、COG、3D Tiles 和仿真资源，但不驱动主地图；
- Cesium 主地图硬编码业务图层 key、标题、分组、缓存、默认显隐和解析正则。

这些清单不是同一份合同，也没有统一表达“业务身份、专业制图、服务方式、版本字段、安全发布能力”之间的关系。GIS-OPT-2 需要统一 Catalog，但不能把 QGIS XML、数据库连接、任意 URL 或前端对象塞进一个万能配置表。

## Decision Drivers

1. 每个业务图层必须有跨 QGIS、GeoServer、Martin、TiTiler、FastAPI 和 Cesium 稳定的身份。
2. 专业制图仍由 QGIS 工程负责，不能降级成数据库样式 JSON。
3. Registry 必须是安全 allowlist，而不是任意数据源或 URL 执行器。
4. Dataset Version 是运行时事实，不能复制成静态图层配置。
5. 旧 `/gis-analysis/layers`、`/dgis/catalog` 和 GeoServer 路径必须分阶段兼容。
6. 前端不得继续枚举业务 layer key、标题、分组和数据版本过滤规则。

## Considered Options

### Option A：以 QGIS GetProjectSettings 为唯一 Catalog

否决。它能表达专业制图元数据，但不能安全表达平台业务身份、跨服务模式、缓存策略、深链路和平台权限；每个目录请求实时解析大 XML 也把上游可用性与内部信息泄露带入主读路径。

### Option B：以数据库 Registry 取代 QGIS 工程

否决。数据库适合稳定身份和安全策略，不适合完整承载 QGIS renderer、label、layout、layer tree、表单与项目级制图语义。

### Option C：Registry + QGIS manifest + Runtime + Dataset Version 合并

采用。四类权威各自独立，由后端 Catalog 服务做唯一合并，前端只消费安全 DTO。

## Decision

### 1. 权威边界

| 权威源 | 负责 | 不负责 |
|---|---|---|
| GIS Layer Registry | 稳定业务身份、来源 relation、服务/渲染模式、版本过滤字段、能力、缓存政策、公开 allowlist、active 状态 | QGIS XML、渲染器细节、凭据、任意 SQL/URL、运行健康 |
| QGIS Desktop / Server manifest | renderer、label、比例尺、绘制顺序、显示标题、项目分组、layout、构建 revision | 业务权限、数据库角色、Dataset Version 状态、前端对象 |
| Runtime config / health | 同源公开入口、内部服务发现、feature flag、超时、上限、健康与实际 revision | 业务 layer 定义、用户可编辑配置 |
| Dataset Version | `id/status/content_hash/published_at/retired_at` 和可公开性 | 图层标题、服务路由、样式 |
| Frontend UI state | 当前显隐、透明度、选择、面板状态 | 业务 layer 清单、过滤表达式、安全权限 |

Registry、manifest 和 Dataset Version 均不能被浏览器直接修改。

### 2. 稳定身份

三个身份不得混用：

- `layer_key`：平台稳定业务身份，例如 `river`；进入 API、前端状态、日志、Issue 和深链路；重命名需兼容别名迁移。
- `qgis_short_name`：QGIS WMS 稳定发布名；由 Registry 指定并在生成工程中强制唯一。
- `qgis_layer_id`：某个 QGIS 工程 revision 内的构建验证身份；可因重建变化，不进入公开 API 或持久前端状态。

GeoServer qualified name、Martin source id、TiTiler asset id 均是 adapter 配置，不是业务身份。

### 3. Registry 首期逻辑字段

后续迁移实现不得少于以下逻辑字段；本轮不创建物理表：

| 字段 | 约束与语义 |
|---|---|
| `id` | 内部主键，不作为外部身份 |
| `layer_key` | 唯一，`^[a-z][a-z0-9_]{1,62}$`，发布后稳定 |
| `title` | 稳定业务标题，供无项目 manifest 的回退展示 |
| `group_key` | 稳定分组 key，不等同可本地化显示名 |
| `source_schema` | 首期仅 `publish` 或 `tiles` allowlist |
| `source_relation` | 单一 PostgreSQL identifier，不允许点号、引号或表达式 |
| `geometry_type` | 平台枚举，不从客户端输入 SQL 类型 |
| `native_crs` | `EPSG:<integer>` 规范格式 |
| `qgis_short_name` | QGIS_WMS 必填且唯一 |
| `service_mode` | 本 ADR 的固定枚举 |
| `render_mode` | 本 ADR 的固定枚举 |
| `dataset_filter_field` | 版本化服务首期只能为 `dataset_version_id`；非版本资源为 null |
| `identify_enabled` | 默认识别能力；最终能力取 Registry、manifest、runtime 和权限交集 |
| `legend_enabled` | 默认图例能力 |
| `search_enabled` | 默认搜索能力；只允许后端登记的安全搜索路径 |
| `capabilities` | 其他结构化布尔能力，不允许任意 operation 名 |
| `cache_mode` | `NONE` / `CLIENT_PRIVATE` / `VERSIONED_PUBLIC` |
| `identify_mode` | `NONE` / `FEATURE_INFO` / `DETAIL_API` / `CLIENT_PICK` |
| `detail_route_key` | 后端登记的路由 key，不是 URL |
| `model_entity_type` | 可空的四类治理实体或受控枚举 |
| `active` | 软启停；false 不进入新 Catalog/Server 工程 |
| `revision` | 乐观并发和 manifest 追踪 |
| 审计字段 | created/updated actor/time；生产 actor 来自 IAM |

Registry 明确禁止保存：SQL、CQL/FILTER、SELECT 列表达式、密码、token、DSN、内部 hostname、文件系统路径、任意外部 URL、QGIS XML、Cesium runtime 对象和前端组件名。

`source_schema + source_relation` 必须同时通过 identifier 校验、schema allowlist、relation allowlist、数据库存在性和服务角色 SELECT 权限验证。只通过正则不构成发布授权。

### 4. 固定服务与渲染模式

`service_mode` 仅允许：

```text
QGIS_WMS
GEOSERVER_WMS_LEGACY
MARTIN_MVT
TITILER
FASTAPI
CESIUM_DYNAMIC
THREE_D_TILES
```

`render_mode` 仅允许：

```text
RASTER_WMS
VECTOR_TILE
RASTER_TILE
DYNAMIC_PRIMITIVE
THREE_D
```

初始合法组合：

| service_mode | render_mode | 版本门禁所有者 |
|---|---|---|
| QGIS_WMS | RASTER_WMS | FastAPI QGIS Gateway |
| GEOSERVER_WMS_LEGACY | RASTER_WMS / RASTER_TILE | 现有后端/客户端兼容层，迁移后收口 |
| MARTIN_MVT | VECTOR_TILE | Martin SQL/source + Catalog allowlist |
| TITILER | RASTER_TILE | TiTiler 登记资产网关 |
| FASTAPI | DYNAMIC_PRIMITIVE | FastAPI 资源 API |
| CESIUM_DYNAMIC | DYNAMIC_PRIMITIVE | 现有时序/仿真 API |
| THREE_D_TILES | THREE_D | 登记 tileset + same-origin 静态服务 |

未知组合在 Registry 写入和 Catalog 构建时都失败，不允许前端猜测。

### 5. 合并优先级

Catalog 服务按下列顺序合并，但不是“后者覆盖全部前者”：

1. Registry 决定 layer 是否存在、业务身份、来源、安全能力、服务/渲染/缓存/识别模式；
2. QGIS manifest 只可补充/覆盖 renderer 元数据、label、绘制顺序、比例尺、项目显示标题、显示分组和 layout；
3. Runtime 只解析登记的 endpoint key、健康、feature flag 和实际 project revision；
4. Dataset Version 注入本次请求的版本状态与 hash；
5. Catalog 输出安全 DTO，丢弃所有内部字段。

任何安全冲突 fail closed：Registry inactive、manifest revision 不一致、QGIS short name 缺失/重复、版本不公开、服务不健康时，图层不可被标记为可用。QGIS manifest 不能增加 Registry 未登记的公开图层，也不能扩大 capability。

Catalog 同时输出：

- `title`：Registry 稳定业务标题；
- `display_title`：项目 manifest 可本地化展示标题，缺失时回退 `title`。

### 6. 底图安全边界

底图类型可设计为 `XYZ/WMS/WMTS/COG/MVT/ARCGIS_REST`，但首期只允许部署配置中预先登记的 `endpoint_key`。Catalog 只能返回同源代理地址或已审核的公开地址，Registry 不保存任意 URL。

未来若开放管理员登记外部 URL，必须另建带 IAM 的受控流程，至少实施 scheme/host/port allowlist、DNS 与重定向后 IP 复核、私网和 metadata endpoint 阻断、超时、响应大小、MIME、TLS、凭据分离和定期重验证。该能力本阶段不实现。

### 7. 旧目录兼容

- `/api/v1/dgis/catalog` 保留其基础设施、仿真、COG、MVT、3D 资产职责，先由新 Catalog adapter 合并，不立即删除；
- `/api/v1/gis-analysis/layers` 保留兼容期，但不得继续成为主地图新增业务层入口；
- GeoServer 12 层静态清单在 shadow 阶段继续工作；Registry 建立后以双向一致性测试暴露漂移；
- 前端切换采用 `legacy → shadow → catalog` feature flag，失败时可无数据迁移地切回 legacy。

删除旧端点、静态数组或 GeoServer 常量必须另有弃用窗口和 ADR/交付记录，本阶段不执行。

## Consequences

### Positive

- 平台获得唯一稳定的业务图层身份和安全 allowlist；
- QGIS 专业制图能力被保留，不被数据库 schema 取代；
- 新服务通过固定 adapter 扩展，不再修改 Cesium 大组件中的业务枚举；
- Catalog 可做 revision、ETag、差异测试和回滚。

### Negative

- 需要 Registry 迁移、后台校验、manifest builder 和多来源合并器；
- 初次导入会暴露现有 14/12/22 层清单的名称和分组差异；
- 旧端点在兼容期形成有限重复，必须有明确退役门禁。

## Security

- Registry 写入属于高权限管理动作，生产必须由 IAM scope 和审计保护；
- source、service、capability、endpoint 均为枚举/allowlist；
- Catalog 不返回 credentials、internal endpoint、DB relation、project path、MAP 或 FILTER；
- Registry active 不等于 Dataset Version 可公开，每次请求仍由版本状态门禁；
- 外部 URL 不允许由普通用户或 QGIS 插件直接登记。

## Version Semantics

- Registry revision 描述“图层配置代次”，Dataset Version 描述“数据事实代次”，QGIS project revision 描述“专业制图代次”；三者分别输出、分别进入缓存键；
- 版本化 layer 必须声明 `dataset_filter_field`；QGIS_WMS 首期固定为 `dataset_version_id`；
- published 版本可以进入公开 Catalog；retired 版本只允许历史只读 API，不进入新的公开地图目录；
- layer key 在 Dataset Version 间稳定，feature id 只在 `{layer_key, feature_id, dataset_version_id}` 三元组内解释。

## Migration / Rollback

1. A1 只使用临时、只读的 bootstrap Registry snapshot，实现 Server deployment-project builder 和合同测试，不建立真实 Registry 表；
2. B1 再实现真实 `gis_layer_registry` migration、seed、校验与 snapshot export，并使其成为唯一 Registry 权威；
3. 从现有 QGIS/GeoServer/Martin/TiTiler/后端常量生成可审查初始清单；
4. shadow Catalog 同时比较旧清单和新输出，差异有明确 allowlist；
5. 前端 adapter 在 feature flag 下读新 Catalog；
6. 任何错误切回 legacy，不回写或删除 Registry 数据；
7. 旧入口只有在观察期和回滚窗口结束后才能删除。

## Acceptance Gates

- [ ] Registry schema 和枚举与本 ADR 一致，禁止任意 SQL/URL/path/secret；
- [ ] layer_key、qgis_short_name 唯一，qgis_layer_id 不进入公开合同；
- [ ] relation 通过 identifier、schema、存在性和权限四重校验；
- [ ] manifest 不能扩大 Registry allowlist 或 capability；
- [ ] Catalog 对每种 service/render 组合都有正反合同测试；
- [ ] published、retired、draft 等版本状态按合同过滤；
- [ ] 旧 12 层/22 层/DGIS catalog 有差异报告和兼容测试；
- [ ] 前端业务层清单不再硬编码后才能切换主路径；
- [ ] feature flag 可切回 legacy，且不需要数据库回滚。

## Open Questions

- Registry 的后台管理 UI 是否进入 GIS-OPT-2 后续阶段；首期可使用迁移/seed 管理，但仍需审计。
- 多语言 `display_title` 是否在 Registry 单独建 translation 表；不影响稳定 `title` 和 `layer_key`。
- 公开 Catalog 是否按角色裁剪图层；生产 IAM 接入前只能提供平台级公开 allowlist。

## References

- `docs/review/GIS-OPT-2_Baseline_Audit.md`
- `docs/adr/ADR-0012-qgis-server-integration.md`
- `docs/adr/ADR-0011-qgis-controlled-production.md`
