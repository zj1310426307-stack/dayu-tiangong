"""Chinese-first contracts for Guangdong open reference labels."""

from database.import_open_reference_data import (
    ADMINISTRATIVE_NAME_ZH,
    _chinese_transport_label,
)


def test_reviewed_administrative_mapping_is_complete_and_chinese() -> None:
    """The immutable 93-feature source snapshot must have one unique Chinese label each."""

    assert len(ADMINISTRATIVE_NAME_ZH) == 93
    assert len(set(ADMINISTRATIVE_NAME_ZH.values())) == 93
    assert all(any("\u3400" <= char <= "\u9fff" for char in value) for value in ADMINISTRATIVE_NAME_ZH.values())
    assert ADMINISTRATIVE_NAME_ZH["Guangzhou Province"] == "广东省"
    assert ADMINISTRATIVE_NAME_ZH["Guangzhoushi"] == "广州市"
    assert ADMINISTRATIVE_NAME_ZH["Shenzhenshi"] == "深圳市"


def test_osm_label_normalization_never_emits_unreviewed_foreign_text() -> None:
    """Named Chinese features render; unnamed and unknown foreign names stay silent."""

    assert _chinese_transport_label("东江", "waterway") == "东江"
    assert _chinese_transport_label("Qingtou River", "waterway") == "青头河"
    assert _chinese_transport_label("G238", "road") == "国道 G238"
    assert _chinese_transport_label("Old G228", "road") == "旧国道 G228"
    assert _chinese_transport_label("未命名道路 123", "road") is None
    assert _chinese_transport_label("Kaitai Avenue", "road") is None
