# GIS 数据治理规范

## 治理原则

1. **单一事实源**：`dayu_tiangong` PostGIS 是唯一业务空间权威库，不复制第二套 GIS 数据库。
2. **原始不等于权威**：`imports` 和 `staging_qgis` 都是非权威区，必须经过可追踪的质检与人工审核。
3. **版本只增不改**：晋级创建新的 `dataset_version`，不覆盖历史核心对象，不漂移已冻结模型输入。
4. **职责分离**：QGIS 负责生产，FastAPI 负责状态和编排，PostGIS 负责约束，GeoServer/Martin/TiTiler 只读发布，Cesium 负责展示。
5. **成熟开源优先**：坐标/格式/几何分别复用 QGIS、GDAL/OGR、PostGIS；只自研水利字段、质量门禁、审核和晋级等必要领域逻辑。

## 数据分区

| 区域 | 可写主体 | 数据命运 |
|---|---|---|
| `imports` | 受控 GDAL 服务 | 每个 job 新建服务器命名表；保留来源证据，不直接发布 |
| `staging_qgis` | QGIS editor / 受控标准化流程 | 按 batch 修正；质检后若内容变化必须重新质检/审核 |
| `public` 核心表 | 晋级服务 | 新版本权威对象；历史版本不就地修改 |
| `publish` | 无直接 DML，视图 | 仅投影 `published` 版本 |
| `tiles` / COG | Martin/TiTiler 只读 | 发布投影与资产服务，不成为新事实源 |

## 来源追溯

每个 `gis_import_batch` 至少记录：

- 原文件名、格式、字节数和 SHA-256；
- 源 CRS、目标 CRS（固定 EPSG:4490）和映射版本；
- operator、survey_time、父版本和原始落地区；
- metadata/notes、暂存内容哈希和最终版本 ID。

每条暂存要素还保存 `source_feature_id`、`source_hash`、`source_payload` 和操作类型，使 issue、审核和权威版本可以回溯到来源要素。真实密码、token、个人路径和敏感身份信息不得进入这些字段。

## 质检规则

当前规则集 `gis-opt1.1` 检查：

- 批次非空；
- 几何非空、有效、类型正确且 SRID=4490；
- 目标 CRS 一致；
- 河道必填、长度、状态、简单线及声明/测地长度偏差提示；
- 横断面父版本河道引用、非负桩号、正糙率和剖面点数；
- 闸门父版本河道引用、宽/高/最大流量及状态；
- 泵站父版本河道引用、流量/扬程/功率、效率曲线及状态。

每次执行写入 `gis_validation_run`；每个问题写入 `gis_validation_issue`，包含 feature ref、rule code、severity、message、可选几何和 details。只有 `error=0` 才是 passed。warning 不自动阻断，但必须由审阅者结合工程背景判断。

## 审核与哈希

审核是追加式事件，`approve|reject|request_changes` 均绑定明确的 `validation_run_id` 和 `staging_content_hash`。`request_changes` 进入可编辑的 `changes_requested`，`reject` 为终态。校验后改变任何权威业务字段或几何都会改变哈希，旧审核不能继续用于晋级。

稳定 SHA-256 的输入使用规范排序和序列化，排除数据库自增 ID、自然行顺序和时间戳。晋级后的 `dataset_version.content_hash` 使用四类核心业务内容及稳定业务关联编码；用于识别内容，不替代数字签名或备份。

## 晋级与发布

晋级前置条件：批次 approved、最新质检 passed、无 error、最新批准与当前暂存哈希一致。服务锁定批次并在同一事务内：

1. 创建新版本并记录父版本、来源批次、变更摘要和审核信息；
2. 克隆父版本四类核心对象；
3. 按业务编码应用 `upsert/delete`；
4. 复用河网拓扑生成；
5. 计算内容哈希并写回版本/批次；
6. 提交事务。

任何一步失败都应整体回滚。同一来源批次与版本一一对应，使晋级幂等。发布是独立动作：写入 `gis_publication` 清单并把版本标记为 `published`，`publish.*` 才可见。

## 发布服务边界

- GeoServer：保留只读数据库角色、WMS、WMTS 和 Basic WFS；禁止 WFS-T。
- Martin：继续执行 `tiles.*`，按 `dataset_version_id` 过滤；本阶段不重写 MVT 函数。
- TiTiler：继续提供受登记 `/data/` COG；发布 manifest 可记录 COG，完整对象存储不在本阶段。
- Cesium：只展示、查询、版本切换、时间回放和模型结果，不复制 QGIS 编辑能力。
- `publish.*` 已补齐 12 个兼容视图，GeoServer store 已切换并撤销核心表直读；WMS/WMTS/Basic WFS/缓存/Cesium 契约已回归。

## 保留、退役与回滚

GIS-OPT-1 已保存 `parent_version_id`、`previous_publication_id` 和 `retired_at` 等追溯字段，但没有提供完整的版本退役/回滚 API。当前回退方式是重新发布一个已审查版本或创建纠正批次，不得删除仍被模型任务、调度或审计引用的历史版本。

原始批次、质检、审核和发布证据的保留期限需由工程/监管策略确定；在策略确定前不自动清理。备份、灾备、对象存储和 HA 不在本阶段。

## 安全与剩余风险

数据库角色已经限制桌面编辑面，backend/worker 也已改用非 owner 账号；但平台统一 OIDC/IAM 和端点 RBAC 尚未完成。actor/reviewer/publisher 当前是审计字段，不是经过统一身份提供商验证的生产身份。因此 mutation API 只能用于受控开发/验收环境。

数据为 DEMO，水动力模型未用真实工程资料率定，未接实时监测、PLC/SCADA 或控制设备；数据治理通过也不代表模型或调度可用于真实工程决策。
