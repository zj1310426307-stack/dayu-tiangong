# HYDRO-MODEL-02 D3A-2 验证记录

## S1：斜床静水平衡

- 24 个平移表格断面，`dx=100 m`，`S0=2e-4`，`n=0.03`；
- 绝对水位恒定、`Q=0`，运行 3600 s；
- 全时域 `max(abs(Q)) <= 1e-10 m3/s`；
- 全时域绝对水位离散与漂移均 `<= 1e-10 m`；
- 相对水量平衡误差 `<= 1e-12`。

## S2：Manning 正常流

- 独立二分根求解矩形 Manning 公式，不调用生产几何或求解器；
- `B=10 m`、`n=0.03`、`S0=8e-4`、`Q=20 m3/s`；
- 独立正常水深 `1.7729062821012627 m`；
- 40 单元、3600 s 的受限均匀流参考保持 `max(abs(depth error)) <= 1e-9 m`、`max(abs(Q error)) <= 1e-9 m3/s`；
- 独立计算的摩阻坡度与显式床坡在 `1e-12` 相对误差内一致。

## S3：缓坡回水

独立 standard-step 路径仅使用 Python 标准库，自行计算 A/T/P、Froude、摩阻坡度、能量线和二分根；生产路径使用标准 hydrostatic-reconstruction + Manning 算子。

| 单元数 / CFL | H L1 (m) | H Linf (m) | Q L1 (m3/s) | 相对水量误差 |
| --- | ---: | ---: | ---: | ---: |
| 12 / 0.6 | 0.0089159121 | 0.0147743884 | 0.6443171696 | 1.79e-16 |
| 24 / 0.6 | 0.0044399377 | 0.0075527522 | 0.3250686827 | 5.95e-17 |
| 48 / 0.6 | 0.0022038038 | 0.0038173903 | 0.1632136372 | 3.57e-16 |
| 48 / 0.3 | 0.0016025267 | 0.0037990506 | 0.1608857843 | 5.95e-17 |

空间加密和 CFL 减半均未降低解的可信度；细网格通过 `H L1 <= 0.02 m`、`H Linf <= 0.05 m`、`Q L1 <= 0.25 m3/s` 门限。

## 六小时 Gate/Pump

- 显式线性床坡 `S0=1e-7`，20 个相同局部 Profile，所有河床字段为 `synthetic` 且带确认身份/时间；
- Gate 在 3015 s 打开，Pump 在 4020 s 启动；
- 662 个接受步，最大摩阻数 `0.0980445660 <= 0.1`；
- 摩阻重试 578 次，均为接受步前的受控减步，没有泄漏丢弃步证据；
- 相对水量平衡误差 `9.06e-16`；
- Pump 外排 `55.7640 m3`、输入能量 `0.331104 kWh`；
- Gate 最大能量方程残差 `9.73e-11 m <= 1e-10 m`。

## 自动门禁

- `tests/model02/test_d3a_slope_science.py`：S1/S2/S3、空间与时间/CFL 加密；
- `tests/model_engine/test_v4_d3a_2_execution.py`：显式能力、适配器、Gate/Pump 及失败关闭；
- `tests/model_engine/test_d3a_2_schema_metadata.py`：ORM、迁移 lineage、禁止 Profile 回填；
- `.github/workflows/model02.yml` 的 `D3A scientific validation` job 在 Ubuntu/Python 3.11 运行上述门禁；完整 MODEL-02 矩阵继续覆盖 Ubuntu/Windows。

## Hosted 证据

2026-08-29 在提交 `47d420b7889ea2ef97d75969c39c794c4341a17b` 上完成：

- `model02` run `33252260357`：Frontend contract、Legacy hydraulic、D3A scientific validation、MODEL02 Ubuntu Python 3.11、MODEL02 Windows Python 3.11 全部成功；
- `hydraulic-platform` run `33252260201`：Backend v4 contract、PostGIS migration、D1 regression、D2 fault recovery、Frontend OpenAPI、D2 shipping runtime、Worker integration 全部成功。

因此 D3A-2 的 S1/S2/S3、Gate/Pump 斜床案例、网格/CFL 加密、D1/D2 回归与 Hosted 门均为 PASS；D3A-3 才从该门之后解锁。
