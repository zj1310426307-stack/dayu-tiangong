# HYDRO-MODEL-02-D3A-RC1-FIX1 Grid Family

## 冻结结论

FIX1 使用 `structure-aligned-voronoi-odd3-v1`，在任何新结果产生前固定为
`18 / 54 / 162` cells，空间加密比为 `3 / 3`。若该家族不能通过验收，FIX1 直接
FAIL；不允许按结果另选三层。

之所以使用奇数倍 3，而不是偶数倍约 2，是因为嵌套加密必须同时保留父网格 site
和父网格 face：Pump/monitor 绑定 exact control-volume centroid，Gate 绑定 exact
face。偶数细分不能同时保留两类几何对象；在每个旧 site gap 的 `1/3`、`2/3`
处插点则可同时保留。

## Base sites 与构造规则

18 个 base section sites（m）为：

```text
250, 750, 1250, 1750, 2150, 2470, 2850, 3230, 3600,
4200, 4800, 5400, 5700, 6000, 6300, 6600, 6900, 7366.666666666667
```

每次加密保持全部旧 sites，在每个相邻 gap 加入 `1/3`、`2/3` 两点；上游补
`first/3`，下游补 `7600-(7600-last)/3`。实际有限体积边界仍由生产适配器的
相邻 section 中点规则确定，不建立旁路 mesh。所有生成坐标先以有理数计算，再
投影为输入浮点值。

| level | cells | representative h | min cell | max cell | mesh SHA-256 |
| --- | ---: | ---: | ---: | ---: | --- |
| coarse | 18 | 422.222222 m | 300.000000 m | 600.000000 m | `7f65fd66aa5f58bc1e605c3775dc9bdc0660b5938f568dd68fa3b6341d0f5349` |
| medium | 54 | 140.740741 m | 100.000000 m | 200.000000 m | `221ac5e93d132a4da34cabb032a0835011e71a4cd3d6daa87c4326c42490a724` |
| fine | 162 | 46.913580 m | 33.333333 m | 66.666667 m | `eeac4f93b9a33130387b3988c90d241f53e11687e0595558b5a3896e2541676f` |

hash 覆盖 grid family、level、完整 section chainages、face chainages、cell lengths
与 control-volume centroids；因此 CI 可拒绝结果挑选或位置漂移。

## Structure/location 证明

| 对象 | 绑定 | coarse / medium / fine 映射 | 位置误差 |
| --- | --- | --- | ---: |
| Gate | exact internal face | `3040 / 3040 / 3040 m` | `0 / 0 / 0 m` |
| Pump | exact CV centroid | `6000 / 6000 / 6000 m` | `0 / 0 / 0 m` |
| monitor | exact CV centroid | `2850 / 2850 / 2850 m` | `0 / 0 / 0 m` |

Base monitor cell 为 `[2660, 3040] m`，几何中心是 `2850 m`，其右边界同时是 Gate
face。Base Pump cell 为 `[5850, 6150] m`，几何中心是 `6000 m`。奇数倍加密保持
这些父 site 与父 face，因此三个位置在所有层不漂移。

## 同一物理问题

三层仅改变预先声明的空间分辨率：

```text
z_b(x) = 9.0 - 1e-7*x
width(x) = 20*(1 - 0.12*sin(pi*x/7600))
n(x) = 0.025
H0(x) = 10.0 (x<3040), otherwise 9.8
```

边界序列、Gate/Pump 参数、控制算法、Manning、bed/source、非棱柱通量/源项、
runtime envelope、摩阻预测器和任务平台均未改变。机器可读的完整坐标与绑定见
`outputs/d3a/final-convergence-fix1.json` 每层 `manifest`。
