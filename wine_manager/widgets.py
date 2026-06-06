import pathlib

from PySide6.QtCore import QFileInfo, Qt, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QLinearGradient, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QFileIconProvider,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QStyle,
    QVBoxLayout,
    QWidget,
)


APP_ART_WIDTH = 84
APP_FAVORITE_WIDTH = 38
APP_RUNTIME_WIDTH = 132
APP_PREFIX_WIDTH = 160
APP_ACTIONS_WIDTH = 126


_ICON_PROVIDER = QFileIconProvider()


def add_shadow(widget: QFrame, blur: int = 28, alpha: int = 36) -> None:
    widget.setGraphicsEffect(None)


def apply_button_variant(button: QPushButton, variant: str) -> None:
    button.setProperty("variant", variant)
    button.style().unpolish(button)
    button.style().polish(button)


def _icon_has_pixmap(icon: QIcon, size: int = 64) -> bool:
    return not icon.isNull() and not icon.pixmap(size, size).isNull()


def _theme_icon(names: list[str]) -> QIcon:
    for name in names:
        if QIcon.hasThemeIcon(name):
            icon = QIcon.fromTheme(name)
            if _icon_has_pixmap(icon):
                return icon
    return QIcon()


def _resolve_app_icon(exe_path: str) -> QIcon:
    if exe_path:
        file_info = QFileInfo(exe_path)
        if file_info.exists():
            icon = _ICON_PROVIDER.icon(file_info)
            if _icon_has_pixmap(icon):
                return icon

        suffix = pathlib.Path(exe_path).suffix.lower()
        if suffix == ".exe":
            icon = _theme_icon(["wine", "application-x-ms-dos-executable", "application-x-executable"])
            if _icon_has_pixmap(icon):
                return icon

    icon = _theme_icon(["application-x-executable", "application-octet-stream", "applications-games"])
    if _icon_has_pixmap(icon):
        return icon

    app = QApplication.instance()
    if app is not None and app.style() is not None:
        icon = app.style().standardIcon(QStyle.StandardPixmap.SP_FileIcon)
        if _icon_has_pixmap(icon):
            return icon
    return QIcon()


def _accent_from_title(title: str) -> QColor:
    seed = sum((index + 1) * ord(char) for index, char in enumerate(title))
    return QColor.fromHsl(seed % 360, 72, 146)


def _monogram(title: str) -> str:
    tokens = [token[0].upper() for token in title.split() if token and token[0].isalnum()]
    if not tokens:
        return "APP"
    return "".join(tokens[:3])


def _rounded_pixmap(pixmap: QPixmap, size: int, radius: int = 24, zoom_percent: int = 0) -> QPixmap:
    source_width = max(1, pixmap.width())
    source_height = max(1, pixmap.height())
    base_scale = max(size / source_width, size / source_height)
    zoom_factor = max(0.05, 1.0 + (zoom_percent / 100.0))
    target_width = max(1, round(source_width * base_scale * zoom_factor))
    target_height = max(1, round(source_height * base_scale * zoom_factor))
    scaled = pixmap.scaled(target_width, target_height, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)

    rounded = QPixmap(size, size)
    rounded.fill(Qt.transparent)

    painter = QPainter(rounded)
    painter.setRenderHint(QPainter.Antialiasing)
    path = QPainterPath()
    path.addRoundedRect(0, 0, size, size, radius, radius)
    painter.setClipPath(path)

    painter.fillPath(path, QColor("#0b1015"))

    x_position = (size - scaled.width()) // 2
    y_position = (size - scaled.height()) // 2
    painter.drawPixmap(x_position, y_position, scaled)
    painter.end()
    return rounded


def build_app_artwork_pixmap(
    title: str,
    exe_path: str = "",
    art_path: str = "",
    size: int = 144,
    zoom_percent: int = 0,
) -> QPixmap:
    if art_path:
        custom_pixmap = QPixmap(art_path)
        if not custom_pixmap.isNull():
            return _rounded_pixmap(custom_pixmap, size, zoom_percent=zoom_percent)
    return _draw_app_tile(title, size, exe_path)


