"""Atomically import curated Guangdong open reference data into PostGIS.

The command accepts newline-delimited GeoJSON generated from immutable source
snapshots.  It stages every row in temporary tables, validates minimum counts,
and only then replaces the public reference dataset in one transaction.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Iterable, Iterator

import psycopg


CHUNK_SIZE = 1_000

# geoBoundaries exposes this historical Guangdong snapshot with romanized
# shapeName values only.  Keep those source names untouched for provenance and
# maintain the reviewed Chinese display label separately.
ADMINISTRATIVE_NAME_ZH = {
    "Guangzhou Province": "广东省",
    "Boluoxian": "博罗县",
    "Chaoyangxian": "潮阳县",
    "Chaozhoushi": "潮州市",
    "Chenghaishi": "澄海市",
    "Chonghuashi": "从化市",
    "Dapuxian": "大埔县",
    "Deqingxian": "德庆县",
    "Dianbaxian": "电白县",
    "Dongguanshi": "东莞市",
    "Doumenxian": "斗门县",
    "Enpingshi": "恩平市",
    "Fengkaixian": "封开县",
    "Fengshunxian": "丰顺县",
    "Fogangxian": "佛冈县",
    "Foshanshi": "佛山市",
    "Gaomingshi": "高明市",
    "Gaoyaoshi": "高要市",
    "Gaozhoushi": "高州市",
    "Guangningxian": "广宁县",
    "Guangzhoushi": "广州市",
    "Haifengxian": "海丰县",
    "Haikangxian": "海康县",
    "Hepingxian": "和平县",
    "Heshanshi": "鹤山市",
    "Heyuanshi": "河源市",
    "Huadushi": "花都市",
    "Huaijixian": "怀集县",
    "Huazhoushi": "化州市",
    "Huidongxian": "惠东县",
    "Huilaixian": "惠来县",
    "Huiyangshi": "惠阳市",
    "Huizhoushi": "惠州市",
    "Jiangmenshi": "江门市",
    "Jiaolingxian": "蕉岭县",
    "Jiexixian": "揭西县",
    "Jieyangshi": "揭阳市",
    "Kaipingshi": "开平市",
    "Lechangxian": "乐昌县",
    "Lianjiangxian": "廉江县",
    "Liannanyaozuzizhixian": "连南瑶族自治县",
    "Lianpingxian": "连平县",
    "Lianzhoushi": "连州市",
    "Longchuanxian": "龙川县",
    "Longmenxian": "龙门县",
    "Lufengxian": "陆丰县",
    "Luodingshi": "罗定市",
    "Maomingshi": "茂名市",
    "Meizhoushi": "梅州市",
    "Nanaoxian": "南澳县",
    "Nanhaishi": "南海市",
    "Nanxiongxian": "南雄县",
    "Panyushi": "番禺市",
    "Pingyuanxian": "平远县",
    "Puningshi": "普宁市",
    "Qingxinxian": "清新县",
    "Qingyuanshi": "清远市",
    "Qujiangxian": "曲江县",
    "Raopingxian": "饶平县",
    "Renhuaxian": "仁化县",
    "Ruyuanyaozuzizhixian": "乳源瑶族自治县",
    "Shanshuishi": "三水市",
    "Shantoushi": "汕头市",
    "Shaoguanshi": "韶关市",
    "Shenzhenshi": "深圳市",
    "Shenzhenxian": "深圳县",
    "Shixingxian": "始兴县",
    "Shundeshi": "顺德市",
    "Sihuishi": "四会市",
    "Suixixian": "遂溪县",
    "Taishanshi": "台山市",
    "Wongyuanxian": "翁源县",
    "Wuchuanshi": "吴川市",
    "Wuhuaxian": "五华县",
    "Xinfengxian": "新丰县",
    "Xingningshi": "兴宁市",
    "Xinhuishi": "新会市",
    "Xinxingxian": "新兴县",
    "Xinyishi": "信宜市",
    "Xuwenxian": "徐闻县",
    "Yangchushi": "阳春市",
    "Yangshanxian": "阳山县",
    "Yangxixian": "阳西县",
    "Yingdeshi": "英德市",
    "Yongdingxian": "永定县",
    "Yunanxian": "郁南县",
    "Yunfushi": "云浮市",
    "Zengchengshi": "增城市",
    "Zhanjianghsi": "湛江市",
    "Zhaoqingshi": "肇庆市",
    "Zhijinxian": "紫金县",
    "Zhongshanshi": "中山市",
    "Zhuhaishi": "珠海市",
}


def _chinese_transport_label(name: str, kind: str) -> str | None:
    """Return a Chinese-only map label and suppress unreviewed foreign text."""

    if name.startswith("未命名"):
        return None
    if re.search(r"[\u3400-\u9fff]", name):
        return name
    if kind == "waterway" and name == "Qingtou River":
        return "青头河"
    route = re.fullmatch(r"(Old |New )?([GSXY])(\d+)", name)
    if route:
        age, prefix, number = route.groups()
        class_name = {"G": "国道", "S": "省道", "X": "县道", "Y": "乡道"}[prefix]
        age_name = {None: "", "Old ": "旧", "New ": "新"}[age]
        return f"{age_name}{class_name} {prefix}{number}"
    return None


def _snapshot(paths: Iterable[Path]) -> str:
    """Hash source files with path separators so the snapshot is reproducible."""

    digest = hashlib.sha256()
    for path in sorted(paths, key=lambda item: item.name):
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\0")
        with path.open("rb") as source:
            while block := source.read(1024 * 1024):
                digest.update(block)
        digest.update(b"\0")
    return f"sha256:{digest.hexdigest()}"


def _features(path: Path) -> Iterator[dict[str, Any]]:
    """Stream GeoJSON Text Sequences without loading a province into memory."""

    with path.open("r", encoding="utf-8") as source:
        for line_number, raw_line in enumerate(source, start=1):
            line = raw_line.lstrip("\x1e").strip()
            if not line:
                continue
            value = json.loads(line)
            if value.get("type") != "Feature" or not isinstance(value.get("geometry"), dict):
                raise ValueError(f"{path}:{line_number} is not one GeoJSON Feature")
            yield value


def _chunks(rows: Iterable[tuple[Any, ...]]) -> Iterator[list[tuple[Any, ...]]]:
    """Bound memory while retaining efficient PostgreSQL executemany batches."""

    chunk: list[tuple[Any, ...]] = []
    for row in rows:
        chunk.append(row)
        if len(chunk) >= CHUNK_SIZE:
            yield chunk
            chunk = []
    if chunk:
        yield chunk


def _admin_rows(paths: list[Path], snapshot: str) -> Iterator[tuple[Any, ...]]:
    """Map geoBoundaries ADM1/ADM2 features to the reference table contract."""

    for path in paths:
        level = "ADM1" if "adm1" in path.name.lower() else "ADM2"
        for feature in _features(path):
            properties = feature.get("properties") or {}
            source_id = f"{level}:{properties.get('shapeID') or feature.get('id')}"
            name = str(properties.get("shapeName") or source_id)
            try:
                name_zh = ADMINISTRATIVE_NAME_ZH[name]
            except KeyError as exc:
                raise ValueError(f"missing reviewed Chinese administrative label: {name}") from exc
            metadata = {
                "shapeISO": properties.get("shapeISO"),
                "shapeGroup": properties.get("shapeGroup"),
                "shapeType": properties.get("shapeType"),
            }
            yield (
                "geoBoundaries",
                source_id,
                snapshot,
                name,
                name_zh,
                "Guangdong, China",
                json.dumps(metadata, ensure_ascii=False),
                json.dumps(feature["geometry"], ensure_ascii=False, separators=(",", ":")),
                level,
            )


def _osm_rows(path: Path, snapshot: str, kind: str) -> Iterator[tuple[Any, ...]]:
    """Map curated OSM ways to road or waterway provenance records."""

    type_field = "highway" if kind == "road" else "waterway"
    for feature in _features(path):
        properties = feature.get("properties") or {}
        osm_id = str(properties.get("osm_id") or feature.get("id"))
        feature_type = str(properties.get(type_field) or "unknown")[:32]
        fallback = "未命名道路" if kind == "road" else "未命名水系"
        name = str(properties.get("name") or properties.get("ref") or f"{fallback} {osm_id}")[:256]
        name_zh = _chinese_transport_label(name, kind)
        metadata = {
            "osm_id": osm_id,
            "ref": properties.get("ref"),
            type_field: feature_type,
        }
        yield (
            "OpenStreetMap",
            f"way/{osm_id}",
            snapshot,
            name,
            name_zh,
            "Guangdong, China",
            json.dumps(metadata, ensure_ascii=False),
            json.dumps(feature["geometry"], ensure_ascii=False, separators=(",", ":")),
            feature_type,
        )


def _insert_chunks(cursor: psycopg.Cursor[Any], statement: str, rows: Iterable[tuple[Any, ...]]) -> int:
    """Insert bounded batches and return the exact accepted feature count."""

    count = 0
    for chunk in _chunks(rows):
        cursor.executemany(statement, chunk)
        count += len(chunk)
    return count


def import_reference_data(args: argparse.Namespace) -> dict[str, int]:
    """Stage, validate, and atomically replace all three reference datasets."""

    administrative_paths = [Path(value).resolve() for value in args.administrative]
    road_path = Path(args.roads).resolve()
    waterway_path = Path(args.waterways).resolve()
    osm_snapshot_path = Path(args.osm_snapshot_file).resolve()
    for path in [*administrative_paths, road_path, waterway_path, osm_snapshot_path]:
        if not path.is_file():
            raise FileNotFoundError(path)
    admin_snapshot = _snapshot(administrative_paths)
    osm_snapshot = _snapshot([osm_snapshot_path])

    connection = psycopg.connect(
        host=os.getenv("POSTGRES_HOST", "database"),
        port=int(os.getenv("POSTGRES_PORT", "5432")),
        dbname=os.getenv("POSTGRES_DB", "dayu_tiangong"),
        user=os.getenv("POSTGRES_USER", "dayu"),
        password=os.environ["POSTGRES_PASSWORD"],
    )
    with connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "CREATE TEMP TABLE import_administrative_area "
                "(LIKE reference_data.administrative_area INCLUDING DEFAULTS INCLUDING CONSTRAINTS INCLUDING IDENTITY) ON COMMIT DROP"
            )
            cursor.execute(
                "CREATE TEMP TABLE import_road "
                "(LIKE reference_data.road INCLUDING DEFAULTS INCLUDING CONSTRAINTS INCLUDING IDENTITY) ON COMMIT DROP"
            )
            cursor.execute(
                "CREATE TEMP TABLE import_waterway "
                "(LIKE reference_data.waterway INCLUDING DEFAULTS INCLUDING CONSTRAINTS INCLUDING IDENTITY) ON COMMIT DROP"
            )
            admin_count = _insert_chunks(
                cursor,
                """
                INSERT INTO import_administrative_area
                    (source,source_id,source_snapshot,name,name_zh,address,metadata_json,geometry,administrative_level)
                VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb,
                        ST_Multi(ST_CollectionExtract(ST_MakeValid(ST_Transform(
                            ST_SetSRID(ST_GeomFromGeoJSON(%s),4326),4490)),3)),%s)
                """,
                _admin_rows(administrative_paths, admin_snapshot),
            )
            road_count = _insert_chunks(
                cursor,
                """
                INSERT INTO import_road
                    (source,source_id,source_snapshot,name,name_zh,address,metadata_json,geometry,road_type)
                VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb,
                        ST_Multi(ST_CollectionExtract(ST_MakeValid(ST_Transform(
                            ST_SetSRID(ST_GeomFromGeoJSON(%s),4326),4490)),2)),%s)
                """,
                _osm_rows(road_path, osm_snapshot, "road"),
            )
            waterway_count = _insert_chunks(
                cursor,
                """
                INSERT INTO import_waterway
                    (source,source_id,source_snapshot,name,name_zh,address,metadata_json,geometry,waterway_type)
                VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb,
                        ST_Multi(ST_CollectionExtract(ST_MakeValid(ST_Transform(
                            ST_SetSRID(ST_GeomFromGeoJSON(%s),4326),4490)),2)),%s)
                """,
                _osm_rows(waterway_path, osm_snapshot, "waterway"),
            )
            counts = {
                "administrative_area": admin_count,
                "road": road_count,
                "waterway": waterway_count,
            }
            minimums = {
                "administrative_area": args.min_administrative,
                "road": args.min_roads,
                "waterway": args.min_waterways,
            }
            failures = [
                f"{name}={counts[name]}<{minimum}"
                for name, minimum in minimums.items()
                if counts[name] < minimum
            ]
            if failures:
                raise RuntimeError("OPEN_REFERENCE_IMPORT_TOO_SMALL: " + "; ".join(failures))
            cursor.execute(
                "TRUNCATE reference_data.administrative_area, reference_data.road, "
                "reference_data.waterway RESTART IDENTITY"
            )
            cursor.execute(
                "INSERT INTO reference_data.administrative_area "
                "(source,source_id,source_snapshot,name,name_zh,address,metadata_json,geometry,imported_at,administrative_level) "
                "SELECT source,source_id,source_snapshot,name,name_zh,address,metadata_json,geometry,imported_at,administrative_level "
                "FROM import_administrative_area"
            )
            cursor.execute(
                "INSERT INTO reference_data.road "
                "(source,source_id,source_snapshot,name,name_zh,address,metadata_json,geometry,imported_at,road_type) "
                "SELECT source,source_id,source_snapshot,name,name_zh,address,metadata_json,geometry,imported_at,road_type "
                "FROM import_road"
            )
            cursor.execute(
                "INSERT INTO reference_data.waterway "
                "(source,source_id,source_snapshot,name,name_zh,address,metadata_json,geometry,imported_at,waterway_type) "
                "SELECT source,source_id,source_snapshot,name,name_zh,address,metadata_json,geometry,imported_at,waterway_type "
                "FROM import_waterway"
            )
    return counts


def _parser() -> argparse.ArgumentParser:
    """Build the explicit command contract used by operators and verification."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--administrative", action="append", required=True)
    parser.add_argument("--roads", required=True)
    parser.add_argument("--waterways", required=True)
    parser.add_argument("--osm-snapshot-file", required=True)
    parser.add_argument("--min-administrative", type=int, default=20)
    parser.add_argument("--min-roads", type=int, default=1_000)
    parser.add_argument("--min-waterways", type=int, default=100)
    return parser


def main() -> None:
    """Execute the operator-facing importer and print machine-readable counts."""

    counts = import_reference_data(_parser().parse_args())
    print(json.dumps({"status": "imported", "counts": counts}, ensure_ascii=False))


if __name__ == "__main__":
    main()
