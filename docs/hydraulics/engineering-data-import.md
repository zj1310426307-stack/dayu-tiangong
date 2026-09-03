# 工程数据导入

Production-04 延续 HYDRO-DATA 的两阶段原则：先读取文件、识别列和工程语义、计算 SHA-256、返回 Preview 与 Issues；用户确认后再次提交完整文件，后端重新解析并在单一事务中写入正式记录和审计事件。Preview 不写数据库，客户端返回的 Preview 也不能替代源文件成为正式导入证据。

## 支持范围

- 河网、断面与剖面继续使用 `/api/v1/hydraulic/imports/preview|commit`，支持现有 CSV、XLSX、GeoJSON、Shapefile ZIP 和受控 DXF 流程。
- Boundary 与 Observed H/Q 使用 `/api/v1/hydraulic/production/time-series/preview`；正式观测使用 `/observations/import` 再上传完整 CSV/XLSX。
- MIKE11 或其他外部模型的合法 CSV/XLSX 导出使用 `/external-results/preview` 和 `/external-results/import`。
- 不启动 MIKE11、不调用 DHI SDK、不解析受保护的原生工程文件，也不猜测未知版本。

## 河道、断面和 Boundary

河道导入必须明确源 CRS、米制 engineering CRS、轴序、中央经线和水平单位。中心线点按上游到下游依次录入，采用桩号必须严格递增；`flow_direction=forward` 表示表内点序就是水流方向。显示几何可保存为 EPSG:4490，但长度、投影和桩号只能在确认的投影坐标系中计算。河向、端点 Node 和 Branch chainage 未确认时不能进入正式模型。

断面支持 XYZ 点、扩展 station/elevation 表，以及公开 MIKE11 六列长表 `ID、TOPOID、里程、偏移、高程、river_name`。六列表中 `river_name` 必须填写已经导入当前 Dataset Version 的 `branch_code`；同一断面的连续点行可以省略重复身份，但每个新 profile 首行必须写全身份。断面组按各 Branch 的上游到下游顺序依次录入，里程必须非递减；同一位置的多个 TOPOID 可以同里程。解析器按 `(ID, TOPOID)` 分组并保持点序，不把不同测次合并。必须明确 Branch、chainage、横向 offset、垂直单位、高程基准和来源；同一断面不同测次保留为版本化 Profile，不静默覆盖。模板没有提供的岸顶、轴线或测点坐标必须保持 NULL/`pending`，不得从横距猜测。断面单独导入也会读取数据库中目标 Branch 的起止桩号，越界或倒序即整批拒绝，不把越界点夹到河段端点。

Boundary 导入必须声明 Q 或 H、单位、相对/绝对时间、时区、Branch/Node/chainage 和水位基准。缺测值保持 MISSING，不能填零。正式模拟要求上下游外部端点完整覆盖模拟时段。

## 观测资料

Observed H/Q 必须有 station、Branch、chainage、变量、单位、质量标记、时间基准、来源文件名和来源 SHA-256。水位必须声明与模型一致的垂直基准，或提供单独审核的基准转换；系统不会自动估计偏移。

示例映射：

```json
{
  "series_kind": "observation",
  "series_id": "OBS-H-01",
  "variable": "water_level",
  "unit": "m",
  "source": "survey archive reference",
  "branch_id": "12",
  "chainage_m": 3500.0,
  "station_id": "STA-01",
  "vertical_datum": "confirmed project datum",
  "time_basis": "absolute",
  "timezone": "Asia/Shanghai",
  "column_mapping": {"time": "DateTime", "value": "Stage", "quality_flag": "Quality"}
}
```

## 安全边界

上传使用统一大小预算、安全文件名和允许扩展名；XLSX 公式单元格被拒绝，CSV/XLSX 输出会中和公式注入前缀。服务端不根据文件名访问任意路径，不把上传内容写入源码树，也不把真实工程资料提交到 Git。
