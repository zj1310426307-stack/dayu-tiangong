# 大禹·天工当前数据库设计

业务空间统一采用 CGCS2000 / EPSG:4490；水动力距离采用米制桩号、河段长度和经批准的 CGCS2000 投影计算。权威 Alembic 演进为 `0001 → 0014`。

## 单库与 schema 边界

`dayu_tiangong` 是唯一业务空间数据库：

| schema/边界 | 用途 | 权威性 |
|---|---|---|
| `public` | 版本化水利核心表、模型、任务、调度、结果、治理审计 | 权威业务数据 |
| `imports` | GDAL/OGR 原始批次表，每次导入使用服务器生成的不可变表名 | 非权威原始落地 |
| `staging_qgis` | QGIS 可编辑的四类专业暂存表 | 非权威、待质检 |
| `publish` | 只暴露已发布版本的只读视图 | 权威数据的发布投影 |
| `tiles` | Martin 自动发现的版本过滤 MVT 函数 | 权威数据的瓦片投影 |

可选 GeoNode 使用目录/资产隔离边界，不建立第二份业务空间事实。TiTiler 的 COG 和 3D Tiles 文件通过只读资产卷服务，其元数据与 `dataset_version_id` 由 `simulation_layer`/发布清单关联，不把大文件写入核心关系表。

## 表域

| 领域 | 表 | 关键语义 |
|---|---|---|
| 版本治理 | `dataset_version` | 父版本、来源批次、内容哈希、审核/批准/发布/退役审计；权威版本不就地覆盖 |
| GIS 目录 | `gis_layer_registry`、`basemap_registry` | 图层稳定身份、服务/渲染模式、权限能力和受控底图 endpoint key |
| 导入治理 | `gis_import_batch` | 文件名、格式、大小、来源 SHA-256、源/目标 CRS、映射版本、操作人、原始表、父版本与状态 |
| 质检 | `gis_validation_run`、`gis_validation_issue` | 每次质检绑定暂存内容哈希；问题可按批次、规则、严重级别和几何查询 |
| 审核/发布 | `gis_review`、`gis_publication` | 人工决定绑定质检 generation；发布清单与版本一一对应 |
| QGIS 暂存 | `staging_qgis.river`、`cross_section`、`gate`、`pump` | 四类稳定字段、来源追溯、`upsert/delete`、EPSG:4490 几何和 GiST |
| 发布视图 | `publish` 下 12 个 GeoServer 兼容视图 | 仅 `published` 版本；GeoServer 已改接且无核心表直读权限 |
| 数据/空间 | `river`、`river_node`、`river_segment`、`river_connection`、`cross_section` | 版本隔离、有向河网、稳定节点身份、GiST 4490 |
| 横断面扩展 | `cross_section_location`、`cross_section_axis`、`cross_section_point`、`cross_section_profile` | 加法空间模型；复合外键保证与断面属于同一版本，不改旧 solver 合同 |
| 结构物 | `gate`、`pump` | 静态设计、明确河段/节点拓扑与设备约束/Q-H/Q-η |
| 时态状态 | `feature_state` | TimescaleDB hypertable，追加式对象状态，不覆盖静态设计字段 |
| 模型输入 | `model_parameter`、`boundary_condition`、`simulation_case`、`simulation_case_boundary` | 一个方案显式关联一组外边界 |
| 任务与结果 | `simulation_task`、`simulation_result`、`junction_result`、`structure_result`、`dispatch_event` | 冻结快照、队列生命周期、断面/节点/结构物/事件和诊断 |
| 调度 | `dispatch_plan`、`dispatch_action`、`dispatch_rule`、`dispatch_run` | 草稿—校验—冻结—归档，冻结 JSON 和 hash |
| 优化 | `optimization_task`、`optimization_candidate`、`optimization_result` | 冻结输入、候选仿真、Pareto 与人工推荐 |
| AI | `ai_conversation`、`knowledge_document`、`knowledge_chunk`、`ai_tool_call_log`、`ai_report` | 来源回答、知识检索、只读工具审计与报告 |
| 模型资产 | `simulation_layer` | 任务、版本、时间、服务类型、URL、样式和资产版本登记 |

## GIS-OPT-1 暂存模型

四张暂存表共享以下来源字段：`id`、`batch_id`、`source_feature_id`、`operation`、`quality_status`、`source_crs`、`target_crs`、`source_hash`、`operator`、`survey_time`、`source_payload`、`created_at`、`updated_at`。每表都约束：

