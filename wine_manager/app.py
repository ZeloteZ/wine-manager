import sys

from PySide6.QtWidgets import QApplication

from .main_window import WineManagerWindow
from .theme import apply_theme


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Wine Manager")
    app.setApplicationVersion("2.0")
    apply_theme(app)

    window = WineManagerWindow()
    window.show()

    geometry = app.primaryScreen().availableGeometry()
    window.move(
        geometry.center().x() - window.width() // 2,
        geometry.center().y() - window.height() // 2,
    )
    return app.exec()