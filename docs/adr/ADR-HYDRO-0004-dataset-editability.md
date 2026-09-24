# ADR-HYDRO-0004：Dataset Version 不可变、分支编辑与审计边界

- 状态：Accepted
- 日期：2026-09-13
- 取代范围：将已审核、已批准或已发布版本自动退回草稿的旧行为

## 决策

`DatasetVersion` 是工程数据、校核结论和计算快照的共同身份边界，不是一个可被原地重写的容器。只有同时满足 `status=draft` 与 `is_read_only=false` 的版本可以写入河网、断面、建筑物、Marker、参数、边界和计算方案等版本化数据。

`is_read_only` 只表示用户对**草稿**施加的额外编辑锁；它不能解锁、降级或覆盖审核、批准、发布、退役等业务状态。任何非草稿版本都不可原地编辑，即使 `is_read_only=false`。

## 分支编辑

需要修改非草稿工程数据时，必须调用 `POST /api/v1/model-data/dataset-versions/{id}/clone` 创建新的草稿版本。新版本保留：

- `parent_version_id`（来源版本）；
- 新的版本号、名称、创建人和创建时间；
- `status=draft`、`is_read_only=false`；
- 不继承内容 hash、审核、批准、发布或退役时间及审核人身份。

当前端收到 `DAYU_DATASET_VERSION_IMMUTABLE` 时，必须显示“基于此版本创建草稿”，而不是提供“解除只读”或“编辑后自动退草稿”。

## 删除语义

只有可写草稿可删除。删除前，服务会拒绝仍被派生版本引用的 Dataset Version；运行、发布、审计或其他数据库关系仍由明确外键保护。平台不会为了完成删除而静默删除历史运行证据。

## Standard 1D 与冻结快照

数据版本的批准/发布是 Standard 1D 权威计算的授权前提；冻结后的 Dispatch/Hydraulic snapshot 是独立不可变证据。批准或发布版本不得因用户点击编辑而改变身份、审核哈希或历史结论。

## 兼容性与迁移

本决策不新增表字段：`DatasetVersion.parent_version_id` 已存在于当前数据库迁移链。旧版本可继续查询；旧 Gate/Pump 资产仅作为历史调度计划读取兼容，不是新写入路径。

完整工程图的克隆范围会随实体关系增加而扩展；在没有明确复制和重映射每个依赖关系前，服务不得把未复制的工程数据伪装成新版本的权威数据。