- `operation ∈ {upsert, delete}`；
- `quality_status ∈ {pending, passed, failed}`；
- `target_crs = EPSG:4490`；
- `(batch_id, source_feature_id)` 与 `(batch_id, 业务编码)` 唯一；
- 几何类型固定，河道为 `LINESTRING`，其余为 `POINT`，均有 GiST 索引。

暂存表允许保留需要质检报告解释的领域问题；QGIS 表单是即时辅助，FastAPI/PostGIS 质检才是晋级门禁。字段映射详见 `docs/gis/qgis_staging_field_mapping.md`。

## 生命周期与一致性约束

- 批次：`created → staged → validating → validation_failed|validated → in_review → changes_requested|rejected|approved → promoting → promoted → published`。`changes_requested` 可返工重验，`rejected` 为终态。
- 质检：`running → passed|failed`，`error` 数量必须为零才通过。
- 版本：`draft|review|approved|published|retired|rejected`；GIS 晋级产出 `approved`，发布动作再变为 `published`。
- `dataset_version.source_batch_id` 唯一，`gis_publication.dataset_version_id` 唯一，保证重复晋级/发布不创建双份权威对象。
- 审核和质检分别保存同一暂存内容 SHA-256；晋级前再次计算，任何校验后编辑都会令旧批准失效。
- 晋级在一个事务内锁定批次、复制父版本四类核心对象、应用增量、生成拓扑、计算核心内容哈希；异常由事务整体回滚。
- 核心内容哈希排除自增 ID、时间戳和数据库自然行顺序，使用业务字段、业务关联编码和规范几何表达。
- 模型输入快照继续引用原 `dataset_version_id`；GIS 新版本不会漂移历史计算输入。

## 数据库角色

| 角色 | 登录 | 能力 | 明确禁止 |
|---|---:|---|---|
| `dayu_qgis_editor` | 是 | 读参考/治理/发布；四张暂存表 `SELECT/INSERT/UPDATE/DELETE` | 核心表 DML、发布、DDL |
| `dayu_qgis_reviewer` | 是 | 读参考、暂存、质检、审核和发布 | 任意 DML，角色默认只读事务 |
| `dayu_publisher` | 否 | 受控后端晋级/发布所需的最小表和序列权限 | 桌面直接登录、任意 schema DDL |
| `dayu_backend` | 是 | 非 owner 的 API/Worker 运行账号，继承发布组并按应用白名单读写 | 数据库所有权、角色管理、核心 schema DDL |
| `dayu_geoserver` | 是 | 只读 `publish` 的 12 个兼容视图 | `public` 核心表、暂存读取、DML、WFS-T |
| `dayu_qgis_server` | 是 | 只读 `publish.river|cross_section|gate|pump` | `public`、`staging_qgis`、`imports`、DDL/DML、任何其他角色成员资格 |
| `dayu_martin` | 是 | 只读来源表并执行 `tiles.*` | 写业务表 |

Compose 的 backend/worker 已使用 `dayu_backend`，迁移和角色引导仍由 owner 的一次性任务执行。运行账号降权不等于平台统一 IAM 已完成。

## 迁移

- `20260811_0001`：GIS 基线。
- `20260811_0002`：版本化水利数据库/拓扑。
- `20260812_0003`：EPSG:4490 与 Phase 3 任务结果。
- `20260812_0004`：快照、边界组、异步字段、闸泵拓扑、调度和节点/结构结果。
- `20260812_0005`：结构结果扬程差与泵转输语义。
- `20260812_0006`：优化任务、候选和 Pareto 结果。
- `20260812_0007`：AI 会话、知识/片段、工具调用和报告。
- `20260813_0008`：GIS 分析与版本化注记。
- `20260813_0009`：基础地图和搜索对象。
- `20260813_0010`：TimescaleDB、`imports`、`tiles`、时态状态和模型图层。
- `20260814_0011`：QGIS 暂存、GIS 治理审计、版本生命周期和 `publish` 视图。
- `20260814_0012`：补齐 12 个 GeoServer 兼容发布视图，并把服务读取边界收口到 `publish`。
- `20260815_0013`：新增权威 GIS Layer Registry 和受控 Basemap Registry。
- `20260815_0014`：以 ADD ONLY 方式新增横断面 location/axis/point/profile 及发布视图。

幂等 seed 在已有完整拓扑时复用节点，避免破坏历史结果外键和可追溯性。任何生产升级都必须先备份、运行迁移与权限集成测试，再开放 QGIS 编辑连接。
