# HYDRO-MODEL-02 数学模型与数值方程决策

- 文档状态：`MATHEMATICAL SPECIFICATION PROPOSED / NOT IMPLEMENTED`
- 用途：供水力负责人冻结未来实现必须满足的方程、符号和守恒边界
- 非用途：本文件不是当前求解器已通过的能力声明

## 1. 守恒变量

一维 Saint-Venant 主状态采用：

\[
\mathbf{U}=
\begin{bmatrix}
A\\Q
\end{bmatrix}
\]

其中：

- \(A(x,t)\)：过水面积，m²；
- \(Q(x,t)\)：有符号流量，m³/s；
- \(h(x,t)\)：水深，m；
- \(H=z_b+h\)：水位，m；
- \(T=\partial A/\partial h\)：水面宽，m。

流向以 Branch/Reach 正方向为正，但数值状态允许 \(Q<0\)。

## 2. 连续方程

\[
\frac{\partial A}{\partial t}
+\frac{\partial Q}{\partial x}
=q_l
\]

\(q_l\) 是单位河长侧向入流，正值入河、负值出河。节点泵送和内部结构物不应被重复计入
侧向外部通量。

## 3. 动量方程

棱柱断面的基本守恒形式：

\[
\frac{\partial Q}{\partial t}
+\frac{\partial}{\partial x}
\left(\beta\frac{Q^2}{A}+gI_1\right)
=gA(S_0-S_f)+S_m
\]

其中：

- \(\beta\)：断面动量修正系数；
- \(I_1\)：关于水面的静水压力一阶矩，若 \(b(z)\) 为高程 \(z\) 处的湿宽、
  \(H=z_b+h\)，则
  \[
  I_1(h)=\int_{z_b}^{H}(H-z)b(z)\,\mathrm{d}z
  \]
  本文采用正值约定，单位为 \(\mathrm{m^3}\)；
- \(S_0=-\partial z_b/\partial x\)：床坡；
- \(S_f\)：摩阻坡降；
- \(S_m\)：侧向动量、局部损失等显式声明的动量源项。侧向流量 \(q_l\) 的动量
  至少应包含冻结方向约定后的 \(q_l u_{l,x}\)；无动量入流、顺流入流和横向入流不能
  共用未声明的默认值。

对于分区断面，若按输水能力分配区间流量，候选闭合为：

\[
Q_i=Q\frac{K_i}{K},\qquad
\beta=\frac{A}{Q^2}\sum_i\frac{Q_i^2}{A_i}
\]

其中干区和 \(Q=0\) 必须进入独立有限分支。单一均匀速度的基准案例可以明确取
\(\beta=1\)；复式断面生产计算不得在未冻结 \(\beta\) 政策时隐式等同于 1。

对非棱柱河道，断面随 \(x\) 变化产生的几何源项必须与 \(I_1\) 和数值通量一致离散。
正式编码前应以离散 well-balanced 条件冻结其写法；不得继续用局部顶宽近似替代精确
静水压力矩后宣称适用于一般复式断面。

## 4. 断面函数

每个冻结 Profile 至少提供：

\[
A(h),\quad T(h),\quad P(h),\quad R(h)=\frac{A(h)}{P(h)},\quad I_1(h)
\]

以及反函数：

\[
h(A)
\]

所有查算函数要求：

- 在冻结范围内单调、有限；
- `A(h)` 与 `h(A)` 互相一致；
- 不在范围外静默外推；
- 插值方法、垂向步长、processor version 和 profile hash 写入 provenance；
- 面积、压力矩和水面宽使用同一个断面定义。

## 5. 分区糙率与输水能力

对粗糙率分区 \(i\)：

\[
K_i(h)=\frac{A_i(h)R_i(h)^{2/3}}{n_i}
\]

复合断面输水能力：

\[
K(h)=\sum_i K_i(h)
\]

有符号摩阻坡降：

\[
S_f=\frac{Q|Q|}{K(h)^2}
\]

