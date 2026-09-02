# Repository Instructions

## Hydraulic Solver Development Policy

大禹·天工不以重新实现已有成熟水动力数值求解器为目标。

对于一维水动力、二维水动力、城市排水、水文计算、网格生成及其他已有成熟且许可证兼容的开源计算能力，应优先执行：

成熟开源方案检索
→ 技术与许可证审查
→ Adapter / CLI / Container 集成
→ Benchmark
→ 平台化封装。

平台核心研发资源集中于：

- Unified Hydraulic Data Model
- River Network
- Cross Section Database
- Hydraulic Structure Database
- Boundary Condition Manager
- Scenario Manager
- Model Builder
- Solver Adapter
- Job Manager
- Result Engine
- GIS
- 自动建模
- 成果分析
- 专业工作流

除非经过明确技术论证证明成熟开源方案无法满足实际工程需求，否则禁止从零重复开发生产级数值求解器。

当前默认技术路线：

- 1D：MASCARET
- Advanced 1D/2D：D-Flow FM reserved
- Standard 2D：TELEMAC-2D
- Fast flood：SFINCS
- Urban drainage：EPA SWMM
- Mesh：优先采用成熟开源 Mesh 工具

此前任何“自行开发生产级 1D Saint-Venant Solver”的历史要求均已废止。

HYDRO-DATA-01 的 Network → Branch → Chainage → Cross Section 数据架构继续保留。

业务层和前端不得直接依赖具体 Solver 文件格式。
所有 Solver 必须通过统一 Adapter 接入。

对真实工程数据、实测资料、外部模型结果和率定数据，禁止伪造、静默补齐或用合成数据替代后宣称工程验证通过。合成数据仅可用于软件回归测试，并必须明确标识。
