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

一个 profile 的首个点行必须写全 `ID、TOPOID、里程、river_name`；后续点行可以只写 `偏移、高程`。解析器只在当前 profile 组内前向继承身份，并按 `(ID, TOPOID)` 分组；没有新 ID 却改变 TOPOID、里程或 river_name 时拒绝导入。未知 river_name、少于三个点、非递增偏移或其他整批错误继续 fail closed。

断面单独导入时，校验器必须从目标 Dataset Version 的 `hydraulic.branch` 读取 `chainage_start_m/chainage_end_m`；不能只确认 Branch 编码存在。任何越界断面必须返回 `SECTION_CHAINAGE_OUTSIDE_BRANCH`，不得通过端点夹取把越界里程静默定位到河段端点。

六列模板没有位置 XY、断面轴线、测量日期、测量方法和分区糙率，因此这些值不得伪造：位置只能由已存在的 Branch 与里程插值得到，方向保持 `pending`，缺省糙率使用 API 明示默认值。需要完整勘测证据时使用扩展 CSV/API 合同补录。

`/data-center/rivers` 与 `/data-center/cross-sections` 只读取 `hydraulic` 权威模型；旧 `public.river` 和 `public.cross_section` API 继续作为兼容面存在，但前端不得绕过水动力 preview/commit 直接把它们当主数据编辑。
