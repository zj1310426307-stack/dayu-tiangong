# ADR-0012：QGIS Server 只读集成与版本安全网关

- Status：Accepted
- Date：2026-08-15
- Decision baseline：远端 `main` / `f72b675e4681823e35cf74219a0721825dca8082`
- Baseline tree：`a9d6750c2e0c7f7834c8bac64acc955d6e7da020`
- Scope：GIS-OPT-2 Step 3，仅冻结架构和合同；QGIS Server 尚未实现

## Context

当前系统已经具备 QGIS Desktop 3.44 LTR、单一 PostGIS、四类强类型暂存、质检审核、不可变 `dataset_version`、12 个 `publish` 只读视图、GeoServer、Martin、TiTiler 和 Cesium。QGIS Server 当前不存在于 Compose、Nginx、FastAPI、健康检查和测试中。

当前 Desktop 主工程 `qgis/projects/dayu_tiangong_ltr.qgs` 的事实为：

- 工程版本为 QGIS 3.44.13，CRS 为 EPSG:4490；
- 源文件 SHA-256 为 `9807018e5475c3595d93090ae5c683a93ebe8052f2c2b037c08dd5948bf79449`；
- 包含 3 个顶层组、14 个图层和 3 个关系；
- 4 个 `staging_qgis` 图层可编辑，10 个 reference/publish 项目层只读；
- 所有数据库连接只写 PostgreSQL service 名；
- 项目 title 为空，OWS 发布限制没有形成合同，`<Layouts/>` 为空；
- `publish.river` 在工程中以 reference 和 publish 两个项目层重复出现；
- 尚未覆盖 `publish.water_name`、`publish.poi`、`publish.map_annotation` 等全部 12 个发布视图。

`publish.*` 会同时暴露所有 `status='published'` 的数据版本。因此，将 QGIS Server 启动起来并不能证明版本隔离、安全发布或 Print 可用。

## Decision Drivers

1. Desktop 专业制图只能有一个人工维护权威源。
2. QGIS Server 不得读取或写入 staging，也不得使用 editor、backend、owner 或 GeoServer 身份。
3. 浏览器不能控制 QGIS 项目路径、数据库过滤表达式、数据源或外部 URL。
4. `dataset_version_id` 必须同时约束 GetMap、GetFeatureInfo、Legend、Print、响应缓存和对象身份。
5. GeoServer 必须在迁移期保留为稳定回滚路径。
6. Martin 继续负责 MVT，TiTiler 继续负责登记 COG，不重复建设缓存与栅格服务。
7. 生成物必须可测试、可追踪、可回滚，并与 QGIS 3.44 LTR 保持可复现。

## Considered Options

### Option A：直接部署 Desktop 主工程

```text
qgis/projects/dayu_tiangong_ltr.qgs
        ↓
QGIS Server
```

否决。当前工程包含 staging 可编辑层。严格只读 Server 角色无法读取这些层；为使其加载而扩大权限会破坏最小权限。工程也缺少 title、完整 OWS 限制、Print Layout、完整发布层和版本隔离门禁。

### Option B：人工维护第二个 Server 工程

```text
Desktop project      Server project
     人工维护             人工维护
```

否决。它会形成第二套人工图层树、样式、short name、比例尺和服务能力配置，长期与 Desktop、Registry、GeoServer SLD 和 React 再次漂移。

### Option C：确定性生成 Server 部署工程

```text
Desktop 主工程 + Registry snapshot + builder version
                    ↓
       dayu_tiangong_server.qgz
       + project-manifest.json
```

采用。当前仓库已经有可被 QGIS 3.44.13 原生 API 回读的工程、稳定 datasource service 形式、short name 和静态契约测试，具备实现确定性 builder 的基础。重复河道层和缺失发布层必须由 builder 门禁暴露，不能静默猜测。

## Decision

### 1. 权威关系

```text
QGIS Desktop 主工程
= 人工维护的专业制图权威源

QGIS Server 部署工程
= 从主工程和 Registry snapshot 生成的只读部署物

GIS Layer Registry
= 业务身份、来源关系、服务模式和公开 allowlist 权威源

PostGIS
= 唯一空间事实源
```

Server `.qgz` 不允许人工修改。任何紧急修正先进入 Desktop 主工程或 Registry，再重新生成。

### 2. 部署工程生成合同

未来 A1 builder 必须：

