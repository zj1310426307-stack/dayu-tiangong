# 大禹·天工 QGIS 生产工程

本目录提供 QGIS Desktop 3.44 LTR 的受控数据生产模板。QGIS 只编辑
`staging_qgis`，核心表与 `publish` 视图只读；质检、审核、版本晋级与发布仍由
大禹·天工平台完成。

## 使用前准备

本仓库随项目提供的 Windows 便捷入口是 `Start_Dayu_QGIS.cmd`。它会使用短英文
盘符绕开 QGIS/Qt 对中文安装路径的 Python/SIP 模块加载缺陷，从忽略提交的
`.env` 读取 `QGIS_EDITOR_DB_PASSWORD`，拷贝并启动仓库内置 Dayu Tiangong Bridge，然后
打开正式工程。启动窗口存续期间会保持短盘符，直到 QGIS 退出；口令不会写入
`.qgs`、service 示例或日志。日常本机使用建议直接双击该入口。

1. 在操作系统用户目录创建本机专用的 PostgreSQL service 文件，并设置
   `PGSERVICEFILE` 指向该文件；可从 `docs/pg_service.conf.example` 复制。
2. service 名必须保持为 `dayu_qgis`。连接口令放入操作系统凭据设施、QGIS
   Authentication Manager 或 libpq 的用户级凭据文件，不提交到仓库。
3. 使用具备最小权限的数据库身份：编辑者只能写 `staging_qgis`，参考层、核心层
   和 `publish` 均由数据库授权保证只读。
4. 用 QGIS 3.44 LTR 打开 `projects/dayu_tiangong_ltr.qgs`。同一 LTR 系列的小版本
   可以升级，但提交项目前应先运行静态契约测试。

## 工程结构

- `01_REFERENCE_READONLY`：已发布版本的河道、河网节点、河段、行政区、道路、地名。
- `02_EDIT_STAGING`：四个可编辑暂存层——河道、横断面、闸门、泵站。
- `03_PUBLISH_READONLY`：供发布链检查的河道、横断面、闸门、泵站只读视图。

工程 CRS 为 CGCS2000（EPSG:4490）。捕捉容差使用屏幕像素；任何米制长度、面积、
缓冲或工程测量必须在经批准的 CGCS2000 投影坐标系中执行，不能用经纬度差代替米。

## 编辑边界

- 每个导入批次只对应一种 `entity_type`。子对象的 `river_code` 不与同批次
  `staging_qgis.river` 建立关系引用，避免制造不存在的跨批次依赖。
- `batch_id`、`source_feature_id`、`operation` 与业务必填字段由表单约束提供即时提示；
  `operation` 只允许“新增或更新（upsert）”和“删除（delete）”。数据库
  CHECK/UNIQUE 约束和 FastAPI 权威质检仍是最终门禁。
- `id`、`quality_status`、来源哈希、坐标系和时间戳等治理字段在表单中只读。新增
  暂存记录时，数据库批次溯源触发器根据 `batch_id` 从 `gis_import_batch` 权威回填
  `source_crs`、`target_crs`、`source_hash` 与 `operator`；QGIS 不允许操作者手填或
  覆盖这些来源事实。`survey_time` 是本次要素测量时间，允许编辑人员在 QGIS 中按
  实际资料补充或修正。
- 工程启用事务组、捕捉和拓扑编辑，但不会开放 WFS-T，也不会直接修改生产核心表。

## 样式边界

`styles/` 中的 QML 是桌面编辑样式的可审查源文件。GeoServer 的 SLD 继续独立维护，
不要把 QML 与 SLD 当成自动双向同步格式。

## 验证

从仓库根目录执行：

```powershell
backend\.venv\Scripts\python.exe -m pytest -q tests/test_qgis_project_contract.py
```

本项目已使用 QGIS 3.44.13 自带的 `qgis_process` 完成原生烟雾检查。如在其他机器
执行且程序不在 `PATH`，应显式设置 `QGIS_PROCESS_EXECUTABLE`，不应把跳过写成通过。
