from __future__ import annotations

import pathlib
import shlex
import threading

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QFont, QIcon, QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from .services import (
    ConfigStore,
    GamescopeSettings,
    LogManager,
    ProgramScanner,
    ProtonManager,
    ProtonRelease,
    is_system_executable,
    normalize_app_name,
    search_artwork_suggestions,
)
from .theme import LOG_LEVEL_COLORS
from .widgets import SectionCard, add_shadow, build_app_artwork_pixmap


def _apply_variant(button: QPushButton, variant: str) -> None:
    button.setProperty("variant", variant)
    button.style().unpolish(button)
    button.style().polish(button)


def _make_chip(text: str, accent: bool = False) -> QLabel:
    label = QLabel(text)
    label.setProperty("chip", True)
    if accent:
        label.setProperty("accent", True)
    label.style().unpolish(label)
    label.style().polish(label)
    return label


def _gamescope_summary(settings: GamescopeSettings) -> str:
    if not settings.enabled:
        return "Gamescope off"

    parts = ["Gamescope on"]
    if settings.width > 0 and settings.height > 0:
        parts.append(f"{settings.width}x{settings.height}")
    elif settings.width > 0:
        parts.append(f"W {settings.width}")
    elif settings.height > 0:
        parts.append(f"H {settings.height}")
    if settings.refresh_rate > 0:
        parts.append(f"{settings.refresh_rate} Hz")
    if settings.fullscreen:
        parts.append("fullscreen")
    elif settings.borderless:
        parts.append("borderless")
    if settings.extra_args:
        parts.append("extra args")
    return " | ".join(parts)


class GamescopeEditor(QFrame):
    settingsChanged = Signal()

    def __init__(self, show_toggle: bool, description: str = "", parent=None):
        super().__init__(parent)
        self._syncing = False
        self._fields_enabled = True
        self.enabled_box: QCheckBox | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        if description:
            hint = QLabel(description)
            hint.setObjectName("MutedText")
            hint.setWordWrap(True)
            root.addWidget(hint)

        if show_toggle:
            self.enabled_box = QCheckBox("Enable gamescope")
            self.enabled_box.toggled.connect(self._on_control_changed)
            root.addWidget(self.enabled_box)

        resolution_row = QHBoxLayout()
        resolution_row.setSpacing(8)

        width_label = QLabel("Width")
        resolution_row.addWidget(width_label)
        self.width_spin = QSpinBox()
        self.width_spin.setRange(0, 16384)
        self.width_spin.setSpecialValueText("Auto")
        self.width_spin.valueChanged.connect(self._on_control_changed)
        resolution_row.addWidget(self.width_spin)

        height_label = QLabel("Height")
        resolution_row.addWidget(height_label)
        self.height_spin = QSpinBox()
        self.height_spin.setRange(0, 16384)
        self.height_spin.setSpecialValueText("Auto")
        self.height_spin.valueChanged.connect(self._on_control_changed)
        resolution_row.addWidget(self.height_spin)

        refresh_label = QLabel("Refresh")
        resolution_row.addWidget(refresh_label)
        self.refresh_spin = QSpinBox()
        self.refresh_spin.setRange(0, 360)
        self.refresh_spin.setSuffix(" Hz")
        self.refresh_spin.setSpecialValueText("Auto")
        self.refresh_spin.valueChanged.connect(self._on_control_changed)
        resolution_row.addWidget(self.refresh_spin)
        resolution_row.addStretch()
        root.addLayout(resolution_row)

        mode_row = QHBoxLayout()
        mode_row.setSpacing(12)
        self.fullscreen_box = QCheckBox("Fullscreen")
        self.fullscreen_box.toggled.connect(self._on_control_changed)
        mode_row.addWidget(self.fullscreen_box)

        self.borderless_box = QCheckBox("Borderless")
        self.borderless_box.toggled.connect(self._on_control_changed)
        mode_row.addWidget(self.borderless_box)
        mode_row.addStretch()
        root.addLayout(mode_row)

        extra_label = QLabel("Extra Args")
        root.addWidget(extra_label)
        self.extra_args_edit = QLineEdit()
        self.extra_args_edit.setPlaceholderText("Optional extra arguments, e.g. -w 1280 -h 720")
        self.extra_args_edit.textChanged.connect(self._on_control_changed)
        root.addWidget(self.extra_args_edit)

        self._apply_field_state()

    def _on_control_changed(self) -> None:
        self._apply_field_state()
        if not self._syncing:
            self.settingsChanged.emit()

    def _apply_field_state(self) -> None:
        active = self._fields_enabled
        if self.enabled_box is not None:
            active = active and self.enabled_box.isChecked()
        for widget in [
            self.width_spin,
            self.height_spin,
            self.refresh_spin,
            self.fullscreen_box,
            self.borderless_box,
            self.extra_args_edit,
        ]:
            widget.setEnabled(active)

    def set_fields_enabled(self, enabled: bool) -> None:
        self._fields_enabled = enabled
        self._apply_field_state()

    def set_settings(self, settings: GamescopeSettings) -> None:
        self._syncing = True
        if self.enabled_box is not None:
            self.enabled_box.setChecked(settings.enabled)
        self.width_spin.setValue(settings.width)
        self.height_spin.setValue(settings.height)
        self.refresh_spin.setValue(settings.refresh_rate)
        self.fullscreen_box.setChecked(settings.fullscreen)
        self.borderless_box.setChecked(settings.borderless)
        self.extra_args_edit.setText(settings.extra_args)
        self._syncing = False
        self._apply_field_state()

    def current_settings(self, force_enabled: bool | None = None) -> GamescopeSettings:
        if force_enabled is None:
            enabled = self.enabled_box.isChecked() if self.enabled_box is not None else False
        else:
            enabled = force_enabled
        return GamescopeSettings(
            enabled=enabled,
            width=self.width_spin.value(),
            height=self.height_spin.value(),
            refresh_rate=self.refresh_spin.value(),
            fullscreen=self.fullscreen_box.isChecked(),
            borderless=self.borderless_box.isChecked(),
            extra_args=self.extra_args_edit.text().strip(),
        )


class ReleaseRow(QFrame):
    def __init__(self, release: ProtonRelease, installed: bool, action_callback, parent=None):
        super().__init__(parent)
        self.setObjectName("ReleaseCard")
        add_shadow(self, blur=12, alpha=12)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(10)

        text_layout = QVBoxLayout()
        text_layout.setSpacing(2)

        top_row = QHBoxLayout()
        top_row.setSpacing(8)

        tag_label = QLabel(release.tag)
        tag_label.setObjectName("SectionTitle")
        top_row.addWidget(tag_label, 0, Qt.AlignVCenter)

        date_label = QLabel(release.published.strftime("%Y-%m-%d"))
        date_label.setObjectName("MutedText")
        top_row.addWidget(date_label, 0, Qt.AlignVCenter)
        top_row.addStretch()
        text_layout.addLayout(top_row)

        name_label = QLabel(release.name)
        name_label.setObjectName("MutedText")
        name_label.setWordWrap(True)
        text_layout.addWidget(name_label)

        layout.addLayout(text_layout, 1)

        state_chip = _make_chip("Installed" if installed else "Available", accent=installed)
        state_chip.setMinimumWidth(88)
        state_chip.setAlignment(Qt.AlignCenter)
        layout.addWidget(state_chip, 0, Qt.AlignVCenter)

        self.action_button = QPushButton("Remove" if installed else "Install")
        _apply_variant(self.action_button, "danger" if installed else "secondary")
        self.action_button.setMinimumWidth(86)
        self.action_button.setFixedHeight(30)
        self.action_button.clicked.connect(lambda: action_callback(release.tag, installed))
        layout.addWidget(self.action_button, 0, Qt.AlignVCenter)


