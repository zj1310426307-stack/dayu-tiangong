"""QGIS lifecycle wrapper for the controlled bridge dock."""

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import QAction

from .api_client import BridgeApiClient
from .dock import BridgeDock


class DayuTiangongBridge:
    def __init__(self, iface) -> None:
        self.iface = iface
        self.action = None
        self.dock = None

    def initGui(self) -> None:  # noqa: N802 - QGIS plugin API name
        self.action = QAction("大禹·天工 Bridge", self.iface.mainWindow())
        self.action.triggered.connect(self.show_dock)
        self.iface.addPluginToWebMenu("大禹·天工", self.action)

    def show_dock(self) -> None:
        if self.dock is None:
            self.dock = BridgeDock(self.iface, BridgeApiClient())
            self.iface.addDockWidget(Qt.RightDockWidgetArea, self.dock)
        self.dock.show(); self.dock.raise_()

    def unload(self) -> None:
        if self.dock is not None:
            self.dock.cleanup(); self.iface.removeDockWidget(self.dock); self.dock.deleteLater(); self.dock = None
        if self.action is not None:
            self.iface.removePluginWebMenu("大禹·天工", self.action); self.action.deleteLater(); self.action = None
