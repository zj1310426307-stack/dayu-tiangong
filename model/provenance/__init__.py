"""模型输入来源与确定性哈希公共入口。"""

from model.provenance.snapshot import canonical_json, snapshot_hash

__all__ = ["canonical_json", "snapshot_hash"]
