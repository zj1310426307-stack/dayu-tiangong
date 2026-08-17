# GIS 数据治理架构

## 原则

1. PostGIS 单库保存权威数据、暂存、治理和发布视图。
2. QGIS Desktop 只生产数据，不充当在线服务。
3. FastAPI 集中执行状态机、内容哈希、质检、审核和晋级事务。
4. GeoServer 只读发布，OpenLayers 只读展示。
5. Web 无编辑、无 WFS-T，已发布版本不可原地修改。

## 链路

```text
QGIS / 受控导入
  → imports（raw landing，可选）
  → staging_qgis（typed staging）
  → validation run + issues
  → review
  → atomic promotion
  → dataset_version approved
  → publication
  → publish views
  → GeoServer / OpenLayers
```

raw landing 不等于 typed staging。存在 raw 表的批次只有在标准化完成、有 typed 行并通过门禁后才能进入 staged。

## 防漂移

- 权威字段按固定排序和无损规范形式生成 SHA-256；
- validation run 记录对应暂存哈希；
- review 绑定同一 validation generation；
- promotion 锁批次并再次计算暂存哈希；
- QGIS 编辑触发器与批次状态锁闭合并发写窗口；
- promotion 异常整体回滚，不留下幽灵版本或半批核心数据。

## 权限

编辑者只能写允许的暂存业务列，复核者只读，GeoServer 只读 publish，后端以非 owner 身份运行并继承发布组。任何角色 bootstrap 都会改变密码和授权，必须在明确授权的维护窗口执行。

## 发布与模型

发布 GIS 版本可被 WebGIS 读取，但不自动继承“模型已率定”结论。模型参数、边界条件和真实工况必须按独立验证流程准备；PLC/SCADA 不在当前治理链内。
