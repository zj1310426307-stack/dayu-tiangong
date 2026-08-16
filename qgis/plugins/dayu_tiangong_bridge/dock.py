"""Small dock panel for platform status, validation, and transient issues."""

from __future__ import annotations

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtWidgets import (
    QDockWidget, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)
from qgis.core import QgsExpression, QgsFeatureRequest, QgsProject
from qgis.gui import QgsHighlight

from .api_client import BridgeApiClient, BridgeError
from .issue_layer import replace_issue_layer


class BridgeDock(QDockWidget):
    def __init__(self, iface, client: BridgeApiClient) -> None:
        super().__init__("大禹·天工 Bridge", iface.mainWindow())
        self.iface = iface
        self.client = client
        self.issue_layer = None
        self.issue_highlight = None
        self.issues_by_id = {}
        root = QWidget(self)
        layout = QVBoxLayout(root)
        form = QFormLayout()
        self.dataset = QSpinBox(); self.dataset.setRange(1, 2_147_483_647)
        self.batch = QSpinBox(); self.batch.setRange(1, 2_147_483_647)
        self.status = QLabel("尚未连接")
        self.identity = QLabel(client.identity_label)
        self.validation_status = QLabel("未读取")
        self.review_status = QLabel("未读取")
        self.publication_status = QLabel("未读取")
        form.addRow("Dataset Version", self.dataset); form.addRow("Batch", self.batch)
        form.addRow("身份", self.identity); form.addRow("API", self.status)
        form.addRow("Validation", self.validation_status)
        form.addRow("Review", self.review_status)
        form.addRow("Publish", self.publication_status)
        layout.addLayout(form)
        buttons = QHBoxLayout()
        refresh = QPushButton("刷新状态"); refresh.clicked.connect(self.refresh_status)
        validate = QPushButton("运行 Validation"); validate.clicked.connect(self.run_validation)
        issues = QPushButton("加载 Issues"); issues.clicked.connect(self.load_issues)
        validate.setEnabled(client.mutation_allowed)
        for button in (refresh, validate, issues): buttons.addWidget(button)
        layout.addLayout(buttons)
        self.detail = QLineEdit(); self.detail.setReadOnly(True); layout.addWidget(self.detail)
        self.issue_table = QTableWidget(0, 4)
        self.issue_table.setHorizontalHeaderLabels(["级别", "规则", "要素", "消息"])
        self.issue_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.issue_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.issue_table.itemSelectionChanged.connect(self.locate_selected_issue)
        layout.addWidget(self.issue_table)
        self.setWidget(root)
        self.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)

    def _show_error(self, exc: Exception) -> None:
        self.status.setText("离线 / 拒绝")
        self.detail.setText(str(exc))

    def refresh_status(self) -> None:
        try:
            health = self.client.get("health")
            self.status.setText(
                "在线" if health.get("status") == "healthy" else "服务降级"
            )
            try:
                batch = self.client.get("batch", batch_id=self.batch.value())
            except BridgeError as exc:
                if exc.status_code != 404:
                    raise
                self.validation_status.setText("暂无")
                self.review_status.setText("批次不存在")
                self.publication_status.setText("未读取")
                self.detail.setText(f"batch={self.batch.value()} · 不存在")
                return
            try:
                validation = self.client.get("validation", batch_id=self.batch.value())
                self.validation_status.setText(
                    f"run={validation.get('id')} · {validation.get('status')}"
                )
            except BridgeError:
                self.validation_status.setText("暂无")
            publications = self.client.get("publications")
            current = next(
                (
                    item for item in publications
                    if item.get("dataset_version_id") == self.dataset.value()
                ),
                None,
            )
            self.detail.setText(f"batch={batch.get('id')} · {batch.get('status')}")
            self.review_status.setText(
                f"{batch.get('status')} · {batch.get('review_submitted_by') or '未提交'}"
            )
            self.publication_status.setText(
                str(current.get("publication_status")) if current else "未发布"
            )
        except BridgeError as exc:
            self._show_error(exc)

    def run_validation(self) -> None:
        try:
            result = self.client.post("validate", batch_id=self.batch.value())
            self.detail.setText(f"validation={result.get('id')} · {result.get('status')}")
        except BridgeError as exc:
            self._show_error(exc)

    def load_issues(self) -> None:
        try:
            expected_batch = self.batch.value()
            validation = self.client.get("validation", batch_id=expected_batch)
            issues = self.client.get("issues", batch_id=expected_batch)
            if self.batch.value() != expected_batch:
                return
            run_id = validation.get("id")
            current_issues = [
                issue for issue in issues
                if issue.get("validation_run_id") == run_id
            ]
            self.issue_layer = replace_issue_layer(
                self.issue_layer, current_issues, expected_batch
            )
            self._populate_issue_table(current_issues)
            self.detail.setText(
                f"run={run_id} · issues={len(current_issues)} · memory only"
            )
            if not self.issue_layer.extent().isEmpty():
                self.iface.mapCanvas().setExtent(self.issue_layer.extent())
                self.iface.mapCanvas().refresh()
        except BridgeError as exc:
            self._show_error(exc)

    def _populate_issue_table(self, issues) -> None:
        self.issues_by_id = {int(issue["id"]): issue for issue in issues}
        self.issue_table.setRowCount(0)
        for issue in issues:
            row = self.issue_table.rowCount()
            self.issue_table.insertRow(row)
            severity = QTableWidgetItem(str(issue.get("severity", "")).upper())
            severity.setData(Qt.UserRole, int(issue["id"]))
            self.issue_table.setItem(row, 0, severity)
            self.issue_table.setItem(row, 1, QTableWidgetItem(str(issue.get("rule_code", ""))))
            self.issue_table.setItem(row, 2, QTableWidgetItem(str(issue.get("feature_ref") or "")))
            self.issue_table.setItem(row, 3, QTableWidgetItem(str(issue.get("message", ""))))
        self.issue_table.resizeColumnsToContents()

    def locate_selected_issue(self) -> None:
        selected = self.issue_table.selectedItems()
        if not selected or self.issue_layer is None:
            return
        issue_id = int(selected[0].data(Qt.UserRole))
        issue = self.issues_by_id.get(issue_id)
        if issue is None:
            return
        feature_ref = str(issue.get("feature_ref") or "")
        entity_type = str(issue.get("entity_type") or "")
        target_layer = None
        target_feature = None
        if feature_ref and entity_type:
            escaped = QgsExpression.quotedString(feature_ref)
            request = QgsFeatureRequest().setFilterExpression(
                f'"source_feature_id" = {escaped}'
            )
            for layer in QgsProject.instance().mapLayers().values():
                source = layer.source() if hasattr(layer, "source") else ""
                if f'table="staging_qgis"."{entity_type}"' not in source:
                    continue
                target_feature = next(layer.getFeatures(request), None)
                if target_feature is not None:
                    target_layer = layer
                    break
        if target_feature is None:
            request = QgsFeatureRequest().setFilterExpression(f'"issue_id" = {issue_id}')
            target_feature = next(self.issue_layer.getFeatures(request), None)
            target_layer = self.issue_layer
        if target_feature is None or target_layer is None or target_feature.geometry().isEmpty():
            return
        if self.issue_highlight is not None:
            self.issue_highlight.hide()
            self.issue_highlight = None
        self.issue_highlight = QgsHighlight(
            self.iface.mapCanvas(), target_feature.geometry(), target_layer
        )
        self.issue_highlight.setColor(QColor(255, 70, 55, 230))
        self.issue_highlight.setFillColor(QColor(255, 70, 55, 70))
        self.issue_highlight.setWidth(3)
        self.issue_highlight.show()
        extent = target_feature.geometry().boundingBox()
        extent.scale(1.5)
        self.iface.mapCanvas().setExtent(extent)
        self.iface.mapCanvas().refresh()

    def cleanup(self) -> None:
        if self.issue_highlight is not None:
            self.issue_highlight.hide()
            self.issue_highlight = None
        if self.issue_layer is not None:
            QgsProject.instance().removeMapLayer(self.issue_layer.id())
            self.issue_layer = None
