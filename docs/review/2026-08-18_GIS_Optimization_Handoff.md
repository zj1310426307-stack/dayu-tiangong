# 大禹天工 GIS 优化窗口交接说明

日期：2026-08-18
项目：`project-003-大禹天工`
仓库：`zj1310426307-stack/dayu-tiangong`
当前交付分支：`agent/gis-open-data-guangdong`
GitHub Draft PR：[#8](https://github.com/zj1310426307-stack/dayu-tiangong/pull/8)

## 1. 新窗口读取顺序

新窗口开始后按顺序读取：

1. `D:\CH\00_全局工作台.md`
2. `D:\CH\02_新项目SOP.md`
3. `D:\CH\01_全局复利与踩坑日志.md` 中 `L-20260817-01` 至 `L-20260818-02`
4. `D:\CH\project-003-大禹天工\README.md`
5. 本交接文件
6. 仓库 `README.md`、`docs/architecture.md`、`docs/gis/GIS_DEPLOY_GUIDE.md`

不得重置、清理或覆盖现有工作树。尤其不得删除历史审查基线 `docs/review/Phase1_GIS_Base_Audit_Report.md`。

## 2. 当前目标与架构结论

当前 GIS 底座已经收敛为：

```text
QGIS Desktop（受控生产）
        ↓
PostGIS（唯一权威数据中心）
        ↓
GeoServer（唯一 GIS 发布服务）
        ↓
FastAPI（版本、目录和安全网关）
        ↓
OpenLayers（唯一 WebGIS 渲染端）
```

保留约束：

- 不建立第二套 GIS 数据库。
- 不开放 WFS-T。
- QGIS 不直接修改生产核心表，只写受控暂存区。
- Web 前端不接收任意图层名、SQL、CQL 或外部瓦片 URL。
- QGIS Server、Cesium、Martin、TiTiler 和 GeoNode 已退出核心 WebGIS 运行链，不应重新引入。
- GeoServer 继续 KEEP，现有 Dataset Version 发布门禁继续保留。

## 3. 本轮已实现能力

### 3.1 广东开放参考数据

- 新增迁移 `0016`，建立强类型 `reference_data` 行政区、道路和水系表及发布视图。
- 已导入广东行政区 93 条、主要道路 168,554 条、主要水系 19,749 条。
- 原始名称保留用于来源审计，中文展示字段单独管理。
- 数据来源、许可、快照哈希和处理结果已归档在项目 `03_参考资料`。

### 3.2 高分辨率影像

- 新增迁移 `0017`。
- 默认底图为 Esri World Imagery，可在广东城市范围放大到建筑级。
- NASA Blue Marble 和 VIIRS 保留为备用影像，默认关闭。
- 影像经 FastAPI 白名单代理加载，禁止批量下载或制作离线影像包。

### 3.3 中文标注

- 新增迁移 `0018`，行政区、道路、水系增加 `name_zh`。
- 行政区 93/93 有中文展示名；道路 95,179 条、水系 4,680 条含已确认中文展示值。
- GeoServer 使用含 Noto Sans CJK SC 的定制镜像和三套中文 SLD。
- 无法确认的拼音、外文和未命名占位符不渲染，避免误标。

### 3.4 坐标定位

地图支持三种输入：

- EPSG:4326：经度、纬度。
- EPSG:3857：Web XY 米制坐标。
- CGCS2000 三度带：按 `X=东坐标`、`Y=北坐标` 输入，可选中央经线：
  - 111°E：EPSG:4546
  - 114°E：EPSG:4547
  - 117°E：EPSG:4548

用户给定坐标：

```text
X = 641444.743（东坐标）
Y = 2464480.899（北坐标）
```

转换对比：

- 111°E：约 `112.372295°E, 22.271271°N`
- 114°E：约 `115.372295°E, 22.271271°N`

中央经线必须由测量成果、`.prj` 或数据提供方确认，系统不能仅凭 X/Y 猜测。当前界面默认 114°E，但允许立即切换并回显经纬度。

### 3.5 地图工具菜单

- 地图顶部提供“图层管理”和“坐标定位”两个按钮。
- 初始均收起，最大化保留地图可视区域。
- 再次点击当前按钮可关闭；点击另一按钮时只打开一个面板。
- 工具保持挂载，仅使用 `hidden` 控制可见性，因此图层开关、坐标输入、转换结果和定位点不会因收起而丢失。
- 移动端同样保持顶部菜单和单面板展开。

## 4. 当前运行环境

访问地址：

```text
http://127.0.0.1:8080/gis?datasetVersionId=58
```

Docker Compose 项目名：

```text
dayu-tiangong-phase1
```

最近核验状态：

- frontend：运行中，端口 8080。
- backend：healthy，主机端口 8001。
- database：healthy，PostGIS 端口 5432。
- geoserver：healthy，仅绑定 `127.0.0.1:8081`。
- redis、worker：healthy。
- migrate、seed、qgis-bootstrap、app-bootstrap、geoserver-init、gis-catalog-seed：均 `Exited (0)`，属于正常一次性任务。

## 5. 最近验证证据

- 全量离线回归：`202 passed, 70 skipped`。
- OpenLayers/Catalog/工具菜单静态专项：`10 passed`。
- TypeScript typecheck：通过。
- 前端 production build：通过，仅保留既有大分块提示。
- `git diff --check`：通过，仅有 Windows CRLF 提示。
- 真实浏览器：
  - 默认只显示顶部工具菜单。
  - 两工具互斥展开、可再次点击收起。
  - 坐标面板收起再打开后输入和结果保留。
  - CGCS2000 两种中央经线转换结果正确显示。
  - 页面日志 `0 warning / 0 error`。
- Docker 持久环境：数据库、后端、GeoServer、Redis、Worker 健康。

常用验证命令：

```powershell
cd D:\CH\project-003-大禹天工\04_工作文件\dayu-tiangong
$env:PYTHONPATH='backend;.'
backend\.venv\Scripts\python.exe -m pytest -q

cd frontend
npm.cmd run typecheck
npm.cmd run build
```

## 6. 关键代码与文档

- Catalog 与影像代理：`backend/app/gis_catalog/`
- GeoServer 服务合同：`backend/app/geoserver/`
- 开放数据导入：`database/import_open_reference_data.py`
- 数据迁移：`database/migrations/versions/20260817_0016_*` 至 `0018_*`
- OpenLayers 地图：`frontend/src/gis/MapView.tsx`
- 图层管理：`frontend/src/gis/LayerManager.tsx`
- 坐标定位：`frontend/src/gis/CoordinateLocator.tsx`
- 坐标显示：`frontend/src/gis/Coordinate.tsx`
- 中文弹窗：`frontend/src/gis/Popup.tsx`
- GeoServer 中文样式：`geoserver/styles/*_open.sld`
- 当前架构：`docs/architecture.md`
- 部署与人工验收：`docs/gis/GIS_DEPLOY_GUIDE.md`
- Catalog 契约：`docs/gis/gis_catalog_contract.md`

## 7. Git 状态与保护要求

本次 GitHub 发布状态：

- 当前分支：`agent/gis-open-data-guangdong`
- 功能提交：`c3ecfc9`（`feat(gis): add Guangdong data and coordinate tools`）。
- 远端 `main`：`4d0c851`。
- `479b9fe` 与远端 `main` 的文件树一致；远端 `main` 多一个普通合并提交，因此当前差异可以形成干净 PR。
- Draft PR：[#8](https://github.com/zj1310426307-stack/dayu-tiangong/pull/8)，目标分支 `main`。
- PR 实时核验：46 个文件，3,041 行新增、168 行删除，`mergeable=true`、`mergeable_state=clean`。
- GitHub 当前无已上报的自动 checks；不能把“0 checks”写成“CI 已通过”，应以本文件记录的本地/运行验证为证据并继续人工审查。
- 远端原先仅保留 `main`；推送后临时增加本 PR 工作分支。PR 合并后可按用户授权删除该远端工作分支。

保护要求：

- 不得执行 `git reset --hard`、`git checkout -- <path>` 或删除工作树。
- 不得遗漏新增的 0016、0017、0018 迁移、中文 SLD、坐标定位组件和开放数据导入脚本。
- 不提交 `.env`、真实数据库密码、QGIS Auth Manager 数据或个人路径。
- Git 发布前必须再检查远端 `main`、PR 差异、敏感信息和 CI。

## 8. 已知限制

- 核心河道、断面、闸泵和模型参数仍为 DEMO DATA，不等于工程实测数据。
- 开放行政区、道路和水系是可追溯快照，不替代法定测绘或工程勘测成果。
- Esri World Imagery 是受许可约束的在线服务，清晰度和时相因地区而异。
- 用户给定 CGCS2000 坐标的实际中央经线仍未由原始测量资料确认。
- 统一 IAM、真实模型率定、PLC/SCADA 接入和生产高可用不在当前范围。

## 9. 新窗口建议的继续顺序

1. 先读取本文件及列出的权威文档。
2. 运行 `git status -sb`，确认没有丢失本轮文件。
3. 打开 GIS 页面，人工检查工具菜单、中文标注、影像和 CGCS2000 定位。
4. 若继续界面优化，优先处理移动端布局、菜单键盘操作和业务方视觉反馈；不得改变 Catalog 或 Dataset Version 语义。
5. 获取用户测量资料中的中央经线/分带信息，确认本次 X/Y 唯一正确位置。
6. 审查 Draft PR #8 的完整差异；确认无误后转为 Ready，再决定是否合入 `main` 并删除远端工作分支。

## 10. 给新窗口 Codex 的直接要求

```text
读取本交接文件后继续大禹天工 GIS 优化。
先核对工作树、Docker 和真实页面，不要重置或重做已经完成的内容。
保持 PostGIS → GeoServer → FastAPI → OpenLayers 单一 WebGIS 链路。
优先处理用户新反馈，并同步架构、验证和交付文档。
当前工作入口是 GitHub Draft PR #8。任何后续提交、转 Ready、合并或远端分支删除都必须基于实时 GitHub 状态执行并复核。
```