class ProtonHubDialog(QDialog):
    def __init__(self, proton_manager: ProtonManager, logger: LogManager, parent=None):
        super().__init__(parent)
        self.pm = proton_manager
        self.logger = logger
        self.releases: list[ProtonRelease] = []
        self.installed: set[str] = set()
        self._pending_refresh = 0

        self.setWindowTitle("Proton Manager")
        self.resize(760, 540)

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        title_row = QHBoxLayout()
        title_row.setSpacing(10)

        title_label = QLabel("Proton Manager")
        title_label.setObjectName("SectionTitle")
        title_row.addWidget(title_label)

        title_row.addStretch()

        self.summary_label = QLabel()
        self.summary_label.setObjectName("MutedText")
        title_row.addWidget(self.summary_label, 0, Qt.AlignRight | Qt.AlignVCenter)
        root.addLayout(title_row)

        controls = QHBoxLayout()
        controls.setSpacing(8)

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Filter versions")
        self.search_edit.textChanged.connect(self.refresh_list)
        controls.addWidget(self.search_edit)

        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.clicked.connect(self.refresh)
        controls.addWidget(self.refresh_button)
        root.addLayout(controls)

        activity_row = QHBoxLayout()
        activity_row.setSpacing(10)

        self.progress_label = QLabel("")
        self.progress_label.setObjectName("MutedText")
        self.progress_label.hide()
        activity_row.addWidget(self.progress_label, 1)

        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setMaximumWidth(220)
        self.progress_bar.hide()
        activity_row.addWidget(self.progress_bar)
        root.addLayout(activity_row)

        self.release_list = QListWidget()
        self.release_list.setObjectName("CompactReleaseList")
        self.release_list.setSpacing(6)
        root.addWidget(self.release_list, 1)

        close_row = QHBoxLayout()
        close_row.addStretch()
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.accept)
        close_row.addWidget(close_button)
        root.addLayout(close_row)

        self.pm.remoteReady.connect(self.on_remote_ready)
        self.pm.installedReady.connect(self.on_installed_ready)
        self.pm.downloadProgress.connect(self.on_download_progress)
        self.pm.installProgress.connect(self.on_install_progress)
        self.pm.downloadFinished.connect(self.on_download_finished)
        self.pm.uninstallFinished.connect(self.on_uninstall_finished)

        self.refresh()

    def refresh(self) -> None:
        self._pending_refresh = 2
        self._set_activity("Loading available Proton versions", busy=True)
        self.pm.query_remote()
        self.pm.query_installed()

    def on_remote_ready(self, releases: list[ProtonRelease]) -> None:
        self.releases = releases
        self.refresh_list()
        self._complete_refresh_step()

    def on_installed_ready(self, tags: list[str]) -> None:
        self.installed = set(tags)
        self.refresh_list()
        self._complete_refresh_step()

    def _set_activity(self, message: str = "", busy: bool = False, progress: int | None = None) -> None:
        self.progress_label.setText(message)
        self.progress_label.setVisible(bool(message))
        if not busy and progress is None:
            self.progress_bar.hide()
            return
        self.progress_bar.show()
        if progress is None:
            self.progress_bar.setRange(0, 0)
            return
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(progress)

    def _complete_refresh_step(self) -> None:
        if self._pending_refresh <= 0:
            return
        self._pending_refresh -= 1
        if self._pending_refresh == 0:
            self._set_activity()

    def refresh_list(self) -> None:
        self.release_list.clear()
        query = self.search_edit.text().strip().lower()
        visible = 0

        for release in self.releases:
            haystack = f"{release.tag} {release.name}".lower()
            if query and query not in haystack:
                continue

            item = QListWidgetItem()
            row = ReleaseRow(release, release.tag in self.installed, self.on_action_requested)
            item.setSizeHint(row.sizeHint())
            self.release_list.addItem(item)
            self.release_list.setItemWidget(item, row)
            visible += 1

        if visible == 0:
            self.release_list.addItem("No Proton versions match this filter.")

        proton_dir = pathlib.Path(self.pm.proton_dir)
        location = proton_dir.name or str(proton_dir)
        self.summary_label.setText(f"{len(self.installed)} installed | {len(self.releases)} available | {location}")
        self.summary_label.setToolTip(str(proton_dir))

    def on_action_requested(self, tag: str, installed: bool) -> None:
        if installed:
            self._set_activity(f"Removing {tag}", busy=True)
            self.pm.uninstall(tag)
            return

        self._set_activity(f"Installing {tag}", progress=0)
        self.pm.install(tag)

    def on_download_progress(self, tag: str, done: int, total: int) -> None:
        if total > 0:
            self._set_activity(f"Downloading {tag}", progress=int((done / total) * 100))
            return
        self._set_activity(f"Downloading {tag}", busy=True)

    def on_install_progress(self, tag: str, status_message: str) -> None:
        self._set_activity(f"{tag}: {status_message}", busy=True)

    def on_download_finished(self, tag: str, success: bool, message: str) -> None:
        self._set_activity()
        self.pm.query_installed()
        if success:
            QMessageBox.information(self, "Proton Installed", f"{tag} is ready.")
        else:
            QMessageBox.critical(self, "Installation Failed", f"{tag}\n\n{message}")

    def on_uninstall_finished(self, tag: str, success: bool, message: str) -> None:
        self._set_activity()
        self.pm.query_installed()
        if success:
            QMessageBox.information(self, "Proton Removed", f"{tag} was removed.")
        else:
            QMessageBox.critical(self, "Removal Failed", f"{tag}\n\n{message}")


class AppsDialog(QDialog):
    def __init__(self, prefix: str, scanner: ProgramScanner, cached_apps: list[str], launch_callback, parent=None):
        super().__init__(parent)
        self.prefix = prefix
        self.scanner = scanner
        self.launch_callback = launch_callback
        self.selected_app: str | None = None
        self.all_apps = list(cached_apps)

        self.setWindowTitle("Installed Applications")
        self.resize(700, 520)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        title_label = QLabel(pathlib.Path(prefix).name or prefix)
        title_label.setObjectName("SectionTitle")
        root.addWidget(title_label)

        filters = QHBoxLayout()
        filters.setSpacing(10)

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search apps")
        self.search_edit.textChanged.connect(self.filter_apps)
        filters.addWidget(self.search_edit, 1)

        self.hide_system = QCheckBox("Hide system files")
        self.hide_system.setChecked(True)
        self.hide_system.stateChanged.connect(self.filter_apps)
        filters.addWidget(self.hide_system)

        self.refresh_button = QPushButton("Rescan")
        self.refresh_button.clicked.connect(lambda: self.start_scan(force=True))
        filters.addWidget(self.refresh_button)

        root.addLayout(filters)

        self.count_label = QLabel()
        self.count_label.setObjectName("MutedText")
        root.addWidget(self.count_label)

        self.app_list = QListWidget()
        self.app_list.currentItemChanged.connect(self.update_selection)
        self.app_list.itemDoubleClicked.connect(lambda _: self.launch_selected())
        root.addWidget(self.app_list, 1)

        self.path_label = QLabel("No application selected")
        self.path_label.setObjectName("MutedText")
        self.path_label.setWordWrap(True)
        root.addWidget(self.path_label)

        button_row = QHBoxLayout()
        button_row.setSpacing(10)

        self.favorite_button = QPushButton("Add to Favorites")
        _apply_variant(self.favorite_button, "primary")
        self.favorite_button.clicked.connect(self.accept_selected)
        button_row.addWidget(self.favorite_button)

        self.launch_button = QPushButton("Launch Now")
        _apply_variant(self.launch_button, "secondary")
        self.launch_button.clicked.connect(self.launch_selected)
        button_row.addWidget(self.launch_button)

        close_button = QPushButton("Close")
        close_button.clicked.connect(self.reject)
        button_row.addWidget(close_button)
        root.addLayout(button_row)

        self.scanner.scanned.connect(self.on_scanned)
        self.update_selection()

        if self.all_apps:
            self.filter_apps()
        else:
            self.start_scan(force=False)

    def start_scan(self, force: bool) -> None:
        self.count_label.setText("Scanning prefix...")
        self.app_list.clear()
        self.app_list.addItem("Scanning installed applications...")
        self.scanner.scan(self.prefix, force=force)

    def on_scanned(self, prefix: str, apps: list[str]) -> None:
        if prefix != self.prefix:
            return
        self.all_apps = apps
        self.filter_apps()

    def filter_apps(self) -> None:
        self.app_list.clear()
        query = self.search_edit.text().strip().lower()
        hide_system = self.hide_system.isChecked()
        visible = 0

        for app_path in self.all_apps:
            lower = app_path.lower()
            if hide_system and is_system_executable(lower, app_path):
                continue
            if query and query not in lower:
                continue

            visible += 1
            name = pathlib.Path(app_path).name
            item = QListWidgetItem(f"{name}\n{app_path}")
            item.setData(Qt.UserRole, app_path)
            item.setToolTip(app_path)
            self.app_list.addItem(item)

        if visible == 0:
            self.app_list.addItem("No applications match this filter.")

        self.count_label.setText(f"{visible} applications visible | {len(self.all_apps)} cached total")
        if visible > 0:
            self.app_list.setCurrentRow(0)
        else:
            self.update_selection()

    def current_path(self) -> str | None:
        item = self.app_list.currentItem()
        if not item:
            return None
        return item.data(Qt.UserRole)

    def update_selection(self, *_args) -> None:
        current = self.current_path()
        has_selection = bool(current)
        self.favorite_button.setEnabled(has_selection)
        self.launch_button.setEnabled(has_selection)
        self.path_label.setText(current or "No application selected")

    def accept_selected(self) -> None:
        current = self.current_path()
        if not current:
            return
        self.selected_app = current
        self.accept()

    def launch_selected(self) -> None:
        current = self.current_path()
        if not current:
            return
        if self.launch_callback(current):
            self.accept()


