# Phase 4.0 水动力正确性加固

## 冻结输入与可复现性

`freeze_task_input()` 在任务创建事务中读取数据版本、方案、显式边界组、河网、断面、闸泵和参数，规范化 JSON 后计算 SHA-256。任务记录输入 schema、hash、引擎版本/commit；之后业务表变化不影响该任务。

v1 输入经适配继续独立河道求解；v2 输入进入河网求解。v1 结果仍返回 `series + diagnostics`，v2 返回扩展字段。

## 方程、离散与 well-balanced

单河道使用一维 Saint-Venant 守恒变量：

```text
∂A/∂t + ∂Q/∂x = 0
∂Q/∂t + ∂(Q²/A + g I₁)/∂x = gA(S₀ - S_f)
S_f = n² Q|Q| / (A² R^(4/3))
```

采用 Rusanov 数值通量、显式时间推进、CFL 自适应步长与 hydrostatic reconstruction 平衡床坡源项。变床静水基准实测最大速度 `4.64×10⁻¹⁶ m/s`，最大水位漂移 `0 m`，均优于 `1×10⁻⁴` 阈值。

## 断面几何

`RectangularSectionGeometry` 提供解析面积、顶宽、湿周、水力半径与反算水位；`TabulatedSectionGeometry` 使用水位—面积—顶宽—湿周表分段插值，要求水位/面积严格递增并禁止范围外静默外推。每河道至少 3 个断面；两个断面时明确拒绝并给出补测/增加断面提示。

## 边界与水量平衡

正式任务只读取 `simulation_case_boundary`，不扫描同版本其他边界，不静默回退。全域收支为：

```text
residual = Δstorage - (external_inflow + lateral_source
                       - external_outflow - lateral_sink)
```

内部闸泵转输单独披露而不进入外部净收支。相对残差阈值：`≤1e-3 pass`，`(1e-3,5e-3] warning`，`>5e-3 fail`。2 小时验收相对残差为 `6.74×10⁻¹⁷`。

## 适用边界

单河求解具备完整 Saint-Venant 动量方程；Phase 4 河网最低实现使用同步连续性/Manning 回水，不应等同于完整节点 Riemann 动量兼容。模型未经工程率定。