该式仅在 wet state 且 \(K(h)>0\) 时有效；dry cell 必须走独立的正性/重湿分支，不能以
除零保护替代物理政策。各分区交界处的湿周是否计入、如何分配，必须由 processor policy
冻结并进入 hash，避免重复或漏计湿周。

`LeftBank/MainChannel/RightBank` 必须来自显式工程语义；任意 offset 区间仍可计算，但不能
从空间位置自动命名岸槽。未覆盖区间是否采用 default Manning n，属于冻结 processor policy。

## 6. 波速和流态

局部静水波速：

\[
c=\sqrt{gA/T}
\]

以下特征速度、Froude 数和第 8 节的 CFL 公式只适用于明确冻结 \(\beta=1\) 的 A2
reference baseline：

\[
\lambda_{1,2}=u\mp c,\qquad u=Q/A
\]

Froude 数：

\[
Fr=\frac{|u|}{c}
\]

若 \(\beta\neq1\) 且可视为常数，特征值至少应改为：

\[
\lambda_{1,2}=\beta u\mp\sqrt{c^2+\beta(\beta-1)u^2}
\]

若 \(\beta=\beta(A)\)，Jacobian 还必须包含其导数项，HLL 波速、CFL、Froude/临界流
判定和边界特征数都要随之重推。该闭合未冻结前，\(\beta\neq1\) 的复式断面不得进入
原生求解，只能返回 `not_ready`；不能把下面的 \(|u|+c\) 静默用于它。

边界条件数量、节点兼容关系和数值通量必须根据特征方向及亚/超临界状态确定。

## 7. 有限体积离散

对 cell \(i\)：

\[
\mathbf{U}_i^{n+1}
=\mathbf{U}_i^n
-\frac{\Delta t}{\Delta x_i}
\left(\widehat{\mathbf{F}}_{i+1/2}-\widehat{\mathbf{F}}_{i-1/2}\right)
+\Delta t\,\mathbf{S}_i
\]

首个 v4 原生实现选用 HLL 通量。现有 Rusanov 通量保留为 reference，用于交叉验证和问题
定位，不作为新路径唯一生产格式。

床坡与静水压力采用 hydrostatic reconstruction 或等价 well-balanced 离散，至少满足：

- lake-at-rest：\(Q=0\)、自由水面恒定；
- 面积非负；
- dry/wet 界面不产生非有限值；
- 几何变化源项与通量不产生伪波。

## 8. 时间积分

主线选择 SSP-RK2。每个 stage 都必须重新计算：

- 几何/波速；
- 数值通量；
- 摩阻和侧向源项；
- 节点兼容；
- Gate/Pump 通量；
- 边界状态。

对 \(\beta=1\) reference baseline，全局时间步：

\[
\Delta t_{CFL}
=CFL\cdot\min_i\frac{\Delta x_i}{|u_i|+c_i}
\]

实际步长还需截断到：

- 模拟结束；
- 下一个边界折点；
- 下一个调度动作；
- 下一个输出时刻；
- 失败重试后的缩步上限。

摩阻采用半隐式或经验证的算子分裂。任何 state clamp、step reject、重试和最小 dt 命中都
必须计入诊断。

## 9. 初始状态

v4 不允许只给一个全网标量水位/流量就默认可计算。允许的初态来源应显式区分：

- 逐断面/逐 cell 的 \(H,Q\)；
- 经验证的 steady warm start；
- 已成功任务的 restart snapshot；
- 明确声明的均匀初态，仅限适用 Benchmark。

初态必须满足断面查算范围、面积非负、网络拓扑和结构物初始状态。任何自动调整都必须
产生可审计 warning；物理不一致不得以静默 clamp 通过。

## 10. 边界方程

### 10.1 亚临界开边界

常见组合：上游给 \(Q(t)\)，下游给 \(H(t)\)。未给定的特征量从内部状态和特征兼容关系
获得，而不是简单复制相邻 cell 后覆盖一个变量。

