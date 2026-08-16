# Dayu Tiangong Bridge

QGIS 3.44 LTR 的薄平台桥接插件。它只调用固定 FastAPI 治理接口，显示批次、validation、issues、review 与 publication 状态；不连接数据库、不复制 QGIS 编辑/拓扑/表单能力，也不写 core、publish 或 staging。

- DEMO 默认显示 `UNVERIFIED LOCAL IDENTITY`。
- 生产模式设置 `DAYU_BRIDGE_MODE=production`；没有 `DAYU_IAM_TOKEN` 时所有 mutation fail closed。
- Issue 图层使用 Private memory layer，切换批次或卸载插件会清理，项目保存时不持久化。
- Token 只进入 Authorization header，不写日志、项目、属性表或异常文本。
