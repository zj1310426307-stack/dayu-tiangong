# ADR-HYDRO-0002：CGCS2000 坐标导入和米制计算

- 状态：Accepted
- 日期：2026-08-18

## 决策

每次导入必须携带强类型 CoordinateReferenceSpec：源 CRS、坐标模式、轴序、字段映射、水平/垂向单位、垂向基准、中央经线、带宽与带号前缀口径。缺少 CRS 或轴序时 fail closed，未知垂向基准不转换。

PostGIS/PROJ 是当前仓库已部署的后端权威转换引擎。preview 和 commit 必须使用同一配置与转换表达式，同时产生 EPSG:4490 展示几何和 network engineering CRS 米制几何。若后续引入 pyproj，必须与数据库 PROJ 版本和控制点结果对齐，不得在前端以 proj4 结果作为入库权威。

## 审计证据

保存原始 X/Y/Z、source CRS、axis mapping、转换管线描述、PROJ/PostGIS/GDAL 版本、源/目标包络、样点转换、配置 hash 和文件 SHA-256。commit 必须复核预览配置 hash 且只能写 draft Dataset Version。

## 禁止项

- 不根据字段名或数值大小猜轴序。
- 不自动猜中央经线或带号。
- 不用 `ST_SetSRID` 代替 `ST_Transform`。
- 不在 EPSG:4490 经纬度上计算距离、容差、长度或桩号。
