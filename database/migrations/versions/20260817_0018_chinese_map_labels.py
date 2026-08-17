"""Add reviewed Chinese labels for Guangdong reference layers.

Revision ID: 20260817_0018
Revises: 20260817_0017
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260817_0018"
down_revision: str | None = "20260817_0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# This list is intentionally migration-local.  It records the reviewed display
# mapping for the immutable geoBoundaries snapshot without rewriting source names.
ADMINISTRATIVE_LABELS = (
    ("Guangzhou Province", "广东省"),
    ("Boluoxian", "博罗县"),
    ("Chaoyangxian", "潮阳县"),
    ("Chaozhoushi", "潮州市"),
    ("Chenghaishi", "澄海市"),
    ("Chonghuashi", "从化市"),
    ("Dapuxian", "大埔县"),
    ("Deqingxian", "德庆县"),
    ("Dianbaxian", "电白县"),
    ("Dongguanshi", "东莞市"),
    ("Doumenxian", "斗门县"),
    ("Enpingshi", "恩平市"),
    ("Fengkaixian", "封开县"),
    ("Fengshunxian", "丰顺县"),
    ("Fogangxian", "佛冈县"),
    ("Foshanshi", "佛山市"),
    ("Gaomingshi", "高明市"),
    ("Gaoyaoshi", "高要市"),
    ("Gaozhoushi", "高州市"),
    ("Guangningxian", "广宁县"),
    ("Guangzhoushi", "广州市"),
    ("Haifengxian", "海丰县"),
    ("Haikangxian", "海康县"),
    ("Hepingxian", "和平县"),
    ("Heshanshi", "鹤山市"),
    ("Heyuanshi", "河源市"),
    ("Huadushi", "花都市"),
    ("Huaijixian", "怀集县"),
    ("Huazhoushi", "化州市"),
    ("Huidongxian", "惠东县"),
    ("Huilaixian", "惠来县"),
    ("Huiyangshi", "惠阳市"),
    ("Huizhoushi", "惠州市"),
    ("Jiangmenshi", "江门市"),
    ("Jiaolingxian", "蕉岭县"),
    ("Jiexixian", "揭西县"),
    ("Jieyangshi", "揭阳市"),
    ("Kaipingshi", "开平市"),
    ("Lechangxian", "乐昌县"),
    ("Lianjiangxian", "廉江县"),
    ("Liannanyaozuzizhixian", "连南瑶族自治县"),
    ("Lianpingxian", "连平县"),
    ("Lianzhoushi", "连州市"),
    ("Longchuanxian", "龙川县"),
    ("Longmenxian", "龙门县"),
    ("Lufengxian", "陆丰县"),
    ("Luodingshi", "罗定市"),
    ("Maomingshi", "茂名市"),
    ("Meizhoushi", "梅州市"),
    ("Nanaoxian", "南澳县"),
    ("Nanhaishi", "南海市"),
    ("Nanxiongxian", "南雄县"),
    ("Panyushi", "番禺市"),
    ("Pingyuanxian", "平远县"),
    ("Puningshi", "普宁市"),
    ("Qingxinxian", "清新县"),
    ("Qingyuanshi", "清远市"),
    ("Qujiangxian", "曲江县"),
    ("Raopingxian", "饶平县"),
    ("Renhuaxian", "仁化县"),
    ("Ruyuanyaozuzizhixian", "乳源瑶族自治县"),
    ("Shanshuishi", "三水市"),
    ("Shantoushi", "汕头市"),
    ("Shaoguanshi", "韶关市"),
    ("Shenzhenshi", "深圳市"),
    ("Shenzhenxian", "深圳县"),
    ("Shixingxian", "始兴县"),
    ("Shundeshi", "顺德市"),
    ("Sihuishi", "四会市"),
    ("Suixixian", "遂溪县"),
    ("Taishanshi", "台山市"),
    ("Wongyuanxian", "翁源县"),
    ("Wuchuanshi", "吴川市"),
    ("Wuhuaxian", "五华县"),
    ("Xinfengxian", "新丰县"),
    ("Xingningshi", "兴宁市"),
    ("Xinhuishi", "新会市"),
    ("Xinxingxian", "新兴县"),
    ("Xinyishi", "信宜市"),
    ("Xuwenxian", "徐闻县"),
    ("Yangchushi", "阳春市"),
    ("Yangshanxian", "阳山县"),
    ("Yangxixian", "阳西县"),
    ("Yingdeshi", "英德市"),
    ("Yongdingxian", "永定县"),
    ("Yunanxian", "郁南县"),
    ("Yunfushi", "云浮市"),
    ("Zengchengshi", "增城市"),
    ("Zhanjianghsi", "湛江市"),
    ("Zhaoqingshi", "肇庆市"),
    ("Zhijinxian", "紫金县"),
    ("Zhongshanshi", "中山市"),
    ("Zhuhaishi", "珠海市"),
)


def _replace_views(*, include_chinese_label: bool) -> None:
    """Keep view identity stable while appending or removing the display column."""

    if not include_chinese_label:
        # PostgreSQL permits appending columns with CREATE OR REPLACE but does
        # not permit removing them, so downgrade explicitly rebuilds the views.
        for view_name in ("waterway_open", "road_open", "administrative_area_open"):
            op.execute(f"DROP VIEW publish.{view_name}")
    suffix = ", name_zh" if include_chinese_label else ""
    op.execute(
        f"""
        CREATE OR REPLACE VIEW publish.administrative_area_open AS
        SELECT id, source, source_id, source_snapshot, name, address,
               administrative_level, metadata_json, geometry, imported_at{suffix}
          FROM reference_data.administrative_area
        """
    )
    op.execute(
        f"""
        CREATE OR REPLACE VIEW publish.road_open AS
        SELECT id, source, source_id, source_snapshot, name, address,
               road_type, metadata_json, geometry, imported_at{suffix}
          FROM reference_data.road
        """
    )
    op.execute(
        f"""
        CREATE OR REPLACE VIEW publish.waterway_open AS
        SELECT id, source, source_id, source_snapshot, name, address,
               waterway_type, metadata_json, geometry, imported_at{suffix}
          FROM reference_data.waterway
        """
    )


def upgrade() -> None:
    """Populate Chinese display labels while preserving raw source-name provenance."""

    for table_name in ("administrative_area", "road", "waterway"):
        op.add_column(
            table_name,
            sa.Column("name_zh", sa.String(length=256), nullable=True),
            schema="reference_data",
        )

    bind = op.get_bind()
    bind.execute(
        sa.text(
            "UPDATE reference_data.administrative_area "
            "SET name_zh = :name_zh WHERE name = :source_name"
        ),
        [
            {"source_name": source_name, "name_zh": name_zh}
            for source_name, name_zh in ADMINISTRATIVE_LABELS
        ],
    )
    missing = bind.execute(
        sa.text(
            "SELECT count(*) FROM reference_data.administrative_area "
            "WHERE name_zh IS NULL"
        )
    ).scalar_one()
    if missing:
        raise RuntimeError(f"CHINESE_ADMIN_LABEL_MISSING: {missing}")

    op.execute(
        """
        UPDATE reference_data.road
           SET name_zh = CASE
             WHEN name LIKE '未命名%' THEN NULL
             WHEN name ~ '[一-龥]' THEN name
             WHEN name ~ '^G[0-9]+$' THEN '国道 ' || name
             WHEN name ~ '^S[0-9]+$' THEN '省道 ' || name
             WHEN name ~ '^X[0-9]+$' THEN '县道 ' || name
             WHEN name ~ '^Y[0-9]+$' THEN '乡道 ' || name
             WHEN name ~ '^Old G[0-9]+$' THEN '旧国道 ' || substring(name FROM 5)
             WHEN name ~ '^New G[0-9]+$' THEN '新国道 ' || substring(name FROM 5)
             ELSE NULL
           END
        """
    )
    op.execute(
        """
        UPDATE reference_data.waterway
           SET name_zh = CASE
             WHEN name LIKE '未命名%' THEN NULL
             WHEN name ~ '[一-龥]' THEN name
             WHEN name = 'Qingtou River' THEN '青头河'
             ELSE NULL
           END
        """
    )

    op.alter_column(
        "administrative_area",
        "name_zh",
        existing_type=sa.String(length=256),
        nullable=False,
        schema="reference_data",
    )
    op.create_check_constraint(
        "ck_reference_admin_name_zh_chinese",
        "administrative_area",
        "name_zh ~ '[一-龥]'",
        schema="reference_data",
    )
    op.create_check_constraint(
        "ck_reference_road_name_zh_chinese",
        "road",
        "name_zh IS NULL OR name_zh ~ '[一-龥]'",
        schema="reference_data",
    )
    op.create_check_constraint(
        "ck_reference_waterway_name_zh_chinese",
        "waterway",
        "name_zh IS NULL OR name_zh ~ '[一-龥]'",
        schema="reference_data",
    )
    _replace_views(include_chinese_label=True)
    op.execute(
        """
        UPDATE gis_layer_registry
           SET feature_info_fields = CASE layer_key
             WHEN 'administrative_area' THEN '["id","source","source_id","name_zh","administrative_level"]'::jsonb
             WHEN 'road' THEN '["id","source","source_id","name_zh","road_type"]'::jsonb
             WHEN 'waterway' THEN '["id","source","source_id","name_zh","waterway_type"]'::jsonb
           END,
               updated_by = 'chinese-map-labels', revision = revision + 1
         WHERE layer_key IN ('administrative_area','road','waterway')
        """
    )


def downgrade() -> None:
    """Restore raw source-name views and remove Chinese display columns."""

    op.execute(
        """
        UPDATE gis_layer_registry
           SET feature_info_fields = '["id","source","source_id","name"]'::jsonb,
               updated_by = 'gis-open-data-guangdong', revision = revision + 1
         WHERE layer_key IN ('administrative_area','road','waterway')
        """
    )
    _replace_views(include_chinese_label=False)
    op.drop_constraint(
        "ck_reference_waterway_name_zh_chinese",
        "waterway",
        schema="reference_data",
        type_="check",
    )
    op.drop_constraint(
        "ck_reference_road_name_zh_chinese",
        "road",
        schema="reference_data",
        type_="check",
    )
    op.drop_constraint(
        "ck_reference_admin_name_zh_chinese",
        "administrative_area",
        schema="reference_data",
        type_="check",
    )
    for table_name in ("waterway", "road", "administrative_area"):
        op.drop_column(table_name, "name_zh", schema="reference_data")