def _draw_app_tile(title: str, size: int, exe_path: str = "") -> QPixmap:
    accent = _accent_from_title(title)
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    bg_grad = QLinearGradient(0, 0, 0, size)
    bg_grad.setColorAt(0.0, QColor("#131c26"))
    bg_grad.setColorAt(1.0, QColor("#060a0f"))
    painter.setPen(QColor("#1c2a38"))
    painter.setBrush(bg_grad)
    painter.drawRoundedRect(6, 6, size - 12, size - 12, 22, 22)

    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(accent.red(), accent.green(), accent.blue(), 24))
    painter.drawEllipse(18, 16, size - 36, size - 48)
    bar_grad = QLinearGradient(0, 16, 0, size - 16)
    bar_grad.setColorAt(0.0, QColor(accent.red(), accent.green(), accent.blue(), 220))
    bar_grad.setColorAt(1.0, QColor(accent.red(), accent.green(), accent.blue(), 40))
    painter.setBrush(bar_grad)
    painter.drawRoundedRect(16, 16, 8, size - 32, 4, 4)

    icon = _resolve_app_icon(exe_path)
    if _icon_has_pixmap(icon):
        icon_rect = pixmap.rect().adjusted(28, 22, -28, -30)
        icon.paint(painter, icon_rect, Qt.AlignCenter)
    else:
        painter.setPen(QColor("#e6edf4"))
        mono_font = QFont("Cantarell", 26 if size <= 144 else 44)
        mono_font.setBold(True)
        painter.setFont(mono_font)
        painter.drawText(pixmap.rect().adjusted(24, 14, -18, -28), Qt.AlignCenter, _monogram(title))

        bottom_bar = QLinearGradient(34, 0, size - 28, 0)
        bottom_bar.setColorAt(0.0, QColor(accent.red(), accent.green(), accent.blue(), 130))
        bottom_bar.setColorAt(0.65, QColor(accent.red(), accent.green(), accent.blue(), 28))
        bottom_bar.setColorAt(1.0, QColor(0, 0, 0, 0))
        painter.setBrush(bottom_bar)
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(34, size - 28, size - 62, 4, 2, 2)

    painter.end()
    return pixmap


def _draw_poster_placeholder(title: str, size: tuple[int, int]) -> QPixmap:
    width, height = size
    accent = _accent_from_title(title)
    pixmap = QPixmap(width, height)
    pixmap.fill(QColor("#080c10"))

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.fillRect(0, 0, width, height, QColor("#0b1015"))
    painter.setPen(QColor("#1f2a35"))
    painter.drawRoundedRect(18, 18, width - 36, height - 36, 26, 26)
    painter.fillRect(28, 28, 12, height - 56, QColor(accent.red(), accent.green(), accent.blue(), 170))
    painter.fillRect(56, 54, width - 100, height - 160, QColor(accent.red(), accent.green(), accent.blue(), 26))

    painter.setPen(QColor("#ecf2f7"))
    mono_font = QFont("Cantarell", 44)
    mono_font.setBold(True)
    painter.setFont(mono_font)
    painter.drawText(56, 94, width - 104, 104, Qt.AlignLeft | Qt.AlignVCenter, _monogram(title))

    title_font = QFont("Cantarell", 18)
    title_font.setBold(True)
    painter.setFont(title_font)
    painter.drawText(pixmap.rect().adjusted(56, 196, -40, -110), Qt.AlignLeft | Qt.TextWordWrap, title)

    painter.setPen(QColor(255, 255, 255, 64))
    painter.drawLine(56, height - 108, width - 68, height - 108)
    painter.drawLine(56, height - 88, width - 112, height - 88)
    painter.end()
    return pixmap


class SectionCard(QFrame):
    def __init__(self, title: str, subtitle: str = "", object_name: str = "SectionCard", parent=None):
        super().__init__(parent)
        self.setObjectName(object_name)
        add_shadow(self)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(14)

        self.title_label = QLabel(title)
        self.title_label.setObjectName("SectionTitle")
        root.addWidget(self.title_label)

        self.subtitle_label = QLabel(subtitle)
        self.subtitle_label.setObjectName("SectionSubtitle")
        self.subtitle_label.setWordWrap(True)
        self.subtitle_label.setVisible(bool(subtitle))
        root.addWidget(self.subtitle_label)

        self.body = QVBoxLayout()
        self.body.setSpacing(12)
        root.addLayout(self.body)


class StatBadge(QFrame):
    def __init__(self, label: str, parent=None):
        super().__init__(parent)
        self.setObjectName("StatBadge")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 7, 16, 7)
        layout.setSpacing(0)

        self.value_label = QLabel("-")
        self.value_label.setObjectName("StatBadgeValue")
        layout.addWidget(self.value_label)

        self.title_label = QLabel(label)
        self.title_label.setObjectName("StatBadgeLabel")
        layout.addWidget(self.title_label)

    def set_value(self, value: str) -> None:
        self.value_label.setText(value)