### 10.2 超临界边界

按特征方向要求两个入射条件或零个入射条件。输入不足/过定必须在 preflight 或运行时明确
失败。

### 10.3 其他边界

rating curve、normal depth、closed、lateral inflow 和 restart 各自拥有强类型方程、单位、
插值和覆盖策略。默认禁止时域外常值延拓。

## 11. 节点方程

定义 \(q_{node}>0\) 为外部向节点注水，则节点质量守恒为：

\[
\sum Q_{in}-\sum Q_{out}+q_{node}=0
\]

同时需要与各相连支路特征和节点能头/局部损失相容。建议以节点水位或总水头及各支路
边界流量为未知量进行非线性求解。求解器必须报告：

- 质量残差；
- 能头/兼容残差；
- 迭代次数；
- 收敛状态；
- 缩步/失败原因。

长度倒数分流不是 Saint-Venant 节点方程，在原生 v4 模式中禁止作为 fallback。

## 12. Gate 方程

现有堰流、自由/淹没孔流和倒流方程可复用，但 Gate 流量必须用当前 RK stage 的上下游
水位求解。内部 face 两侧共享的是同一个有符号质量流量 \(Q_{gate}\)，以等量反号进入相邻
控制体；左右动量通量一般会因结构反力、局部损失和能头跳跃而不同，必须分别闭合，不能
复制同一个完整守恒通量向量。结构损失也不得在 face 与 Junction 方程中重复计入。开度
变化率、保持时长和可用性属于控制约束，不改变质量守恒。

Gate 方程与河道/节点状态若需要迭代，未在容差内收敛不得写入 success。

## 13. Pump 方程

Pump 需要求设备 Q-H 曲线与当前系统关系的工作点：

\[
H_{pump}(Q,N)=H_{system}(Q)
\]

内部转输以 intake/outlet 等量反号加入；外部进出流明确进入全域水量平衡。功率：

\[
P=\frac{\rho g Q H}{\eta(Q,N)}
\]

能量由已接受时间 stage 积分，不得把右端动作回填到上一时间区间。

## 14. 全域水量平衡

\[
R_V=
V_{final}-V_{initial}
-V_{external,in}+V_{external,out}
-V_{lateral,in}+V_{lateral,out}
\]

内部 Gate 和内部 Pump 转输不应重复计入外部收支，但应单独报告累计量。所有结构和边界
通量必须来自与状态推进相同的数值 stage。

无量纲残差 \(\epsilon_V=|R_V|/S_V\) 的尺度 \(S_V\) 和 pass/warning/fail 阈值属于版本化
validation policy。零库容的代数收支不能用来替代动态库容守恒。

## 15. 数值失败语义

以下任一情况不得产生 success：

- NaN/Inf；
- 负面积或无法解释的补水；
- CFL 超限且无法缩步；
- 节点/结构非线性不收敛；
- 断面查算越界；
- 边界时域不覆盖；
- 全域水量门失败；
- 快照/网格 hash 不一致；
- 未注册的 solver/result schema。

失败任务保留 diagnostics、最终接受时刻和原因，但不保留看似完整的成功结果。

## 16. 实现前待水力负责人冻结

1. 非棱柱断面 `I1` 与几何源项的最终离散形式；
2. 复式断面 \(\beta\) 政策、完整 Jacobian/HLL 波速、Froude/CFL 与 dry/wet 修正；
3. SSP-RK2 与半隐式摩阻的具体组合形式，包括 Lie/Strang 分裂或 IMEX 方案及其可声明阶数；
4. 节点能头/局部损失方程；
5. Gate/Pump 耦合容差和迭代策略；
6. dry/re-wet 阈值；
7. Benchmark 误差与收敛阈值；
8. 结果质量门和工程签字边界。

这些决策未冻结前，只允许原型研究，不允许发布“完整 Saint-Venant 已完成”的结论。
