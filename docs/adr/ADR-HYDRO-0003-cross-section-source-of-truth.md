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
