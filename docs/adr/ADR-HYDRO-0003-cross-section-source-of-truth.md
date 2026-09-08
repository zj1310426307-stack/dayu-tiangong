# ADR-HYDRO-0003：横断面唯一权威来源

- 状态：Accepted
- 日期：2026-08-18

## 决策

`hydraulic.cross_section` 只表示 Branch 上的断面位置、轴线、岸点、采用桩号和计算桩号。`hydraulic.cross_section_profile` 表示 Topography ID/测次，`cross_section_point` 属于 profile，糙率分区和查算结果也以 profile 为根。正式模型方案必须明确选择 active/selected profile。

旧 `public.cross_section.points JSON` 和 `roughness` 降为兼容投影：读时由 active profile 生成，短期写入在同一事务内转入新表，不允许 JSON 和规范化点独立发展。

## 回填优先级

1. 位置：`cross_section_location.geometry` 优先，否则 legacy point。
2. axis/岸点：仅使用 `cross_section_axis` 已有值；缺失时写 `axis_missing` issue，不伪造。
3. 剖面点：现有规范化 `cross_section_point` 优先，其次 `cross_section_profile.profile`，最后是 legacy `points JSON`。
4. 桩号：legacy station 作为 imported/adopted 初值；空间定位后另存 computed chainage、snap distance 和 difference，不静默覆盖。

## 处理和缓存

profile hash 由规范化点、marker、糙率分区、高程基准和单位生成。查算缓存键为 `profile_hash + processor_version + vertical_step_m`。计算复用 `model.geometry.sections.TabulatedSectionGeometry`，不复制第二套断面算法。

## MIKE11 六列断面模板合同

2026-09-03 起，公开横断面 Excel 模板采用 `ID、TOPOID、里程、偏移、高程、river_name` 六列长表。`ID` 映射 `section_code`，`TOPOID` 映射 profile，`里程`映射 Branch chainage，`偏移/高程`映射有序 profile point，`river_name` 是目标 `branch_code`，不是自由文本河名。

一个 profile 的首个点行必须写全 `ID、TOPOID、里程、river_name`；后续点行可以只写 `偏移、高程`。解析器只在当前 profile 组内前向继承身份，并按 `(ID, TOPOID)` 分组；没有新 ID 却改变 TOPOID、里程或 river_name 时拒绝导入。表内断面组按各 Branch 的上游到下游顺序录入，里程必须非递减；同一断面的多个 TOPOID 可以使用相同里程。未知 river_name、断面组里程倒序、少于三个点、非递增偏移或其他整批错误继续 fail closed。

断面单独导入时，校验器必须从目标 Dataset Version 的 `hydraulic.branch` 读取 `chainage_start_m/chainage_end_m`；不能只确认 Branch 编码存在。任何越界断面必须返回 `SECTION_CHAINAGE_OUTSIDE_BRANCH`，不得通过端点夹取把越界里程静默定位到河段端点。

六列模板没有位置 XY、断面轴线、测量日期、测量方法和分区糙率，因此这些值不得伪造：位置只能由已存在的 Branch 与里程插值得到，方向保持 `pending`，缺省糙率使用 API 明示默认值。需要完整勘测证据时使用扩展 CSV/API 合同补录。

## 深泓点与纵向深泓线

`marker_type=thalweg` 表示 Profile 中的最低高程深泓点；当六列模板未给 marker 时，解析器以最低高程派生标记。多个点高程并列最低时全部保留，不擅自选择一个，并产生 `SECTION_THALWEG_TIE` 供人工复核。

Branch 的 `centerline_role=thalweg` 表示所给中心线是沿河纵向深泓线。它与 `HydraulicCrossSectionInput.axis_points` 的横向断面测线是两个不同几何对象：纵向线不能用来确认横断面左右方向。局部断面基准 0 m 只写入 Coordinate Reference 的高程基准，不把 Profile 最低值提升为权威河床高程。

`/data-center/rivers` 与 `/data-center/cross-sections` 只读取 `hydraulic` 权威模型；旧 `public.river` 和 `public.cross_section` API 继续作为兼容面存在，但前端不得绕过水动力 preview/commit 直接把它们当主数据编辑。

## 剖面预览与 Marker 编辑语义

横断面数据库的剖面图必须读取当前 active profile 的全部 `cross_section_point`，按 `sequence` 排序后逐点直线连接。预览不得抽稀、补点或使用平滑插值；显示点数必须与该活动剖面的入库点数一致。深泓点、Marker 1（左堤防）和 Marker 3（右堤防）作为同一组原始点上的标记叠加展示，不生成新的测量点。

Marker 1/3 属于 Dataset Version 的受治理内容。只有 `draft` 状态允许修改；`published`、`approved`、`retired` 等只读版本只能查看。前端必须在发出写请求前禁用 Marker 选择与保存，并给出中文草稿指引；后端继续以不可变门禁作为最终权威，不能因前端状态失效而放宽已发布版本。