1. 固定使用 QGIS 3.44 LTR；首个基准版本为 3.44.13；
2. 读取 `qgis/projects/dayu_tiangong_ltr.qgs` 和一个不可变 Registry snapshot；
3. 只选择 `active=true` 且 `service_mode=QGIS_WMS` 的 allowlist 图层；
4. 对重复 source relation，仅允许从 `03_PUBLISH_READONLY` 选择唯一候选；零个或多个候选均失败；
5. 移除所有 staging 图层、编辑配置、写表单、关系和不公开图层；
6. 将 datasource service 统一替换为 `service='dayu_qgis_server'`，只允许 `publish` schema；
7. 把部署层 short name 重写为 Registry 的 `qgis_short_name`，且全项目唯一；
8. 固化项目 title、EPSG:4490、OWS advertised URL、CRS allowlist、公开图层、FeatureInfo 字段和禁止的 WFS/WCS/OAPIF 能力；
9. 生成 `Dayu_A4_Landscape` Layout，但在版本隔离验收前禁用 GetPrint；
10. 输出规范化 `project-manifest.json`，记录源工程 hash、Registry revision、QGIS 版本、builder 版本、部署工程 hash、图层身份、绘制顺序、比例尺和 layouts；
11. 相同输入产生语义等价的 XML/manifest。`.qgz` ZIP 时间戳不作为确定性依据，测试比较规范化 XML 与 canonical manifest hash。

建议未来部署路径：

```text
qgis/server/dayu_tiangong_server.qgz
qgis/server/dayu_tiangong_server.manifest.json
```

上述路径本轮不创建。

### 3. 初始服务范围

| 能力 | 初始决定 | 说明 |
|---|---|---|
| WMS GetCapabilities | 启用 | 仅经安全网关，公开 URL 必须重写为同源入口 |
| WMS GetMap | 启用 | layer/version/尺寸/CRS/格式均白名单 |
| WMS GetFeatureInfo | 启用 | 查询层必须是已请求层；返回身份必须含版本 |
| WMS GetLegendGraphic | 启用 | 单一 allowlist layer；缓存绑定项目 revision 和版本 |
| WMS GetProjectSettings | 条件启用 | 先通过无 DSN、路径、隐藏层和编辑字段泄露测试；Catalog 不在请求时解析它 |
| WMS GetPrint | 默认禁用 | Layout、版本过滤和泄露测试全部通过后才启用 |
| QGIS Server WMTS | 不进入核心路径 | Martin/GeoServer 已承担瓦片职责 |
| QGIS Server WFS | 禁用 | 过渡期继续使用 GeoServer Basic WFS |
| QGIS Server OAPIF/WFS3 | 禁用 | 不扩大攻击面 |
| QGIS Server WCS | 禁用 | TiTiler 继续承担登记 COG |

后续若开启 WFS/OAPIF，必须另行 ADR；只能发布 Registry allowlist，且 update/insert/delete 永远不进入公开合同。

### 4. 固定项目和同源入口

内部 QGIS Server 以只读挂载和固定变量运行：

```text
QGIS_PROJECT_FILE=/srv/qgis/dayu_tiangong_server.qgz
```

浏览器唯一可见的 WMS 地址为：

```text
/qgis-server/wms
```

Nginx 将该路径转发到同一个 FastAPI handler：

```text
/api/v1/gis/qgis/wms
```

FastAPI 再调用 Compose 私网中的 QGIS Server。`/qgis-server/*` 的其他路径返回 404；不得直接代理 FCGI。Catalog 返回 `/qgis-server/wms`，不返回内部服务名、端口或文件路径。

网关拒绝任何 `MAP` 参数，即使它恰好等于固定路径；也拒绝任意 `FILTER`、datasource、filesystem path、SQL、external URL 和未声明的 vendor 参数。

### 5. 独立数据库角色

采用新角色 `dayu_qgis_server`，不复用 `dayu_geoserver`。

角色合同：

- `LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS`；
- `default_transaction_read_only=on`；
- 只拥有目标数据库 `CONNECT`、`publish` schema `USAGE`、Registry allowlist relation `SELECT`；
- 不拥有 `public` 核心表、`staging_qgis` schema、sequence、function execution、DDL 或任意 DML 权限；
- 不成为 `dayu_publisher` 或其他写角色成员；
- 密码仅由受控 secret/credential mount 注入；部署工程只保存 service alias；
- bootstrap 每次先撤销既有权限和双向 role membership，再按 allowlist 重授。

本轮只设计，不创建该角色。

### 6. 安全 WMS Gateway

浏览器不得直接使用标准 `LAYERS`、`FILTER` 或 `MAP` 组合控制上游。公开合同接受平台字段：

```text
request
dataset_version_id
layer_key / layer_keys
bbox
width / height
crs
format
transparent
i / j（FeatureInfo）
feature_count（有上限）
template（Print 固定值）
```

Gateway 执行：

