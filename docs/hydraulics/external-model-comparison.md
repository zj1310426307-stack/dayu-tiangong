# 外部模型交叉对比

MIKE11 在 Production-04 中是外部参考模型，不是真理。平台只读取用户有权使用并合法导出的 CSV/XLSX；不自动启动 MIKE11、不调用商业 SDK、不猜测原生文件布局，也不会为了贴合外部结果自动改参数。

## Mapping Wizard 合同

用户必须映射 Branch、chainage、time 以及至少一个 H/Q/V 列。Branch 名称映射逐项给出；chainage 可设置比例、原点、偏移和 same/reverse 方向，reverse 必须给出 Dayu 参考末端桩号。时间必须声明 relative/absolute 和时区。水位对比要求相同高程基准，或先完成外部审计转换。

外部模型名、版本、场景、基准、列映射、Branch/chainage 映射、源文件名和 SHA-256 随结果持久化。未知 MIKE11 版本保留 `UNKNOWN`，不能填造版本号。

## 对比输出

- 每个明确匹配位置的 H/Q 指标；变量和单位不混合。
- Dayu 与 External 的最大 H/Q/V 纵剖面及差值。
- H(t)/Q(t) 时间序列和逐时差值表。
- `reference_not_ground_truth=true`，报告必须解释可能差异：几何、边界、粗糙率、结构表达、时步、数值格式或基准转换。

生产工作台提供 longitudinal profile、time series 和 difference table 三种视图。没有合法导出结果时，对应真实工程状态为 `DATA_NOT_AVAILABLE`，不能用合成 MIKE11 曲线替代。
