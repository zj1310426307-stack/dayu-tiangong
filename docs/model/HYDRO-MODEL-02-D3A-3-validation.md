# HYDRO-MODEL-02-D3A-3 科学验证证据

## 独立科学门

### P1：非棱柱斜床静水

- 几何：6 个非同表格 Profile，宽度渐缩—渐扩，显式非零河床坡降。
- 初值/边界：恒定绝对水位，`Q=0`。
- 120 s 后最大水位漂移 `<=1e-10 m`，最大流量 `<=1e-10 m³/s`，相对水量平衡误差 `<=1e-12`。

### P2：无摩阻变宽动水

- 参考：独立 Bernoulli 亚临界根，平床、`n=0`、恒定 `Q=5 m³/s`。
- 25/50/100 网格水位 L1 相对误差：`1.7180e-5 / 8.6457e-6 / 4.3352e-6`。
- 水位观测阶：`0.9907 / 0.9959`。
- 流量 L1 相对误差：`2.5828e-5 / 1.3050e-5 / 6.5333e-6`。
- 流量观测阶：`0.9849 / 0.9981`。
- 100 网格最大能头误差：`2.1061e-5 m`；全部网格无 retry，水量平衡误差小于 `1e-15`。

### P3：变断面 + Manning + 坡降

- 参考：仅使用 Python 标准库的独立 standard-step；独立重写表格 Profile 的 A/T/P、Manning 摩阻坡和亚临界二分根。
- 工况：1,000 m，宽度 8→6→8 m，`n=0.02`，河床坡 `2e-4`，`Q=4 m³/s`，全湿亚临界。
- 20/40/80 网格水位 L1 误差：`2.9361e-3 / 1.4728e-3 / 7.4882e-4 m`，观测阶均不小于 0.8。
- 20/40/80 网格流量 L1 误差：`2.6739e-2 / 1.4173e-2 / 7.3957e-3 m³/s`，观测阶均不小于 0.8。
- 80 网格速度 L1 误差 `1.7136e-3 m/s`，能头 Linf 误差 `3.8283e-3 m`。
- 80 网格 `maximum_dt=0.4/0.2 s` 时间加密不降低验证质量；最大 CFL 远小于 0.5。

## 结构专项

- Gate 位于两个不同 Profile 之间；结果证据确认上下游 A、T、I1 均来自各自断面，左/右动量通量分别闭合。
- Pump 绑定于渐变家族中的独立源 Profile；6 h 案例中启泵、源水位响应、Q-H 工作点、功率/能量和外排体积证据全部完整。
- 6 h native-v4 端到端案例：20 个断面，12% 渐缩—渐扩，1 Gate，1 external Pump，水量平衡 PASS，最大摩阻数不大于 0.1。

## 回归门

- D3A-1：平床正 Manning，Gate/Pump 强耦合。
- D3A-2：显式线性斜床和标准步法。
- D1/D2：原有 native-v4、Worker、Artifact/状态冻结、构建身份与 legacy 水动力回归不可退化。
- Frontend/OpenAPI：D3A-3 可选，readiness 与生成客户端同源，类型检查和生产构建必须通过。

## 结论

D3A-3 通过 P1/P2/P3、网格/时间加密、不同 Profile Gate/Pump 组合和 D1/D2/D3A-1/2 回归后，可以作为受限的“单河渐变工程断面验证能力”发布。它不是通用一维河网、突变建筑物或生产预报能力。

## Hosted 封口

2026-08-29 在候选提交 `169c3846e26da373710abd4b271b84804cdb5b52` 上完成：

- `model02` run [`33254053757`](https://github.com/zj1310426307-stack/dayu-tiangong/actions/runs/33254053757)：D3A scientific validation、Frontend contract、Legacy hydraulic、MODEL02 Ubuntu Python 3.11、MODEL02 Windows Python 3.11 全部成功；
- `hydraulic-platform` run [`33254053772`](https://github.com/zj1310426307-stack/dayu-tiangong/actions/runs/33254053772)：D1 regression、D2 shipping runtime、D2 fault recovery、Backend v4 contract、Worker integration、PostGIS migration、Frontend OpenAPI 全部成功。

因此 D3A-3 科学门、跨平台门、D1/D2 冻结回归和 immutable shipping-runtime 均为 `PASS`。最终交付 PR 为 [#12](https://github.com/zj1310426307-stack/dayu-tiangong/pull/12)，状态必须保持 `NOT MERGED`。
