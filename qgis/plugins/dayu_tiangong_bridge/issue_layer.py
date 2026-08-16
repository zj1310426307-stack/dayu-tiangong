"""Create transient issue visualization without writing staging or project state."""

from __future__ import annotations

import json
from typing import Any

from qgis.PyQt.QtCore import QVariant
from qgis.core import QgsFeature, QgsField, QgsGeometry, QgsProject, QgsVectorLayer, Qgis


SEVERITY_LABELS = {"error": "ERROR", "warning": "WARNING", "info": "INFO"}


def build_issue_layer(issues: list[dict[str, Any]], batch_id: int) -> QgsVectorLayer:
    """Replace the transient memory layer for the selected batch/run."""

    layer = QgsVectorLayer("GeometryCollection?crs=EPSG:4490", f"Dayu validation issues · batch {batch_id}", "memory")
    layer.setFlags(layer.flags() | Qgis.MapLayerFlag.Private)
    layer.setCustomProperty("dayu/transient", True)
    provider = layer.dataProvider()
    provider.addAttributes([
        QgsField("issue_id", QVariant.LongLong), QgsField("batch_id", QVariant.LongLong),
        QgsField("validation_run_id", QVariant.LongLong), QgsField("entity_type", QVariant.String),
        QgsField("feature_ref", QVariant.String), QgsField("rule_code", QVariant.String),
        QgsField("severity", QVariant.String), QgsField("message", QVariant.String),
    ])
    layer.updateFields()
    features = []
    for issue in issues:
        severity = str(issue.get("severity", "")).lower()
        if severity not in SEVERITY_LABELS:
            continue
        feature = QgsFeature(layer.fields())
        feature.setAttributes([
            issue.get("id"), issue.get("batch_id"), issue.get("validation_run_id"),
            issue.get("entity_type"), issue.get("feature_ref"), issue.get("rule_code"),
            SEVERITY_LABELS[severity], issue.get("message"),
        ])
        geometry = issue.get("geometry")
        if isinstance(geometry, dict):
            feature.setGeometry(QgsGeometry.fromGeoJson(json.dumps(geometry)))
        features.append(feature)
    provider.addFeatures(features)
    layer.updateExtents()
    return layer


def replace_issue_layer(current: QgsVectorLayer | None, issues: list[dict[str, Any]], batch_id: int) -> QgsVectorLayer:
    project = QgsProject.instance()
    if current is not None:
        project.removeMapLayer(current.id())
    layer = build_issue_layer(issues, batch_id)
    project.addMapLayer(layer)
    return layer
