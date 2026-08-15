# Processing

GIS-OPT-1 不引入自定义大型插件或重复几何算法。编辑人员优先使用 QGIS 原生的
“检查有效性”、Topology Checker、捕捉和 Processing 工具进行预检；正式质量结果
由平台的 PostGIS/FastAPI validation run 生成并保存。

后续只有在原生处理模型无法稳定复用既有校验链时，才在此目录增加小型、可测试的
处理模型，并先记录架构决策。