class AddAppDialog(QDialog):
    def __init__(self, prefixes: list[str], selected_prefix: str | None, parent=None):
        super().__init__(parent)
        self.prefixes = list(prefixes)

        self.setWindowTitle("Add App to Prefix")
        self.resize(660, 240)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(14)

        header = SectionCard(
            "Add App to Prefix",
            "Link a local Windows executable to a prefix so it appears in the library immediately.",
        )
        root.addWidget(header)

        prefix_row = QHBoxLayout()
        prefix_row.setSpacing(10)
        prefix_label = QLabel("Prefix")
        prefix_row.addWidget(prefix_label)

        self.prefix_combo = QComboBox()
        for prefix in self.prefixes:
            self.prefix_combo.addItem(pathlib.Path(prefix).name or prefix, prefix)
        if selected_prefix is not None:
            index = self.prefix_combo.findData(selected_prefix)
            self.prefix_combo.setCurrentIndex(index if index >= 0 else 0)
        prefix_row.addWidget(self.prefix_combo, 1)
        header.body.addLayout(prefix_row)

        executable_row = QHBoxLayout()
        executable_row.setSpacing(10)

        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText("Choose a Windows executable")
        self.path_edit.textChanged.connect(self.refresh_state)
        executable_row.addWidget(self.path_edit, 1)

        self.browse_button = QPushButton("Browse")
        self.browse_button.clicked.connect(self.browse_executable)
        executable_row.addWidget(self.browse_button)
        header.body.addLayout(executable_row)

        self.preview_label = QLabel("No executable selected")
        self.preview_label.setObjectName("MutedText")
        self.preview_label.setWordWrap(True)
        header.body.addWidget(self.preview_label)

        actions = QHBoxLayout()
        actions.addStretch()

        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(self.reject)
        actions.addWidget(cancel_button)

        self.add_button = QPushButton("Add App")
        _apply_variant(self.add_button, "primary")
        self.add_button.clicked.connect(self.accept_selection)
        actions.addWidget(self.add_button)
        root.addLayout(actions)

        if self.prefix_combo.count() == 0:
            self.prefix_combo.setEnabled(False)
            self.path_edit.setEnabled(False)
            self.browse_button.setEnabled(False)
            self.add_button.setEnabled(False)
            self.preview_label.setText("No prefixes available")
        else:
            self.refresh_state()

    def selected_prefix(self) -> str | None:
        return self.prefix_combo.currentData()

    def selected_path(self) -> str:
        return self.path_edit.text().strip()

    def browse_executable(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Choose App Executable",
            str(pathlib.Path.home()),
            "Windows Executables (*.exe);;All Files (*)",
        )
        if path:
            self.path_edit.setText(path)

    def refresh_state(self) -> None:
        exe_path = self.selected_path()
        if exe_path:
            self.preview_label.setText(f"{normalize_app_name(exe_path)}\n{exe_path}")
        else:
            self.preview_label.setText("No executable selected")
        self.add_button.setEnabled(bool(self.selected_prefix() and exe_path))

    def accept_selection(self) -> None:
        prefix = self.selected_prefix()
        exe_path = self.selected_path()
        if not prefix:
            QMessageBox.warning(self, "Incomplete", "Please choose a prefix.")
            return
        if not exe_path:
            QMessageBox.warning(self, "Incomplete", "Please choose an executable.")
            return
        if not pathlib.Path(exe_path).is_file():
            QMessageBox.warning(self, "Executable Missing", "The selected executable does not exist.")
            return
        self.accept()


class LaunchExeDialog(QDialog):
    def __init__(
        self,
        prefixes: list[str],
        installed_tags: list[str],
        config: ConfigStore,
        selected_prefix: str | None,
        parent=None,
    ):
        super().__init__(parent)
        self.prefixes = list(prefixes)
        self.config = config

        self.setWindowTitle("Launch .exe")
        self.resize(760, 560)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(14)

        launch_card = SectionCard(
            "Launch .exe",
            "Run a Windows executable once with explicit runtime and display options.",
        )
        root.addWidget(launch_card)

        prefix_row = QHBoxLayout()
        prefix_row.setSpacing(10)
        prefix_row.addWidget(QLabel("Prefix"))

        self.prefix_combo = QComboBox()
        for prefix in self.prefixes:
            self.prefix_combo.addItem(pathlib.Path(prefix).name or prefix, prefix)
        if selected_prefix is not None:
            index = self.prefix_combo.findData(selected_prefix)
            self.prefix_combo.setCurrentIndex(index if index >= 0 else 0)
        self.prefix_combo.currentIndexChanged.connect(self.on_gamescope_mode_changed)
        prefix_row.addWidget(self.prefix_combo, 1)
        launch_card.body.addLayout(prefix_row)

        executable_row = QHBoxLayout()
        executable_row.setSpacing(10)

        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText("Choose a Windows executable")
        self.path_edit.textChanged.connect(self.refresh_preview)
        executable_row.addWidget(self.path_edit, 1)

        self.browse_button = QPushButton("Browse")
        self.browse_button.clicked.connect(self.browse_executable)
        executable_row.addWidget(self.browse_button)
        launch_card.body.addLayout(executable_row)

        self.arguments_edit = QLineEdit()
        self.arguments_edit.setPlaceholderText("Optional executable arguments, e.g. -windowed -lang en")
        self.arguments_edit.textChanged.connect(self.refresh_preview)
        launch_card.body.addWidget(self.arguments_edit)

        runtime_row = QHBoxLayout()
        runtime_row.setSpacing(10)
        runtime_row.addWidget(QLabel("Runtime"))

        self.runtime_combo = QComboBox()
        self.runtime_combo.addItem("Use prefix/default runtime", "__inherit__")
        self.runtime_combo.addItem("System Wine", "")
        for tag in installed_tags:
            self.runtime_combo.addItem(f"Proton {tag}", tag)
        self.runtime_combo.currentIndexChanged.connect(self.refresh_preview)
        runtime_row.addWidget(self.runtime_combo, 1)
        launch_card.body.addLayout(runtime_row)

        self.add_to_library_box = QCheckBox("Add to library after launch")
        launch_card.body.addWidget(self.add_to_library_box)

        self.preview_label = QLabel("No executable selected")
        self.preview_label.setObjectName("MutedText")
        self.preview_label.setWordWrap(True)
        launch_card.body.addWidget(self.preview_label)

        gamescope_card = SectionCard(
            "Gamescope",
            "Keep inherited defaults, disable gamescope for this launch, or use custom launch settings.",
        )
        root.addWidget(gamescope_card)

        gamescope_mode_row = QHBoxLayout()
        gamescope_mode_row.setSpacing(10)
        gamescope_mode_row.addWidget(QLabel("Mode"))

        self.gamescope_mode_combo = QComboBox()
        self.gamescope_mode_combo.addItem("Use prefix/default gamescope", "__inherit__")
        self.gamescope_mode_combo.addItem("Disable gamescope", "__disabled__")
        self.gamescope_mode_combo.addItem("Enable custom gamescope", "__enabled__")
        self.gamescope_mode_combo.currentIndexChanged.connect(self.on_gamescope_mode_changed)
        gamescope_mode_row.addWidget(self.gamescope_mode_combo, 1)
        gamescope_card.body.addLayout(gamescope_mode_row)

        self.gamescope_editor = GamescopeEditor(
            show_toggle=False,
            description="0 keeps gamescope defaults. Extra args are appended before Wine or Proton.",
            parent=self,
        )
        self.gamescope_editor.set_settings(self.config.default_gamescope())
        self.gamescope_editor.set_fields_enabled(False)
        gamescope_card.body.addWidget(self.gamescope_editor)

        actions = QHBoxLayout()
        actions.addStretch()

        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(self.reject)
        actions.addWidget(cancel_button)

        self.launch_button = QPushButton("Launch")
        _apply_variant(self.launch_button, "primary")
        self.launch_button.clicked.connect(self.accept_selection)
        actions.addWidget(self.launch_button)
        root.addLayout(actions)

        if self.prefix_combo.count() == 0:
            self.prefix_combo.setEnabled(False)
            self.path_edit.setEnabled(False)
            self.browse_button.setEnabled(False)
            self.runtime_combo.setEnabled(False)
            self.gamescope_mode_combo.setEnabled(False)
            self.gamescope_editor.set_fields_enabled(False)
            self.add_to_library_box.setEnabled(False)
            self.launch_button.setEnabled(False)
            self.preview_label.setText("No prefixes available")
        else:
            self.refresh_preview()

    def selected_prefix(self) -> str | None:
        return self.prefix_combo.currentData()

    def selected_path(self) -> str:
        return self.path_edit.text().strip()

    def selected_runtime(self) -> str:
        value = self.runtime_combo.currentData()
        if value == "__inherit__":
            prefix = self.selected_prefix()
            if not prefix:
                return ""
            override = self.config.runtime_override(prefix)
            return self.config.default_runtime if override is None else override
        return value or ""

    def runtime_override_value(self) -> str | None:
        value = self.runtime_combo.currentData()
        if value == "__inherit__":
            return None
        return value or ""

    def selected_gamescope(self) -> GamescopeSettings | None:
        value = self.gamescope_mode_combo.currentData()
        if value == "__inherit__":
            return None
        return self.gamescope_editor.current_settings(force_enabled=value == "__enabled__")

    def selected_arguments(self) -> list[str]:
        raw_args = self.arguments_edit.text().strip()
        if not raw_args:
            return []
        try:
            return shlex.split(raw_args)
        except ValueError as error:
            raise RuntimeError(f"Invalid executable arguments: {error}") from error

    def should_add_to_library(self) -> bool:
        return self.add_to_library_box.isChecked()

    def browse_executable(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Choose Executable",
            str(pathlib.Path.home()),
            "Windows Executables (*.exe);;All Files (*)",
        )
        if path:
            self.path_edit.setText(path)

    def on_gamescope_mode_changed(self) -> None:
        value = self.gamescope_mode_combo.currentData()
        if value == "__inherit__":
            prefix = self.selected_prefix()
            settings = self.config.effective_gamescope(prefix) if prefix else self.config.default_gamescope()
            self.gamescope_editor.set_settings(settings)
            self.gamescope_editor.set_fields_enabled(False)
        else:
            self.gamescope_editor.set_fields_enabled(value == "__enabled__")
        self.refresh_preview()

    def refresh_preview(self) -> None:
        exe_path = self.selected_path()
        prefix = self.selected_prefix()
        self.launch_button.setEnabled(bool(prefix and exe_path))
        if not exe_path:
            self.preview_label.setText("No executable selected")
            return

        runtime_value = self.runtime_combo.currentData()
        if runtime_value == "__inherit__":
            runtime_text = "Inherited runtime"
        elif runtime_value:
            runtime_text = f"Proton {runtime_value}"
        else:
            runtime_text = "System Wine"

        gamescope_value = self.gamescope_mode_combo.currentData()
        if gamescope_value == "__inherit__":
            gamescope_text = "Inherited gamescope"
        elif gamescope_value == "__enabled__":
            gamescope_text = "Custom gamescope enabled"
        else:
            gamescope_text = "Gamescope disabled"

        args_text = "Arguments set" if self.arguments_edit.text().strip() else "No arguments"
        self.preview_label.setText(
            f"{normalize_app_name(exe_path)}\n{exe_path}\n{runtime_text} | {gamescope_text} | {args_text}"
        )

    def accept_selection(self) -> None:
        prefix = self.selected_prefix()
        exe_path = self.selected_path()
        if not prefix:
            QMessageBox.warning(self, "Incomplete", "Please choose a prefix.")
            return
        if not exe_path:
            QMessageBox.warning(self, "Incomplete", "Please choose an executable.")
            return
        if not pathlib.Path(exe_path).is_file():
            QMessageBox.warning(self, "Executable Missing", "The selected executable does not exist.")
            return
        try:
            self.selected_arguments()
        except RuntimeError as error:
            QMessageBox.warning(self, "Invalid Arguments", str(error))
            return
        self.accept()


