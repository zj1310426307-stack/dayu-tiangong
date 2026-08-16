"""QGIS plugin entrypoint."""


def classFactory(iface):  # noqa: N802 - QGIS plugin API name
    from .plugin import DayuTiangongBridge

    return DayuTiangongBridge(iface)
