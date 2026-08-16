"""Load the repository bridge in the isolated Dayu QGIS profile."""

from qgis.core import Qgis, QgsMessageLog
import qgis.utils


PLUGIN_ID = "dayu_tiangong_bridge"


def _start_bridge() -> None:
    """Enable the bundled bridge without touching any governance mutation."""

    if PLUGIN_ID not in qgis.utils.plugins:
        if not qgis.utils.loadPlugin(PLUGIN_ID):
            raise RuntimeError("QGIS could not load the Dayu Tiangong Bridge")
        if not qgis.utils.startPlugin(PLUGIN_ID):
            raise RuntimeError("QGIS could not start the Dayu Tiangong Bridge")
    plugin = qgis.utils.plugins.get(PLUGIN_ID)
    if plugin is None:
        raise RuntimeError("Dayu Tiangong Bridge is unavailable after startup")
    plugin.show_dock()


try:
    _start_bridge()
except Exception as exc:  # QGIS must remain usable when the optional dock fails.
    QgsMessageLog.logMessage(str(exc), "Dayu Tiangong Bridge", Qgis.Critical)