class AppArtworkDialog(QDialog):
    searchFinished = Signal(int, object, str)

    def __init__(self, config: ConfigStore, logger: LogManager, app_name: str, prefix: str, exe_path: str, parent=None):
        super().__init__(parent)
        self.config = config
        self.logger = logger
        self.app_name = app_name
        self.prefix = prefix
        self.exe_path = exe_path
        self.remote_suggestions = []
        self._browsed_art_path = ""
        self._search_generation = 0
        self._current_art_path = self.current_override_path()
        self._saved_zoom = self.config.app_art_zoom(self.prefix, self.exe_path)

        self.setWindowTitle(f"Artwork | {app_name}")
        self.resize(860, 560)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        header = QHBoxLayout()
        header.setSpacing(10)

        title_label = QLabel(app_name)
        title_label.setObjectName("SectionTitle")
        header.addWidget(title_label, 1)

        prefix_chip = _make_chip(pathlib.Path(prefix).name or prefix)
        header.addWidget(prefix_chip)
        root.addLayout(header)

        search_row = QHBoxLayout()
        search_row.setSpacing(8)

        self.search_edit = QLineEdit(normalize_app_name(app_name))
        self.search_edit.setPlaceholderText("Search artwork")
        self.search_edit.returnPressed.connect(self.start_search)
        search_row.addWidget(self.search_edit, 1)

        self.search_button = QPushButton("Search")
        self.search_button.clicked.connect(self.start_search)
        search_row.addWidget(self.search_button)
        root.addLayout(search_row)

        self.status_label = QLabel("Search the app name to find icon and image suggestions.")
        self.status_label.setObjectName("MutedText")
        self.status_label.setWordWrap(True)
        root.addWidget(self.status_label)

        content = QHBoxLayout()
        content.setSpacing(12)

        preview_card = SectionCard("Preview")
        self.preview_label = QLabel()
        self.preview_label.setObjectName("ArtworkPreview")
        self.preview_label.setFixedSize(220, 220)
        self.preview_label.setAlignment(Qt.AlignCenter)
        preview_card.body.addWidget(self.preview_label, 0, Qt.AlignCenter)

        self.preview_title = QLabel("Executable icon")
        self.preview_title.setObjectName("SectionTitle")
        self.preview_title.setWordWrap(True)
        preview_card.body.addWidget(self.preview_title)

        self.preview_meta = QLabel()
        self.preview_meta.setObjectName("MutedText")
        self.preview_meta.setWordWrap(True)
        self.preview_meta.setOpenExternalLinks(True)
        preview_card.body.addWidget(self.preview_meta)

        zoom_row = QHBoxLayout()
        zoom_row.setSpacing(8)
        zoom_label = QLabel("Zoom")
        zoom_row.addWidget(zoom_label)

        self.zoom_spin = QSpinBox()
        self.zoom_spin.setRange(-75, 250)
        self.zoom_spin.setSingleStep(5)
        self.zoom_spin.setSuffix(" %")
        self.zoom_spin.setValue(self._saved_zoom)
        self.zoom_spin.valueChanged.connect(self.on_zoom_changed)
        zoom_row.addWidget(self.zoom_spin)
        preview_card.body.addLayout(zoom_row)

        self.zoom_hint = QLabel("Negative zoom shows more of the image.")
        self.zoom_hint.setObjectName("MutedText")
        preview_card.body.addWidget(self.zoom_hint)
        preview_card.body.addStretch()
        content.addWidget(preview_card, 0)

        suggestion_card = SectionCard(
            "Suggestions",
            "Executable icon, current custom artwork and online search results are listed here.",
        )
        self.suggestion_list = QListWidget()
        self.suggestion_list.setObjectName("ArtworkSuggestionList")
        self.suggestion_list.setIconSize(QSize(92, 92))
        self.suggestion_list.currentItemChanged.connect(self.on_selection_changed)
        self.suggestion_list.itemDoubleClicked.connect(lambda *_: self.apply_selection())
        suggestion_card.body.addWidget(self.suggestion_list, 1)
        content.addWidget(suggestion_card, 1)

        root.addLayout(content, 1)

        actions = QHBoxLayout()
        actions.setSpacing(8)

        browse_button = QPushButton("Choose File")
        browse_button.clicked.connect(self.browse_file)
        actions.addWidget(browse_button)

        actions.addStretch()

        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(self.reject)
        actions.addWidget(cancel_button)

        self.apply_button = QPushButton("Use Artwork")
        _apply_variant(self.apply_button, "primary")
        self.apply_button.clicked.connect(self.apply_selection)
        actions.addWidget(self.apply_button)
        root.addLayout(actions)

        self.searchFinished.connect(self.on_search_finished)
        self.populate_suggestions()
        self.start_search()

    def current_override_path(self) -> str:
        return self.config.app_art_override(self.prefix, self.exe_path) or ""

    def current_override_zoom(self) -> int:
        return self.config.app_art_zoom(self.prefix, self.exe_path)

    def populate_suggestions(self, selected_path: str = "") -> None:
        current_override = self.current_override_path()
        current_override_zoom = self.current_override_zoom()
        self.suggestion_list.clear()

        custom_paths: list[tuple[str, str, str]] = []
        if current_override:
            custom_paths.append(("Current artwork", pathlib.Path(current_override).name, current_override))
        if self._browsed_art_path and self._browsed_art_path != current_override:
            custom_paths.append(("Chosen file", pathlib.Path(self._browsed_art_path).name, self._browsed_art_path))

        for title, subtitle, art_path in custom_paths:
            default_zoom = current_override_zoom if art_path == current_override else 0
            self._add_suggestion_item(title, subtitle, art_path, art_path, default_zoom=default_zoom)

        self._add_suggestion_item("Executable icon", "Use the executable or theme icon", "", "", supports_zoom=False)

        seen_paths = {path for _, _, path in custom_paths if path}
        for suggestion in self.remote_suggestions:
            if suggestion.image_path in seen_paths:
                continue
            self._add_suggestion_item(suggestion.title, suggestion.source, suggestion.image_path, suggestion.attribution)

        target_path = selected_path or self._browsed_art_path or current_override
        if not self._select_matching_item(target_path):
            self.suggestion_list.setCurrentRow(0)

    def _add_suggestion_item(
        self,
        title: str,
        subtitle: str,
        art_path: str,
        attribution: str,
        default_zoom: int = 0,
        supports_zoom: bool = True,
    ) -> None:
        pixmap = build_app_artwork_pixmap(self.app_name, self.exe_path, art_path, 96, default_zoom)
        item = QListWidgetItem(title)
        item.setIcon(QIcon(pixmap))
        item.setToolTip(subtitle if not attribution else f"{subtitle}\n{attribution}")
        item.setData(
            Qt.UserRole,
            {
                "title": title,
                "subtitle": subtitle,
                "art_path": art_path,
                "attribution": attribution,
                "default_zoom": default_zoom,
                "supports_zoom": supports_zoom and bool(art_path),
            },
        )
        self.suggestion_list.addItem(item)

    def _select_matching_item(self, art_path: str) -> bool:
        for index in range(self.suggestion_list.count()):
            item = self.suggestion_list.item(index)
            data = item.data(Qt.UserRole) or {}
            if (data.get("art_path") or "") == art_path:
                self.suggestion_list.setCurrentRow(index)
                return True
        return False

    def start_search(self) -> None:
        query = normalize_app_name(self.search_edit.text().strip())
        if not query:
            self.remote_suggestions = []
            self.populate_suggestions()
            self.status_label.setText("Enter an app name to search for suggestions.")
            self.search_button.setEnabled(True)
            return

        self._search_generation += 1
        generation = self._search_generation
        self.search_button.setEnabled(False)
        self.status_label.setText(f"Searching artwork for {query}...")
        threading.Thread(target=self._search_worker, args=(generation, query), daemon=True).start()

    def _search_worker(self, generation: int, query: str) -> None:
        try:
            results = search_artwork_suggestions(query)
            self.searchFinished.emit(generation, results, "")
        except Exception as error:
            self.searchFinished.emit(generation, [], str(error))

    def on_search_finished(self, generation: int, results: object, error: str) -> None:
        if generation != self._search_generation:
            return
        self.search_button.setEnabled(True)

        if error:
            self.remote_suggestions = []
            self.populate_suggestions()
            self.status_label.setText("Artwork search failed. You can still use the executable icon or choose a local file.")
            self.logger.add("WARNING", f"Artwork search failed for {self.app_name}: {error}", "ArtworkSearch")
            return

        self.remote_suggestions = list(results)
        self.populate_suggestions()
        if self.remote_suggestions:
            self.status_label.setText(f"Found {len(self.remote_suggestions)} online suggestions.")
        else:
            self.status_label.setText("No online suggestions found. You can still use the executable icon or choose a local file.")

    def on_selection_changed(self, current: QListWidgetItem | None, _previous: QListWidgetItem | None = None) -> None:
        if current is None:
            self.apply_button.setEnabled(False)
            self.zoom_spin.setEnabled(False)
            return

        self.apply_button.setEnabled(True)
        data = current.data(Qt.UserRole) or {}
        self._current_art_path = data.get("art_path") or ""
        default_zoom = int(data.get("default_zoom") or 0)
        supports_zoom = bool(data.get("supports_zoom"))

        self.zoom_spin.blockSignals(True)
        self.zoom_spin.setValue(default_zoom if supports_zoom else 0)
        self.zoom_spin.setEnabled(supports_zoom)
        self.zoom_spin.blockSignals(False)
        self.zoom_hint.setVisible(supports_zoom)
        self.refresh_preview()

    def on_zoom_changed(self) -> None:
        self.refresh_preview()

    def refresh_preview(self) -> None:
        item = self.suggestion_list.currentItem()
        if item is None:
            return

        data = item.data(Qt.UserRole) or {}
        art_path = data.get("art_path") or ""
        zoom_value = self.zoom_spin.value() if self.zoom_spin.isEnabled() else 0
        pixmap = build_app_artwork_pixmap(self.app_name, self.exe_path, art_path, 220, zoom_value)
        self.preview_label.setPixmap(pixmap)
        self.preview_title.setText(data.get("title") or self.app_name)

        subtitle = data.get("subtitle") or ""
        attribution = data.get("attribution") or ""
        if self.zoom_spin.isEnabled():
            subtitle = f"{subtitle}<br>Zoom: {zoom_value:+d}%" if subtitle else f"Zoom: {zoom_value:+d}%"
        if attribution.startswith("http"):
            subtitle = f'{subtitle}<br><a href="{attribution}">Open source page</a>' if subtitle else f'<a href="{attribution}">Open source page</a>'
        self.preview_meta.setText(subtitle or "Use the executable or theme icon.")

    def browse_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Choose Artwork",
            str(pathlib.Path.home()),
            "Images (*.png *.jpg *.jpeg *.webp *.bmp);;All Files (*)",
        )
        if not path:
            return
        if not pathlib.Path(path).is_file():
            QMessageBox.warning(self, "Artwork Missing", "The selected image does not exist.")
            return
        self._browsed_art_path = path
        self.populate_suggestions(selected_path=path)
        self.status_label.setText("Local artwork added to the suggestions.")

    def apply_selection(self) -> None:
        item = self.suggestion_list.currentItem()
        if item is None:
            return
        data = item.data(Qt.UserRole) or {}
        art_path = data.get("art_path") or ""
        if art_path and not pathlib.Path(art_path).is_file():
            QMessageBox.warning(self, "Artwork Missing", "The selected image is no longer available.")
            return
        self.config.set_app_art_override(self.prefix, self.exe_path, art_path or None)
        self.config.set_app_art_zoom(self.prefix, self.exe_path, self.zoom_spin.value() if art_path else None)
        self.accept()


