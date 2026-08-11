# GIS 模型所有权

数据库领域模型的唯一可执行定义位于：

```text
backend/app/gis/models.py
```

本目录只记录数据库模型归属，避免在 `database/` 与 `backend/` 复制两套 ORM。结构变更必须同时更新：

1. SQLAlchemy/GeoAlchemy2 模型；
2. Alembic 增量迁移；
3. `schema.sql` 当前结构快照；
4. OpenAPI 与数据库测试。
