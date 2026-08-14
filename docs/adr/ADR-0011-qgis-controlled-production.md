# ADR-0011：QGIS 受控生产链

- 状态：Accepted
- 日期：2026-08-13
- 适用阶段：GIS-OPT-1

## 背景

现有 DGIS 已具备 PostGIS 版本表、GeoServer/Martin/TiTiler 发布、Cesium 展示及模型/调度/AI 联动，缺口是专业桌面生产与可审计的数据晋级，而不是新的 WebGIS 内核。

## 决策

- QGIS 3.44 LTR 是专业数据生产端；
- Cesium 是 Web 二三维展示端；
- `dayu_tiangong` PostGIS 是唯一业务空间事实源；
- FastAPI 是批次、质检、审核、差异、晋级和发布控制面；
- GeoServer、Martin、TiTiler 是只读发布面；
- 数据通过 `imports/raw → staging_qgis → validation → review → dataset_version → publish` 流动；
- QGIS editor 只能写 `staging_qgis`，不能写核心表；
- GeoServer 保持 Basic WFS，禁止 WFS-T；
- 晋级创建新版本，不更新已冻结或已发布版本。

## 状态语义

批次状态由后端 service 单独管理：

```text
created → staged → validating → validation_failed | validated
validated → in_review → changes_requested | rejected | approved
approved → promoting → promoted → published
```

`gis_validation_run.status` 仅表示一次规则执行，`gis_review.decision` 仅表示一次人工决定，`dataset_version.status` 仅表示权威版本生命周期；三者不混用。

## 后果

- 保留现有服务和 URL 契约；0012 以 12 个兼容视图把 GeoServer 数据源切换到 `publish`，同时撤销核心表直读；
- 新增四类稳定暂存表、治理审计表、发布视图和最小权限角色；
- 新版本的模型配置与工程率定仍是独立门禁；
- 平台统一身份留待后续成熟 OIDC/IAM 集成，本阶段不自研账户系统。

## 2026-08-14 实施修订

隔离环境验证完成后，用户明确授权持久数据库迁移和服务边界收口。实施追加
`20260814_0012`、`app-bootstrap` 与 12 个发布兼容视图：GeoServer store 已从
`public` 切换到 `publish`；backend/worker 已从 owner 切换为非 owner 的
`dayu_backend`，并继承 `dayu_publisher`。本修订不改变“不开放 WFS-T、不让 QGIS
直写核心表、不建立第二数据库”的原决策。