```text
dataset_version_id → 校验 published + content_hash
layer_key → Registry active allowlist
layer_key → qgis_short_name
dataset_filter_field → 固定白名单 dataset_version_id
服务端构造 QGIS FILTER
只转发按 operation 声明的参数
```

第一阶段只允许 `dataset_filter_field='dataset_version_id'`。Gateway 生成的内部过滤表达式等价于：

```text
qgis_short_name:"dataset_version_id" = <server-validated-integer>
```

该字符串永不接受浏览器片段拼接。

参数门禁：

- WMS version 仅 `1.1.1` 或 `1.3.0`；新 adapter 默认 1.3.0；
- CRS 由部署 manifest allowlist 决定，首期至少 EPSG:4490；新增 CRS 必须进入构建合同；
- `width`、`height` 均为正整数并受运行配置上限约束，首期上限 4096；
- GetFeatureInfo 的 query layers 必须是 GetMap layers 子集，像素坐标必须落在图像范围内，`feature_count<=20`，`INFO_FORMAT` 固定为 `application/json`；
- GetLegendGraphic 首期只允许单层与默认 style；
- GetPrint 只允许 `Dayu_A4_Landscape`、PDF/PNG、受限 extent 和固定 layout item 参数；不接受 redlining、Atlas、external WMS 或任意 label 表达式；
- 对未知参数采用 reject，不采用静默透传。

### 7. Catalog 元数据来源

采用 hybrid：

```text
build-time project manifest
+ runtime health/revision validation
```

不采用“每次 Catalog 请求都解析 GetProjectSettings”，因为大 XML 解析、上游可用性和内部信息泄露会进入读路径。GetProjectSettings 仅用于构建/部署验证与受控诊断；Catalog 使用已签名/只读部署 manifest，并校验运行中 QGIS Server 报告的 project revision 与 manifest 一致。

三种方案的取舍为：

| 方案 | 优点 | 风险 | 结论 |
|---|---|---|---|
| Runtime 每次请求 GetProjectSettings | 总能看到上游即时项目 | 大 XML、上游耦合、内部字段泄露面、难以稳定 cache | 否决作为 Catalog 主读路径 |
| Build-time manifest only | 可测试、可 hash、低延迟 | 无法发现运行实例加载了错误工程或已失效 | 单独使用不足 |
| Build-time manifest + runtime health/revision | 同时获得确定性合同和实际部署校验 | 需要 revision/health 协议 | 采用 |

### 8. Print

未来 Server 部署物必须包含 `Dayu_A4_Landscape`：标题、图例、比例尺、指北针、数据版本、制图时间、坐标系、DEMO/工程提示。

版本字段只能由 Gateway 根据已验证 `dataset_version_id` 注入，浏览器不能提供任意 layout label。下列条件未同时满足时，运行环境设置 `QGIS_SERVER_DISABLE_GETPRINT=1`，Gateway 返回结构化 `PRINT_NOT_READY`：

- Layout 存在且原生 QGIS API 可回读；
- 地图项全部使用相同 server-side dataset filter；
- 两个 published 版本 A/B 输出无混图；
- 输出元数据、标题和缓存键绑定同一版本；
- PDF/PNG 不包含路径、DSN、凭据或非 allowlist 外部资源。

### 9. GeoServer fallback

GeoServer 不删除。GIS-OPT-2 Step 4–8 继续承担旧 WMS/WMTS、Basic WFS、回滚和 A/B 基线。QGIS Server 初期通过 feature flag/shadow 请求并行验收，不立即替换现有 Cesium 主路径。

GeoServer 只有在独立退役 ADR 满足功能、性能、版本隔离、Print、FeatureInfo、缓存、运维和回滚保留期门禁后才可退役。

## Consequences

### Positive

- Desktop 专业制图、平台业务语义和 Server 部署职责不再混为一体；
- staging 从 Server 读取面物理隔离；
- 版本过滤由可信服务端构造，不能由浏览器注入；
- manifest 可测试、可 hash、可与 Catalog 同 revision；
- GeoServer 保留使迁移可以分阶段回滚。

### Negative

- 需要维护 builder、manifest schema、独立角色和 WMS Gateway；
- 当前 Desktop 工程缺失的发布层、重复河道层和空 Layout 会使 A1 首次构建失败，必须显式修复；
- QGIS WMS 第一阶段不提供共享瓦片缓存，性能不能直接等同 GeoWebCache；
- GetProjectSettings 与 GetPrint 在通过安全门禁前保持关闭或受限。

## Security

安全边界按四层实施：

1. 网络：QGIS Server 只在 Compose 私网，宿主无公开端口；
2. 网关：operation、参数、layer、version、尺寸、CRS 和格式 allowlist；
3. 工程：只含 Registry active 发布层，无 staging、WFS/WCS/OAPIF、external layer；
4. 数据库：独立只读角色，只读 `publish` allowlist。

