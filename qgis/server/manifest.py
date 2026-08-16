"""Canonical hashing helpers for QGIS Server project manifests."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET


VOLATILE_LAYOUT_ATTRIBUTES = {"uuid", "templateUuid"}


def canonical_json_bytes(value: Any) -> bytes:
    """Serialize JSON deterministically for snapshots, revisions, and contract tests."""

    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    """Return a lowercase SHA-256 digest for stable manifest fields."""

    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    """Hash an immutable build input without interpreting its contents."""

    return sha256_bytes(path.read_bytes())


def canonical_xml_bytes(root: ET.Element) -> bytes:
    """Normalize XML attribute order, whitespace, and volatile layout UUIDs."""

    clone = ET.fromstring(ET.tostring(root, encoding="utf-8"))

    def normalize(element: ET.Element, *, in_layout: bool = False) -> None:
        """Normalize runtime metadata while retaining stable business and item IDs."""

        in_layout = in_layout or element.tag == "Layouts"
        for key in VOLATILE_LAYOUT_ATTRIBUTES:
            if key in element.attrib:
                element.set(key, "<volatile-layout-uuid>")
        if element is clone:
            for key in ("saveDateTime", "saveUser", "saveUserFull"):
                if key in element.attrib:
                    element.set(key, f"<volatile-{key}>")
        for key in ("mapUuid", "map_uuid"):
            if in_layout and key in element.attrib:
                element.set(key, "<volatile-layout-map-uuid>")
        if in_layout and element.tag == "layer" and "id" in element.attrib:
            element.set("id", "<volatile-layout-symbol-id>")
        if element.tag == "ProjectStyleSettings":
            for key in ("projectStyleId", "iccProfileId"):
                if key in element.attrib:
                    element.set(key, f"<volatile-{key}>")
        attributes = sorted(element.attrib.items())
        element.attrib.clear()
        element.attrib.update(attributes)
        if element.text is not None and not element.text.strip():
            element.text = None
        if element.tail is not None and not element.tail.strip():
            element.tail = None
        for child in element:
            normalize(child, in_layout=in_layout)

    normalize(clone)
    return ET.tostring(clone, encoding="utf-8", short_empty_elements=True)


def element_fingerprint(element: ET.Element | None) -> str:
    """Fingerprint one renderer/label subtree while handling an absent definition."""

    if element is None:
        return sha256_bytes(b"<absent>")
    return sha256_bytes(canonical_xml_bytes(element))


def project_revision(project_xml: bytes, semantic_manifest: dict[str, Any]) -> str:
    """Bind normalized QGIS XML and semantic manifest fields into one revision."""

    root = ET.fromstring(project_xml)
    payload = canonical_xml_bytes(root) + b"\n" + canonical_json_bytes(semantic_manifest)
    return sha256_bytes(payload)