class AppPosterSettingsDialog(QDialog):
    def __init__(
        self,
        config: ConfigStore,
        installed_tags: list[str],
        app_name: str,
        prefix: str,
        exe_path: str,
        open_prefix_settings,
        parent=None,
    ):
        super().__init__(parent)
        self.config = config
        self.installed_tags = list(installed_tags)
        self.app_name = app_name
        self.prefix = prefix
        self.exe_path = exe_path
        self.open_prefix_settings = open_prefix_settings
        self._syncing_gamescope = False

        self.setWindowTitle(app_name)
        self.resize(460, 340)
        self.setToolTip(exe_path)

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(8)

        header = QHBoxLayout()
        header.setSpacing(8)

        title_label = QLabel(app_name)
        title_label.setObjectName("SectionTitle")
        header.addWidget(title_label, 1)

        self.prefix_chip = _make_chip(pathlib.Path(prefix).name or prefix)
        header.addWidget(self.prefix_chip)
        root.addLayout(header)

        self.meta_label = QLabel()
        self.meta_label.setObjectName("MutedText")
        root.addWidget(self.meta_label)

        runtime_row = QHBoxLayout()
        runtime_row.setSpacing(8)

        runtime_label = QLabel("Runtime")
        runtime_row.addWidget(runtime_label)

        self.runtime_combo = QComboBox()
        self.runtime_combo.addItem("Inherit from prefix", "__inherit__")
        self.runtime_combo.addItem("System Wine", "")
        for tag in self.installed_tags:
            self.runtime_combo.addItem(f"Proton {tag}", tag)
        self.runtime_combo.currentIndexChanged.connect(self.on_runtime_changed)
        runtime_row.addWidget(self.runtime_combo, 1)
        root.addLayout(runtime_row)

        gamescope_row = QHBoxLayout()
        gamescope_row.setSpacing(8)

        gamescope_label = QLabel("Gamescope")
        gamescope_row.addWidget(gamescope_label)

        self.gamescope_mode_combo = QComboBox()
        self.gamescope_mode_combo.addItem("Inherit from prefix", "__inherit__")
        self.gamescope_mode_combo.addItem("Disable gamescope", "__disabled__")
        self.gamescope_mode_combo.addItem("Enable custom gamescope", "__enabled__")
        self.gamescope_mode_combo.currentIndexChanged.connect(self.on_gamescope_mode_changed)
        gamescope_row.addWidget(self.gamescope_mode_combo, 1)
        root.addLayout(gamescope_row)

        self.gamescope_editor = GamescopeEditor(
            show_toggle=False,
            description="0 keeps gamescope defaults. Extra args are appended before Wine or Proton.",
            parent=self,
        )
        self.gamescope_editor.settingsChanged.connect(self.on_gamescope_settings_changed)
        root.addWidget(self.gamescope_editor)

        button_row = QHBoxLayout()
        button_row.setSpacing(8)

        self.favorite_button = QPushButton()
        _apply_variant(self.favorite_button, "primary")
        self.favorite_button.clicked.connect(self.toggle_favorite)
        button_row.addWidget(self.favorite_button)

        prefix_button = QPushButton("Prefix...")
        prefix_button.clicked.connect(self.open_prefix_settings_clicked)
        button_row.addWidget(prefix_button)

        close_button = QPushButton("Done")
        close_button.clicked.connect(self.accept)
        button_row.addWidget(close_button)
        button_row.addStretch()
        root.addLayout(button_row)

        self.refresh_runtime_state()
        self.refresh_gamescope_state()
        self.refresh_favorite_state()

    def refresh_runtime_state(self) -> None:
        current_override = self.config.app_runtime_override(self.prefix, self.exe_path)
        target = "__inherit__" if current_override is None else current_override
        index = self.runtime_combo.findData(target)
        self.runtime_combo.setCurrentIndex(index if index >= 0 else 0)
        self._refresh_meta_label()

    def refresh_gamescope_state(self) -> None:
        current_override = self.config.app_gamescope_override(self.prefix, self.exe_path)
        effective_settings = self.config.effective_gamescope(self.prefix)
        self._syncing_gamescope = True
        if current_override is None:
            target = "__inherit__"
            self.gamescope_editor.set_settings(effective_settings)
            self.gamescope_editor.set_fields_enabled(False)
        else:
            target = "__enabled__" if current_override.enabled else "__disabled__"
            self.gamescope_editor.set_settings(current_override)
            self.gamescope_editor.set_fields_enabled(current_override.enabled)
        index = self.gamescope_mode_combo.findData(target)
        self.gamescope_mode_combo.setCurrentIndex(index if index >= 0 else 0)
        self._syncing_gamescope = False
        self._refresh_meta_label()

    def _refresh_meta_label(self) -> None:
        prefix_name = pathlib.Path(self.prefix).name or self.prefix
        prefix_override = self.config.runtime_override(self.prefix)
        effective_prefix_runtime = self.config.default_runtime if prefix_override is None else prefix_override
        app_override = self.config.app_runtime_override(self.prefix, self.exe_path)
        effective_runtime = effective_prefix_runtime if app_override is None else app_override
        effective_gamescope = self.config.effective_gamescope(self.prefix, self.exe_path)

        if effective_runtime:
            runtime_text = f"Proton {effective_runtime}"
        else:
            runtime_text = "System Wine"

        has_app_override = app_override is not None or self.config.app_gamescope_override(self.prefix, self.exe_path) is not None
        mode_text = "App override" if has_app_override else "Inherited from prefix"
        self.meta_label.setText(f"{runtime_text} | {_gamescope_summary(effective_gamescope)} | {mode_text}")
        self.meta_label.setToolTip(f"{prefix_name}\n{self.exe_path}")

    def refresh_favorite_state(self) -> None:
        is_favorite = self.exe_path in self.config.favorites_for(self.prefix)
        if is_favorite:
            self.favorite_button.setText("Favorited")
        else:
            self.favorite_button.setText("Add Favorite")

    def on_runtime_changed(self) -> None:
        value = self.runtime_combo.currentData()
        if value == "__inherit__":
            self.config.set_app_runtime_override(self.prefix, self.exe_path, None)
        else:
            self.config.set_app_runtime_override(self.prefix, self.exe_path, value or "")
        self._refresh_meta_label()

    def on_gamescope_mode_changed(self) -> None:
        if self._syncing_gamescope:
            return

        value = self.gamescope_mode_combo.currentData()
        if value == "__inherit__":
            self.config.set_app_gamescope_override(self.prefix, self.exe_path, None)
            self.gamescope_editor.set_settings(self.config.effective_gamescope(self.prefix))
            self.gamescope_editor.set_fields_enabled(False)
        else:
            enabled = value == "__enabled__"
            self.gamescope_editor.set_fields_enabled(enabled)
            self.config.set_app_gamescope_override(
                self.prefix,
                self.exe_path,
                self.gamescope_editor.current_settings(force_enabled=enabled),
            )
        self._refresh_meta_label()

    def on_gamescope_settings_changed(self) -> None:
        if self._syncing_gamescope:
            return

        value = self.gamescope_mode_combo.currentData()
        if value == "__inherit__":
            return
        self.config.set_app_gamescope_override(
            self.prefix,
            self.exe_path,
            self.gamescope_editor.current_settings(force_enabled=value == "__enabled__"),
        )
        self._refresh_meta_label()

    def toggle_favorite(self) -> None:
        if self.exe_path in self.config.favorites_for(self.prefix):
            self.config.remove_favorite(self.prefix, self.exe_path)
        else:
            self.config.add_favorite(self.prefix, self.exe_path)
        self.refresh_favorite_state()

    def open_prefix_settings_clicked(self) -> None:
        self.open_prefix_settings(self.prefix)
        self.refresh_runtime_state()
        self.refresh_gamescope_state()
        self.refresh_favorite_state()


