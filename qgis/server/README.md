# QGIS Server deployment project

本目录实现 GIS-OPT-2A1 的确定性部署工程构建。人工只维护
`qgis/projects/dayu_tiangong_ltr.qgs`；`generated/` 是 Builder 输出，不允许人工编辑。

`bootstrap_registry.v1.json` 是 **TEMPORARY BOOTSTRAP SNAPSHOT**。B1 上线真实
`gis_layer_registry` 后，由受控 export 生成相同合同的 immutable snapshot；不得长期人工
维护两份 Registry。

首期只发布 Desktop `03_PUBLISH_READONLY` 中的 `river/cross_section/gate/pump`。其余
发布层继续走 `GEOSERVER_WMS_LEGACY`，Builder 不自动造层。

## Windows 构建

QGIS 3.44.13 安装在非 ASCII 路径时，可把 runtime 和仓库临时映射到短路径，
再在 QGIS Python 环境运行：

```text
<QGIS_RUNTIME>\bin\python-qgis-ltr.bat <REPOSITORY>\qgis\server\build_server_project.py
```

Builder 会把 datasource 改为 `service='dayu_qgis_server'`、只保留 `publish` allowlist、
创建 `Dayu_A4_Landscape`，写出 QGZ 后再由同一 QGIS 原生回读。GetPrint 仍保持禁用，
直到 PDF/PNG 内容、图例/标题/版本一致性和无路径/DSN/secret 检查完成。

输出：

```text
qgis/server/generated/dayu_tiangong_server.qgz
qgis/server/generated/dayu_tiangong_server.manifest.json
```

## 运行时双版本隔离证据

`verify_runtime.py` 会通过公开 FastAPI Gateway 检查两个已发布版本。
只有 GetMap 图像不同、且指定像素的 GetFeatureInfo 都命中且要素身份不相交，
才原子写入 `generated/dayu_tiangong_server.isolation.json`。证据必须绑定当前
`project_revision`；缺失、过期或不完整时，health 必须保持 degraded。
验证人需选择同时覆盖两个版本差异要素的 bbox 和像素点。

## 密钥与私有入口

QGIS Server 不映射宿主端口，只提供 Compose 私网内的 `/dayu-ows/`；外部请求必须
经 FastAPI Safe WMS Gateway。数据库口令位于忽略提交的
`qgis/server/generated/qgis_server_db_password.secret`，通过 Compose secret 只读挂载，启动时再
写入 tmpfs 上的 pgpass。不得将真实口令写入 `.env.example`、QGS/QGZ、Nginx 配置或镜像。