class ClickableLabel(QLabel):
    clicked = Signal()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class AppCard(QFrame):
    playRequested = Signal()
    settingsRequested = Signal()
    favoriteToggled = Signal(bool)
    removeRequested = Signal()
    artClicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("AppCard")
        self.setMinimumHeight(148)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        add_shadow(self, blur=18, alpha=24)

        root = QHBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(14)

        self.art_label = ClickableLabel()
        self.art_label.setObjectName("AppCardArt")
        self.art_label.setFixedSize(APP_ART_WIDTH, APP_ART_WIDTH)
        self.art_label.setAlignment(Qt.AlignCenter)
        self.art_label.setCursor(Qt.PointingHandCursor)
        self.art_label.setToolTip("Choose artwork")
        self.art_label.clicked.connect(self.artClicked.emit)
        root.addWidget(self.art_label)

        info_layout = QVBoxLayout()
        info_layout.setSpacing(6)

        self.title_label = QLabel("App")
        self.title_label.setObjectName("AppCardTitle")
        self.title_label.setTextFormat(Qt.PlainText)
        self.title_label.setWordWrap(False)
        self.title_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        info_layout.addWidget(self.title_label)

        self.path_label = QLabel("")
        self.path_label.setObjectName("AppCardPath")
        self.path_label.setTextFormat(Qt.PlainText)
        self.path_label.setWordWrap(False)
        self.path_label.setTextInteractionFlags(Qt.NoTextInteraction)
        self.path_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        info_layout.addWidget(self.path_label)

        self.summary_label = QLabel("Generated artwork based on the executable.")
        self.summary_label.setObjectName("AppCardSummary")
        self.summary_label.setTextFormat(Qt.PlainText)
        self.summary_label.setWordWrap(False)
        self.summary_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        info_layout.addWidget(self.summary_label)

        root.addLayout(info_layout, 1)

        self.favorite_button = QPushButton("☆")
        self.favorite_button.setObjectName("AppFavoriteButton")
        self.favorite_button.setCheckable(True)
        self.favorite_button.setCursor(Qt.PointingHandCursor)
        self.favorite_button.setFixedSize(APP_FAVORITE_WIDTH, APP_FAVORITE_WIDTH)
        self.favorite_button.toggled.connect(self._sync_favorite_button)
        self.favorite_button.clicked.connect(lambda checked: self.favoriteToggled.emit(checked))
        root.addWidget(self.favorite_button)

        self.meta_chip = QLabel("wine")
        self.meta_chip.setObjectName("AppCardChipRuntime")
        self.meta_chip.setAlignment(Qt.AlignCenter)
        self.meta_chip.setFixedSize(APP_RUNTIME_WIDTH, 34)
        root.addWidget(self.meta_chip, 0, Qt.AlignVCenter)

        self.prefix_chip = QLabel("prefix")
        self.prefix_chip.setObjectName("AppCardChipPrefix")
        self.prefix_chip.setAlignment(Qt.AlignCenter)
        self.prefix_chip.setFixedSize(APP_PREFIX_WIDTH, 34)
        root.addWidget(self.prefix_chip, 0, Qt.AlignVCenter)

        self.actions_panel = QWidget()
        self.actions_panel.setObjectName("AppActionsPanel")
        self.actions_panel.setFixedWidth(APP_ACTIONS_WIDTH)
        action_layout = QVBoxLayout(self.actions_panel)
        action_layout.setSpacing(8)
        action_layout.setContentsMargins(10, 10, 10, 10)
        action_layout.setAlignment(Qt.AlignVCenter)

        self.play_button = QPushButton("Run")
        self.play_button.clicked.connect(self.playRequested.emit)
        self.play_button.setFixedWidth(APP_ACTIONS_WIDTH - 20)
        self.play_button.setFixedHeight(34)
        apply_button_variant(self.play_button, "secondary")
        action_layout.addWidget(self.play_button)

        self.settings_button = QPushButton("Settings")
        self.settings_button.clicked.connect(self.settingsRequested.emit)
        self.settings_button.setFixedWidth(APP_ACTIONS_WIDTH - 20)
        self.settings_button.setFixedHeight(30)
        action_layout.addWidget(self.settings_button)

        self.remove_button = QPushButton("Remove")
        self.remove_button.clicked.connect(self.removeRequested.emit)
        self.remove_button.setFixedWidth(APP_ACTIONS_WIDTH - 20)
        self.remove_button.setFixedHeight(30)
        apply_button_variant(self.remove_button, "danger")
        action_layout.addWidget(self.remove_button)
        root.addWidget(self.actions_panel)

        self._set_art("App")

    def set_content(
        self,
        title: str,
        meta: str,
        prefix: str,
        exe_path: str = "",
        art_path: str = "",
        art_zoom: int = 0,
        is_favorite: bool = False,
        tooltip: str = "",
    ) -> None:
        self.title_label.setText(title)
        self.favorite_button.setChecked(is_favorite)
        self._sync_favorite_button(is_favorite)
        self.meta_chip.setText(meta)
        self.prefix_chip.setText(prefix)
        self.setToolTip(tooltip)
        self.path_label.setText(tooltip.split("\n", 1)[0])
        if art_path and is_favorite:
            self.summary_label.setText("Custom artwork is applied and the app is pinned as a favorite.")
        elif art_path:
            self.summary_label.setText("Custom artwork is applied for this entry.")
        elif is_favorite:
            self.summary_label.setText("Pinned as a favorite for faster access from the library.")
        else:
            self.summary_label.setText("Generated artwork is used until you choose a custom image.")
        self._set_art(title, exe_path, art_path, art_zoom)

    def _sync_favorite_button(self, is_favorite: bool) -> None:
        self.favorite_button.setText("★" if is_favorite else "☆")
        self.favorite_button.setToolTip("Remove Favorite" if is_favorite else "Add Favorite")

    def _set_art(self, title: str, exe_path: str = "", art_path: str = "", art_zoom: int = 0) -> None:
        pixmap = build_app_artwork_pixmap(title, exe_path, art_path, 144, art_zoom)
        self.art_label.setPixmap(pixmap.scaled(self.art_label.size(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation))


class PosterCard(QFrame):
    playRequested = Signal()
    settingsRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("PosterCard")
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumSize(150, 220)
        self.setMaximumWidth(210)
        add_shadow(self, blur=20, alpha=28)
        self._title = "App"
        self._image_path = ""

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.poster_label = QLabel()
        self.poster_label.setObjectName("PosterImage")
        self.poster_label.setMinimumSize(150, 220)
        self.poster_label.setAlignment(Qt.AlignCenter)
        self.poster_label.setScaledContents(False)
        root.addWidget(self.poster_label)

        self.overlay = QWidget(self.poster_label)
        self.overlay.setObjectName("PosterOverlay")
        self.overlay.hide()

        overlay_layout = QVBoxLayout(self.overlay)
        overlay_layout.setContentsMargins(12, 12, 12, 12)
        overlay_layout.setSpacing(8)
        overlay_layout.addStretch()

        self.info_panel = QWidget(self.overlay)
        self.info_panel.setObjectName("PosterInfoPanel")
        info_layout = QVBoxLayout(self.info_panel)
        info_layout.setContentsMargins(12, 12, 12, 12)
        info_layout.setSpacing(2)

        self.title_label = QLabel("App")
        self.title_label.setObjectName("PosterHoverTitle")
        self.title_label.setWordWrap(True)
        info_layout.addWidget(self.title_label)

        self.meta_label = QLabel("Wine")
        self.meta_label.setObjectName("PosterHoverMeta")
        self.meta_label.setWordWrap(True)
        info_layout.addWidget(self.meta_label)

        self.prefix_label = QLabel("prefix")
        self.prefix_label.setObjectName("PosterHoverPrefix")
        self.prefix_label.setWordWrap(True)
        info_layout.addWidget(self.prefix_label)

        overlay_layout.addWidget(self.info_panel)

        button_row = QHBoxLayout()
        button_row.setSpacing(8)

        self.play_button = QPushButton("Run")
        self.play_button.clicked.connect(self.playRequested.emit)
        button_row.addWidget(self.play_button)

        self.settings_button = QPushButton("Settings")
        self.settings_button.clicked.connect(self.settingsRequested.emit)
        button_row.addWidget(self.settings_button)
        overlay_layout.addLayout(button_row)
        self._set_placeholder("App")

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.overlay.setGeometry(self.poster_label.rect())
        if self._image_path:
            self._apply_image(self._image_path)
        else:
            self._set_placeholder(self._title)

    def enterEvent(self, event) -> None:
        self.overlay.show()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self.overlay.hide()
        super().leaveEvent(event)

    def set_content(self, title: str, meta: str, prefix: str, image_path: str = "", tooltip: str = "") -> None:
        self._title = title
        self._image_path = image_path
        self.title_label.setText(title)
        self.meta_label.setText(meta)
        self.prefix_label.setText(prefix)
        self.setToolTip(tooltip)
        if image_path and self._apply_image(image_path):
            return
        self._set_placeholder(title)

    def _apply_image(self, image_path: str) -> bool:
        pixmap = QPixmap(image_path)
        if pixmap.isNull():
            return False
        scaled = pixmap.scaled(
            self.poster_label.size(),
            Qt.KeepAspectRatioByExpanding,
            Qt.SmoothTransformation,
        )
        self.poster_label.setPixmap(scaled)
        return True

    def _set_placeholder(self, title: str) -> None:
        pixmap = _draw_poster_placeholder(title, (320, 460))
        self.poster_label.setPixmap(
            pixmap.scaled(self.poster_label.size(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
        )