class SettingsDialog(QDialog):
    def __init__(
        self,
        config: ConfigStore,
        installed_tags: list[str],
        prefixes: list[str],
        selected_prefix: str | None,
        parent=None,
    ):
        super().__init__(parent)
        self.config = config
        self.installed_tags = installed_tags
        self.prefixes = list(prefixes)
        self._syncing_prefix_override = False
        self._syncing_prefix_gamescope = False
        self.prefix_overrides = dict(self.config.data.get("prefix_proton_map", {}))
        self.prefix_gamescope_overrides = {
            prefix: GamescopeSettings.from_raw(settings)
            for prefix, settings in self.config.data.get("prefix_gamescope_map", {}).items()
        }

        self.setWindowTitle("Settings")
        self.resize(980, 720)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        header = QFrame()
        header.setObjectName("SettingsHeader")
        add_shadow(header, blur=20, alpha=22)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(22, 16, 22, 16)
        header_layout.setSpacing(14)

        title_column = QVBoxLayout()
        title_column.setSpacing(3)
        title = QLabel("Settings")
        title.setObjectName("SettingsTitle")
        title_column.addWidget(title)
        subtitle = QLabel("Defaults first, exceptions only where a prefix needs them.")
        subtitle.setObjectName("MutedText")
        subtitle.setWordWrap(True)
        title_column.addWidget(subtitle)
        header_layout.addLayout(title_column, 1)
        header_layout.addWidget(_make_chip(f"{len(self.prefixes)} Prefixes", accent=True))
        header_layout.addWidget(_make_chip(f"{len(installed_tags)} Runtimes" if installed_tags else "Wine Default"))
        root.addWidget(header)

        content = QHBoxLayout()
        content.setSpacing(14)

        self.settings_nav = QListWidget()
        self.settings_nav.setObjectName("SettingsNav")
        self.settings_nav.setFixedWidth(190)
        self.settings_nav.addItems(["Global Defaults", "Prefix Overrides", "Prefix Sources"])
        content.addWidget(self.settings_nav)

        self.settings_pages = QStackedWidget()
        self.settings_pages.setObjectName("SettingsPages")
        content.addWidget(self.settings_pages, 1)
        root.addLayout(content, 1)

        global_page = QWidget()
        global_page.setObjectName("SettingsPage")
        global_layout = QVBoxLayout(global_page)
        global_layout.setContentsMargins(0, 0, 0, 0)
        global_layout.setSpacing(12)

        global_top = QHBoxLayout()
        global_top.setSpacing(12)

        proton_card = SectionCard("Proton Directory", "Where downloaded Proton builds are stored.")
        proton_row = QHBoxLayout()
        proton_row.setSpacing(10)
        self.proton_dir_edit = QLineEdit(str(self.config.proton_dir))
        proton_row.addWidget(self.proton_dir_edit, 1)
        proton_browse = QPushButton("Choose Folder")
        proton_browse.clicked.connect(self.browse_proton_dir)
        proton_row.addWidget(proton_browse)
        proton_card.body.addLayout(proton_row)
        global_top.addWidget(proton_card, 2)

        runtime_card = SectionCard("Default Runtime", "Used unless a prefix or app overrides it.")
        self.default_runtime_combo = QComboBox()
        self.default_runtime_combo.addItem("System Wine", "")
        for tag in installed_tags:
            self.default_runtime_combo.addItem(f"Proton {tag}", tag)
        current = self.default_runtime_combo.findData(self.config.default_runtime)
        self.default_runtime_combo.setCurrentIndex(current if current >= 0 else 0)
        runtime_card.body.addWidget(self.default_runtime_combo)

        self.proton_backend_combo = QComboBox()
        self.proton_backend_combo.addItem("umu-run (recommended)", "umu")
        self.proton_backend_combo.addItem("Direct Proton (legacy)", "direct")
        backend_index = self.proton_backend_combo.findData(self.config.proton_launch_backend)
        self.proton_backend_combo.setCurrentIndex(backend_index if backend_index >= 0 else 0)
        runtime_card.body.addWidget(QLabel("Proton launch backend"))
        runtime_card.body.addWidget(self.proton_backend_combo)
        global_top.addWidget(runtime_card, 1)
        global_layout.addLayout(global_top)

        gamescope_card = SectionCard(
            "Default Gamescope",
            "Apply to all launches unless a prefix or app overrides it.",
        )
        self.default_gamescope_editor = GamescopeEditor(
            show_toggle=True,
            description="Width, height and refresh rate of 0 keep gamescope defaults. Extra args are appended before Wine or Proton.",
            parent=self,
        )
        self.default_gamescope_editor.set_settings(self.config.default_gamescope())
        self.default_gamescope_editor.settingsChanged.connect(self.refresh_current_prefix_previews)
        gamescope_card.body.addWidget(self.default_gamescope_editor)
        global_layout.addWidget(gamescope_card)
        global_layout.addStretch()
        self.settings_pages.addWidget(global_page)

        prefix_page = QWidget()
        prefix_page.setObjectName("SettingsPage")
        prefix_layout = QVBoxLayout(prefix_page)
        prefix_layout.setContentsMargins(0, 0, 0, 0)
        prefix_layout.setSpacing(12)

        prefix_card = SectionCard(
            "Runtime Override",
            "Choose a prefix, then keep it inherited or pin it to Wine/Proton.",
        )
        prefix_row = QHBoxLayout()
        prefix_row.setSpacing(10)

        self.prefix_selector = QComboBox()
        for prefix in self.prefixes:
            label = pathlib.Path(prefix).name or prefix
            self.prefix_selector.addItem(label, prefix)
        prefix_row.addWidget(self.prefix_selector, 1)

        self.prefix_override_combo = QComboBox()
        self.prefix_override_combo.addItem("Use global default", "__inherit__")
        self.prefix_override_combo.addItem("Always use System Wine", "")
        for tag in installed_tags:
            self.prefix_override_combo.addItem(f"Always use Proton {tag}", tag)
        prefix_row.addWidget(self.prefix_override_combo, 1)
        prefix_card.body.addLayout(prefix_row)

        self.prefix_override_label = QLabel("No prefix selected")
        self.prefix_override_label.setObjectName("MutedText")
        self.prefix_override_label.setWordWrap(True)
        prefix_card.body.addWidget(self.prefix_override_label)
        prefix_layout.addWidget(prefix_card)

        prefix_gamescope_card = SectionCard(
            "Gamescope Override",
            "Leave inherited for normal use; customize only when this prefix needs different display behavior.",
        )

        prefix_gamescope_row = QHBoxLayout()
        prefix_gamescope_row.setSpacing(8)

        prefix_gamescope_label = QLabel("Gamescope")
        prefix_gamescope_row.addWidget(prefix_gamescope_label)

        self.prefix_gamescope_mode_combo = QComboBox()
        self.prefix_gamescope_mode_combo.addItem("Use global default", "__inherit__")
        self.prefix_gamescope_mode_combo.addItem("Disable gamescope", "__disabled__")
        self.prefix_gamescope_mode_combo.addItem("Enable custom gamescope", "__enabled__")
        prefix_gamescope_row.addWidget(self.prefix_gamescope_mode_combo, 1)
        prefix_gamescope_card.body.addLayout(prefix_gamescope_row)

        self.prefix_gamescope_editor = GamescopeEditor(
            show_toggle=False,
            description="0 keeps gamescope defaults. Extra args are appended before Wine or Proton.",
            parent=self,
        )
        self.prefix_gamescope_editor.settingsChanged.connect(self.on_prefix_gamescope_settings_changed)
        prefix_gamescope_card.body.addWidget(self.prefix_gamescope_editor)

        self.prefix_gamescope_label = QLabel("No prefix selected")
        self.prefix_gamescope_label.setObjectName("MutedText")
        self.prefix_gamescope_label.setWordWrap(True)
        prefix_gamescope_card.body.addWidget(self.prefix_gamescope_label)
        prefix_layout.addWidget(prefix_gamescope_card)
        prefix_layout.addStretch()
        self.settings_pages.addWidget(prefix_page)

        sources_page = QWidget()
        sources_page.setObjectName("SettingsPage")
        sources_layout = QVBoxLayout(sources_page)
        sources_layout.setContentsMargins(0, 0, 0, 0)
        sources_layout.setSpacing(12)

        roots_card = SectionCard(
            "Additional Prefix Sources",
            "Folders scanned in addition to the default Wine locations.",
        )
        self.roots_list = QListWidget()
        self.roots_list.setObjectName("PrefixSourceList")
        for directory in self.config.extra_prefix_dirs():
            self.roots_list.addItem(directory)
        roots_card.body.addWidget(self.roots_list)

        root_buttons = QHBoxLayout()
        add_button = QPushButton("Add Folder")
        add_button.clicked.connect(self.add_directory)
        root_buttons.addWidget(add_button)

        remove_button = QPushButton("Remove Selected")
        remove_button.clicked.connect(self.remove_directory)
        root_buttons.addWidget(remove_button)

        roots_card.body.addLayout(root_buttons)
        sources_layout.addWidget(roots_card, 1)
        self.settings_pages.addWidget(sources_page)

        footer = QFrame()
        footer.setObjectName("SettingsFooter")
        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.addStretch()

        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(self.reject)
        actions.addWidget(cancel_button)

        save_button = QPushButton("Save")
        _apply_variant(save_button, "primary")
        save_button.clicked.connect(self.save_settings)
        actions.addWidget(save_button)
        footer.setLayout(actions)
        root.addWidget(footer)

        self.settings_nav.currentRowChanged.connect(self.settings_pages.setCurrentIndex)
        self.settings_nav.setCurrentRow(1 if selected_prefix is not None else 0)

        self.prefix_selector.currentIndexChanged.connect(self.on_prefix_selection_changed)
        self.prefix_override_combo.currentIndexChanged.connect(self.on_prefix_override_changed)
        self.prefix_gamescope_mode_combo.currentIndexChanged.connect(self.on_prefix_gamescope_mode_changed)

        if self.prefix_selector.count() == 0:
            self.prefix_selector.setEnabled(False)
            self.prefix_override_combo.setEnabled(False)
            self.prefix_gamescope_mode_combo.setEnabled(False)
            self.prefix_gamescope_editor.set_fields_enabled(False)
            self.prefix_override_label.setText("No prefixes found yet.")
            self.prefix_gamescope_label.setText("No prefixes found yet.")
        else:
            if selected_prefix is not None:
                index = self.prefix_selector.findData(selected_prefix)
                self.prefix_selector.setCurrentIndex(index if index >= 0 else 0)
            else:
                self.prefix_selector.setCurrentIndex(0)
            self.on_prefix_selection_changed()

    def browse_proton_dir(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, "Choose Proton Directory", self.proton_dir_edit.text())
        if directory:
            self.proton_dir_edit.setText(directory)

    def add_directory(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, "Choose Prefix Source")
        if not directory:
            return
        existing = {self.roots_list.item(index).text() for index in range(self.roots_list.count())}
        if directory not in existing:
            self.roots_list.addItem(directory)

    def remove_directory(self) -> None:
        row = self.roots_list.currentRow()
        if row >= 0:
            self.roots_list.takeItem(row)

    def on_prefix_selection_changed(self) -> None:
        prefix = self.prefix_selector.currentData()
        if not prefix:
            self.prefix_override_label.setText("No prefix selected")
            self.prefix_gamescope_label.setText("No prefix selected")
            return

        self._syncing_prefix_override = True
        override = self.prefix_overrides.get(prefix)
        target = "__inherit__" if override is None else override
        index = self.prefix_override_combo.findData(target)
        self.prefix_override_combo.setCurrentIndex(index if index >= 0 else 0)
        self._syncing_prefix_override = False
        self.prefix_override_label.setText(prefix)

        self._syncing_prefix_gamescope = True
        gamescope_override = self.prefix_gamescope_overrides.get(prefix)
        gamescope_target = "__inherit__"
        gamescope_settings = self.default_gamescope_editor.current_settings()
        if gamescope_override is not None:
            gamescope_target = "__enabled__" if gamescope_override.enabled else "__disabled__"
            gamescope_settings = gamescope_override
        index = self.prefix_gamescope_mode_combo.findData(gamescope_target)
        self.prefix_gamescope_mode_combo.setCurrentIndex(index if index >= 0 else 0)
        self.prefix_gamescope_editor.set_settings(gamescope_settings)
        self.prefix_gamescope_editor.set_fields_enabled(gamescope_target == "__enabled__")
        self._syncing_prefix_gamescope = False
        self._refresh_prefix_gamescope_label(prefix)

    def on_prefix_override_changed(self) -> None:
        if self._syncing_prefix_override:
            return
        prefix = self.prefix_selector.currentData()
        if not prefix:
            return

        value = self.prefix_override_combo.currentData()
        if value == "__inherit__":
            self.prefix_overrides.pop(prefix, None)
            self.prefix_override_label.setText(f"{prefix}\nUses the global default.")
        else:
            self.prefix_overrides[prefix] = value or ""
            if value:
                self.prefix_override_label.setText(f"{prefix}\nOverride: Proton {value}")
            else:
                self.prefix_override_label.setText(f"{prefix}\nOverride: System Wine")

    def on_prefix_gamescope_mode_changed(self) -> None:
        if self._syncing_prefix_gamescope:
            return

        prefix = self.prefix_selector.currentData()
        if not prefix:
            return

        value = self.prefix_gamescope_mode_combo.currentData()
        if value == "__inherit__":
            self.prefix_gamescope_overrides.pop(prefix, None)
            self.prefix_gamescope_editor.set_settings(self.default_gamescope_editor.current_settings())
            self.prefix_gamescope_editor.set_fields_enabled(False)
        else:
            enabled = value == "__enabled__"
            self.prefix_gamescope_editor.set_fields_enabled(enabled)
            self.prefix_gamescope_overrides[prefix] = self.prefix_gamescope_editor.current_settings(force_enabled=enabled)
        self._refresh_prefix_gamescope_label(prefix)

    def on_prefix_gamescope_settings_changed(self) -> None:
        if self._syncing_prefix_gamescope:
            return

        prefix = self.prefix_selector.currentData()
        if not prefix:
            return

        value = self.prefix_gamescope_mode_combo.currentData()
        if value == "__inherit__":
            return
        self.prefix_gamescope_overrides[prefix] = self.prefix_gamescope_editor.current_settings(
            force_enabled=value == "__enabled__"
        )
        self._refresh_prefix_gamescope_label(prefix)

    def refresh_current_prefix_previews(self) -> None:
        prefix = self.prefix_selector.currentData()
        if not prefix:
            return
        if self.prefix_gamescope_mode_combo.currentData() == "__inherit__":
            self._syncing_prefix_gamescope = True
            self.prefix_gamescope_editor.set_settings(self.default_gamescope_editor.current_settings())
            self.prefix_gamescope_editor.set_fields_enabled(False)
            self._syncing_prefix_gamescope = False
        self._refresh_prefix_gamescope_label(prefix)

    def _refresh_prefix_gamescope_label(self, prefix: str) -> None:
        override = self.prefix_gamescope_overrides.get(prefix)
        if override is None:
            summary = _gamescope_summary(self.default_gamescope_editor.current_settings())
            self.prefix_gamescope_label.setText(f"{prefix}\nUses global default: {summary}")
            return
        self.prefix_gamescope_label.setText(f"{prefix}\nCustom override: {_gamescope_summary(override)}")

    def save_settings(self) -> None:
        proton_dir = self.proton_dir_edit.text().strip()
        if not proton_dir:
            QMessageBox.warning(self, "Incomplete", "Please choose a Proton directory.")
            return

        self.config.data["proton_dir"] = proton_dir
        self.config.data["default_proton"] = self.default_runtime_combo.currentData() or ""
        self.config.data["proton_launch_backend"] = self.proton_backend_combo.currentData() or "umu"
        self.config.data["gamescope_defaults"] = self.default_gamescope_editor.current_settings().to_config()
        self.config.data["prefix_proton_map"] = dict(self.prefix_overrides)
        self.config.data["prefix_gamescope_map"] = {
            prefix: settings.to_config() for prefix, settings in self.prefix_gamescope_overrides.items()
        }
        self.config.data["extra_prefix_dirs"] = [
            self.roots_list.item(index).text() for index in range(self.roots_list.count())
        ]
        self.config.save()
        self.accept()


