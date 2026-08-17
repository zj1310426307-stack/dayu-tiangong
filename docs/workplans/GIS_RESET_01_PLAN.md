# GIS-RESET-01 实施计划

状态：2026-08-17 全部完成；隔离运行验收通过，持久环境部署待单独授权。

## 当前事实

重构从 `0eb6027` 开始，旧 GIS 已形成 Git bundle 和源码 ZIP。现有 QGIS 受控生产链、PostGIS 版本治理、GeoServer 发布视图均保留。

## 实施步骤

1. 新增 GeoServer-only PostGIS Catalog 和受控 WMS/FeatureInfo Gateway。
2. 移除 QGIS Server 路由、容器、manifest/builder 与专用数据库角色初始化。
3. 默认 Compose 移除 Martin、TiTiler、GeoNode 和 3D Tiles 运行依赖。
4. 使用 OpenLayers 重建 GIS 页面、图层管理和属性弹窗。
5. 同步 OpenAPI 生成客户端、迁移、权限、契约测试和架构文档。
6. 在隔离数据库和 Compose 项目中执行迁移、服务、浏览器闭环验证。

以上 6 项均已完成。

## 完成门禁

- 浏览器可打开地图并加载河道、断面、闸门、泵站。
- 图层开关、透明度、顺序与点击属性可用。
- Catalog 只返回 GeoServer 服务，不含 QGIS Server/Martin/TiTiler/Cesium/3D adapter。
- QGIS Desktop 工程和受控生产链测试继续通过。
- WFS 保持 Basic，无 Transaction/LockFeature。
- 前端类型检查、生产构建、离线回归和隔离 PostGIS 迁移通过。