任何一层不能替代其他层。尤其不能因为 QGIS Server 自带 FILTER 安全检查，就允许浏览器提交 FILTER；官方文档明确 FILTER 是可表达数据库子集的 vendor 参数，平台仍必须在外层完全接管其构造。

## Version Semantics

- 公开 QGIS WMS 只接受 `status='published'` 且 `content_hash` 非空的版本；
- approved/draft/rejected 返回 409，retired 返回 410；
- 每次 Gateway 请求重新验证版本状态，不能只信 Catalog 缓存；
- layer 必须声明 `dataset_filter_field`，QGIS_WMS 首期缺失该字段即拒绝发布；
- GetMap、GetFeatureInfo 与 GetPrint 必须使用同一服务端过滤代次；
- GetCapabilities、Legend、ProjectSettings 虽不读取某一业务要素，也要求版本参数并返回 `X-Dataset-Version`，其缓存键包含版本和 project revision；
- 任何共享缓存键至少包含：project revision、dataset version、operation、排序后的 layer keys、CRS、bbox、尺寸、格式和其余 allowlist 参数；
- FeatureInfo 归一化身份为 `{layer_key, feature_id, dataset_version_id}`，不得把 QGIS layer id 或展示名作为业务身份。

## Deployment Contract

未来 A1/A2 需要提供：

```text
source qgs (tracked)
registry snapshot (versioned)
builder (tracked)
server qgz (generated, read-only mount)
project manifest (generated, canonical JSON)
dayu_qgis_server pg service (secret mount)
QGIS_PROJECT_FILE (fixed)
FastAPI gateway (single policy owner)
same-origin /qgis-server/wms
health endpoint (project revision + QGIS version + DB read probe)
```

运行健康必须区分：process health、project validity、manifest revision、database read、WMS capability 和 version isolation，不能压成一个无证据的 `healthy`。

## Fallback / Rollback

1. 默认保持现有 GeoServer/Cesium 路径；QGIS Server 先 shadow；
2. feature flag 从 `catalog` 切回 `legacy` 时，前端继续使用现有 GeoServer config；
3. 停止 QGIS Server 与 Gateway route 不影响 PostGIS、治理链、Martin、TiTiler 或 GeoServer；
4. 回滚 builder 输出时使用上一份已验收 qgz + manifest 配对，禁止混用 revision；
5. 禁止通过扩大 DB 权限或重新暴露直接 FCGI 来“临时恢复”。

## Acceptance Gates

- [ ] builder 输入、输出和 QGIS 3.44 版本固定；
- [ ] 相同输入的规范化 project/manifest hash 相同；
- [ ] Server 工程不存在 staging datasource、编辑图层、密码、authcfg、个人路径或内部路径泄露；
- [ ] 每个 active QGIS_WMS Registry 层在 Server 工程中有且仅有一个 short name；
- [ ] 角色属性和精确权限满足本 ADR，真实 INSERT/UPDATE/DDL 均失败；
- [ ] 浏览器不能访问内部 QGIS Server，也不能使用 MAP/FILTER/SQL/external URL；
- [ ] GetMap 与 GetFeatureInfo 对两个 published 版本严格隔离；
- [ ] Catalog、manifest、健康响应中的 project revision 一致；
- [ ] GetPrint 在门禁前不可用，门禁后版本、内容和标注一致；
- [ ] GeoServer WMS/WMTS/Basic WFS 回归仍通过；
- [ ] 一键切回 legacy 路径不修改数据库数据。

## Open Questions

以下仅是 A1/A2 的非阻塞实现选择，不改变本 ADR：

- QGIS Server 容器采用仓库自建镜像还是经审查的固定 digest；
- 中文字体最小集合及镜像 license/size；
- WMS 并发线程、超时和 4096 像素上限是否需要按容量测试收紧；
- project manifest 是否增加签名。首期至少要求 canonical hash 和只读部署。

## References

- [QGIS Server 3.44 advanced configuration](https://docs.qgis.org/3.44/en/docs/server_manual/config.html)
- [QGIS Server 3.44 WMS service](https://docs.qgis.org/3.44/en/docs/server_manual/services/wms.html)
- [QGIS Server 3.44 project configuration](https://docs.qgis.org/3.44/en/docs/server_manual/getting_started.html#configure-your-project)
- [QGIS Server 3.44 containerized deployment](https://docs.qgis.org/3.44/en/docs/server_manual/containerized_deployment.html)
- `docs/review/GIS-OPT-2_Baseline_Audit.md`
- `docs/adr/ADR-0011-qgis-controlled-production.md`