class LogsDialog(QDialog):
    def __init__(self, logger: LogManager, parent=None):
        super().__init__(parent)
        self.logger = logger

        self.setWindowTitle("Activity Log")
        self.resize(880, 620)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(14)

        header = SectionCard("Activity Log", "The latest events, downloads, and launcher messages at a glance.")
        controls = QHBoxLayout()
        controls.setSpacing(10)

        self.level_combo = QComboBox()
        self.level_combo.addItems(["All", "INFO", "WARNING", "ERROR", "DEBUG"])
        self.level_combo.currentTextChanged.connect(self.refresh_logs)
        controls.addWidget(self.level_combo)

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search logs")
        self.search_edit.textChanged.connect(self.refresh_logs)
        controls.addWidget(self.search_edit, 1)

        clear_button = QPushButton("Clear")
        clear_button.clicked.connect(self.clear_logs)
        controls.addWidget(clear_button)

        copy_button = QPushButton("Copy")
        copy_button.clicked.connect(self.copy_logs)
        controls.addWidget(copy_button)

        export_button = QPushButton("Export")
        export_button.clicked.connect(self.export_logs)
        controls.addWidget(export_button)

        header.body.addLayout(controls)
        root.addWidget(header)

        self.log_view = QTextBrowser()
        mono_font = QFont("Monospace")
        mono_font.setStyleHint(QFont.Monospace)
        self.log_view.setFont(mono_font)
        root.addWidget(self.log_view, 1)

        self.stats_label = QLabel()
        self.stats_label.setObjectName("MutedText")
        root.addWidget(self.stats_label)

        close_row = QHBoxLayout()
        close_row.addStretch()
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.accept)
        close_row.addWidget(close_button)
        root.addLayout(close_row)

        self.logger.logUpdated.connect(self.on_log_updated)
        self.refresh_logs()

    def matching_logs(self) -> list[str]:
        level = self.level_combo.currentText()
        query = self.search_edit.text().strip().lower()
        result: list[str] = []
        for entry in self.logger.logs:
            if level != "All" and f"[{level}]" not in entry:
                continue
            if query and query not in entry.lower():
                continue
            result.append(entry)
        return result

    def refresh_logs(self) -> None:
        matches = self.matching_logs()
        html_lines = []
        for entry in matches:
            if "[ERROR]" in entry:
                color = LOG_LEVEL_COLORS["ERROR"]
            elif "[WARNING]" in entry:
                color = LOG_LEVEL_COLORS["WARNING"]
            elif "[INFO]" in entry:
                color = LOG_LEVEL_COLORS["INFO"]
            else:
                color = LOG_LEVEL_COLORS["DEFAULT"]
            html_lines.append(f'<span style="color:{color};">{entry}</span>')

        self.log_view.setHtml("<br>".join(html_lines))
        cursor = self.log_view.textCursor()
        cursor.movePosition(QTextCursor.End)
        self.log_view.setTextCursor(cursor)
        self.stats_label.setText(f"{len(matches)} entries visible | {len(self.logger.logs)} total")

    def on_log_updated(self, _entry: str) -> None:
        self.refresh_logs()

    def clear_logs(self) -> None:
        if QMessageBox.question(self, "Clear Logs", "Remove all logs?") != QMessageBox.Yes:
            return
        self.logger.clear()
        self.refresh_logs()

    def copy_logs(self) -> None:
        QApplication.clipboard().setText("\n".join(self.matching_logs()))
        QMessageBox.information(self, "Copied", "The visible logs were copied.")

    def export_logs(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Export Logs", "wine-manager-logs.txt", "Text Files (*.txt)")
        if not path:
            return
        pathlib.Path(path).write_text(self.logger.dump(), encoding="utf-8")
        QMessageBox.information(self, "Exported", f"Logs saved to:\n{path}")