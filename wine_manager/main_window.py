from __future__ import annotations

import pathlib

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from .dialogs import (
    AddAppDialog,
    AppArtworkDialog,
    AppPosterSettingsDialog,
    LaunchExeDialog,
    LogsDialog,
    ProtonHubDialog,
    SettingsDialog,
)
from .services import (
    AppEntry,
    ConfigStore,
    LaunchService,
    LogManager,
    ProgramScanner,
    ProtonManager,
    aggregate_apps,
    discover_prefixes,
    is_system_executable,
    normalize_app_name,
)
from .widgets import AppCard, StatBadge, add_shadow
from .widgets import APP_ACTIONS_WIDTH, APP_ART_WIDTH, APP_FAVORITE_WIDTH, APP_PREFIX_WIDTH, APP_RUNTIME_WIDTH


INITIAL_RENDER_COUNT = 48
LOAD_MORE_BATCH = 24
SCROLL_LOAD_THRESHOLD = 320


def _decorate_chip(label: QLabel, accent: bool = False) -> None:
    label.setProperty("chip", True)
    label.setProperty("accent", accent)
    label.style().unpolish(label)
    label.style().polish(label)
    label.setMinimumWidth(label.fontMetrics().horizontalAdvance(label.text()) + 28)


class WineManagerWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Wine Manager")
        self.resize(1320, 900)
        self.setMinimumSize(1120, 760)

        self.config = ConfigStore()
        self.logger = LogManager()
        self.pm = ProtonManager(self.config, self.logger)
        self.scanner = ProgramScanner(self.logger)
        self.launcher = LaunchService(self.pm, self.config, self.logger)

        self.prefixes: list[str] = []
        self.installed_tags: list[str] = []
        self.app_entries: list[AppEntry] = []
        self.app_entries_by_key: dict[str, AppEntry] = {}
        self.app_cards: dict[str, AppCard] = {}
        self.filtered_app_entries: list[AppEntry] = []
        self._scanning_prefixes: set[str] = set()
        self._last_columns = 0
        self._rendered_count = 0
        self._settings_prefix_hint: str | None = None
        self._render_timer = QTimer(self)
        self._render_timer.setSingleShot(True)
        self._render_timer.setInterval(120)
        self._fill_timer = QTimer(self)
        self._fill_timer.setSingleShot(True)
        self._fill_timer.setInterval(0)
        self._is_appending = False

        self._build_ui()
        self._connect_signals()

        self.logger.add("INFO", "Wine Manager started", "System")
        self.refresh_prefixes()

    def _build_ui(self) -> None:
        frame = QWidget()
        frame.setObjectName("WindowFrame")
        self.setCentralWidget(frame)

        root = QVBoxLayout(frame)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(14)
        root.addWidget(self._build_header())
        root.addWidget(self._build_library(), 1)

        status = QStatusBar()
        self.setStatusBar(status)
        status.showMessage("Ready")

    def _build_header(self) -> QWidget:
        card = QFrame()
        card.setObjectName("HeaderCard")
        add_shadow(card)

        layout = QHBoxLayout(card)
        layout.setContentsMargins(24, 16, 22, 16)
        layout.setSpacing(20)

        brand = QVBoxLayout()
        brand.setSpacing(3)

        title = QLabel("Wine Manager")
        title.setObjectName("HeroTitle")
        brand.addWidget(title)

        subtitle = QLabel("Launch and manage Windows apps across every prefix from one place.")
        subtitle.setObjectName("HeroSubtitle")
        subtitle.setWordWrap(True)
        brand.addWidget(subtitle)
        layout.addLayout(brand)

        layout.addStretch()

        self.prefix_stat = StatBadge("Prefixes")
        self.apps_stat = StatBadge("Apps")
        self.runtime_stat = StatBadge("Runtimes")
        for badge in (self.prefix_stat, self.apps_stat, self.runtime_stat):
            layout.addWidget(badge)

        divider = QFrame()
        divider.setObjectName("HeaderDivider")
        divider.setFixedWidth(1)
        layout.addWidget(divider)

        self.proton_manager_button = QPushButton("Proton")
        self.proton_manager_button.setToolTip("Install, remove and update Proton builds")
        self.settings_button = QPushButton("Settings")
        self.settings_button.setToolTip("Adjust defaults, gamescope presets and prefix overrides")
        self.logs_button = QPushButton("Logs")
        self.logs_button.setToolTip("Review recent launches, scans and service output")
        for button in (self.proton_manager_button, self.settings_button, self.logs_button):
            button.setObjectName("HeaderAction")
            button.setCursor(Qt.PointingHandCursor)
            layout.addWidget(button)

        return card

    def _build_library(self) -> QWidget:
        card = QFrame()
        card.setObjectName("SectionCard")
        add_shadow(card)

        root = QVBoxLayout(card)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(14)

        header_row = QHBoxLayout()
        header_row.setSpacing(10)

        toolbar_title = QLabel("Library")
        toolbar_title.setObjectName("SectionTitle")
        header_row.addWidget(toolbar_title)

        self.library_info = QLabel("No apps loaded yet")
        self.library_info.setObjectName("MutedText")
        header_row.addWidget(self.library_info)
        header_row.addStretch()

        self.library_state_chip = QLabel("Ready")
        _decorate_chip(self.library_state_chip, accent=True)
        header_row.addWidget(self.library_state_chip)
        root.addLayout(header_row)

        controls = QHBoxLayout()
        controls.setSpacing(10)

        self.search_edit = QLineEdit()
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.setPlaceholderText("Search by app, executable or prefix")
        controls.addWidget(self.search_edit, 1)

        self.favorites_only = QCheckBox("Favorites only")
        controls.addWidget(self.favorites_only)

        self.hide_system_apps = QCheckBox("Hide system apps")
        self.hide_system_apps.setChecked(True)
        controls.addWidget(self.hide_system_apps)

        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.setCursor(Qt.PointingHandCursor)
        controls.addWidget(self.refresh_button)

        self.launch_exe_button = QPushButton("Launch .exe")
        self.launch_exe_button.setCursor(Qt.PointingHandCursor)
        controls.addWidget(self.launch_exe_button)

        self.add_app_button = QPushButton("Add App")
        self.add_app_button.setObjectName("HeaderButton")
        self.add_app_button.setCursor(Qt.PointingHandCursor)
        controls.addWidget(self.add_app_button)
        root.addLayout(controls)

        self.list_header = QWidget()
        self.list_header.setObjectName("AppListHeader")
        header_layout = QHBoxLayout(self.list_header)
        header_layout.setContentsMargins(14, 8, 14, 8)
        header_layout.setSpacing(12)

        art_spacer = QLabel("")
        art_spacer.setFixedWidth(APP_ART_WIDTH)
        header_layout.addWidget(art_spacer)

        app_label = QLabel("App")
        app_label.setObjectName("AppListHeaderLabel")
        header_layout.addWidget(app_label, 1)

        favorite_label = QLabel("★")
        favorite_label.setObjectName("AppListHeaderLabel")
        favorite_label.setFixedWidth(APP_FAVORITE_WIDTH)
        favorite_label.setAlignment(Qt.AlignCenter)
        header_layout.addWidget(favorite_label)

        runtime_label = QLabel("Runtime")
        runtime_label.setObjectName("AppListHeaderLabel")
        runtime_label.setFixedWidth(APP_RUNTIME_WIDTH)
        runtime_label.setAlignment(Qt.AlignCenter)
        header_layout.addWidget(runtime_label)

        prefix_label = QLabel("Prefix")
        prefix_label.setObjectName("AppListHeaderLabel")
        prefix_label.setFixedWidth(APP_PREFIX_WIDTH)
        prefix_label.setAlignment(Qt.AlignCenter)
        header_layout.addWidget(prefix_label)

        actions_label = QLabel("Actions")
        actions_label.setObjectName("AppListHeaderLabel")
        actions_label.setFixedWidth(APP_ACTIONS_WIDTH)
        actions_label.setAlignment(Qt.AlignCenter)
        header_layout.addWidget(actions_label)
        root.addWidget(self.list_header)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QScrollArea.NoFrame)

        self.grid_host = QWidget()
        self.grid_layout = QGridLayout(self.grid_host)
        self.grid_layout.setContentsMargins(0, 0, 0, 0)
        self.grid_layout.setHorizontalSpacing(12)
        self.grid_layout.setVerticalSpacing(12)

        self.scroll_area.setWidget(self.grid_host)
        root.addWidget(self.scroll_area, 1)
        return card

    def _connect_signals(self) -> None:
        self.search_edit.textChanged.connect(self.schedule_render_app_wall)
        self.favorites_only.stateChanged.connect(self.schedule_render_app_wall)
        self.hide_system_apps.stateChanged.connect(self.schedule_render_app_wall)
        self.pm.installedReady.connect(self.on_installed_ready)
        self.scanner.scanStarted.connect(self.on_scan_started)
        self.scanner.scanned.connect(self.on_apps_scanned)
        self.logger.logUpdated.connect(self.on_log_updated)
        self._render_timer.timeout.connect(self.render_app_wall)
        self._fill_timer.timeout.connect(self.fill_viewport_if_needed)

        self.proton_manager_button.clicked.connect(self.show_proton_hub)
        self.settings_button.clicked.connect(self.show_settings)
        self.logs_button.clicked.connect(self.show_logs)
        self.launch_exe_button.clicked.connect(self.show_launch_exe_dialog)
        self.add_app_button.clicked.connect(self.show_add_app_dialog)
        self.refresh_button.clicked.connect(self.refresh_prefixes)
        self.scroll_area.verticalScrollBar().valueChanged.connect(self.on_scroll_changed)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        columns = self.current_columns()
        if columns != self._last_columns:
            self.rebuild_app_wall(preserve_count=True)

    def refresh_prefixes(self) -> None:
        self.statusBar().showMessage("Searching prefixes...")
        self.prefixes = discover_prefixes(self.config, self.logger)
        self._settings_prefix_hint = self.prefixes[0] if self.prefixes else None
        self.pm.refresh_directory()
        self.pm.query_installed()
        self.update_app_entries()
        for prefix in self.prefixes:
            self.scanner.scan(prefix)
        self.statusBar().showMessage("Prefixes refreshed")

    def on_installed_ready(self, tags: list[str]) -> None:
        self.installed_tags = tags
        self.update_app_entries()

    def on_scan_started(self, prefix: str) -> None:
        self._scanning_prefixes.add(prefix)
        self._set_library_info("Updating library")
        self._set_library_status(f"Scanning {len(self._scanning_prefixes)}")
        self.refresh_header_stats()

    def on_apps_scanned(self, prefix: str, _apps: list[str]) -> None:
        self._scanning_prefixes.discard(prefix)
        self.update_app_entries()

    def on_log_updated(self, entry: str) -> None:
        self.statusBar().showMessage(entry)

    def update_app_entries(self) -> None:
        self.app_entries = aggregate_apps(self.prefixes, self.scanner.cache, self.config, self.installed_tags)
        self.app_entries_by_key = {entry.key: entry for entry in self.app_entries}
        self.refresh_header_stats()
        self.render_app_wall()

    def refresh_header_stats(self) -> None:
        prefix_count = len(self.prefixes)
        app_count = len(self.app_entries)
        runtime_count = len(self.installed_tags)

        self.prefix_stat.set_value(str(prefix_count))
        self.apps_stat.set_value(str(app_count))
        self.runtime_stat.set_value(str(runtime_count) if runtime_count else "Auto")

        self.refresh_prefix_actions()

    def refresh_prefix_actions(self) -> None:
        has_prefixes = bool(self.prefixes)
        self.add_app_button.setEnabled(has_prefixes)
        self.launch_exe_button.setEnabled(has_prefixes)
        if has_prefixes:
            self.add_app_button.setToolTip("Add an app to a prefix")
            self.launch_exe_button.setToolTip("Launch a selected .exe with custom options")
        else:
            self.add_app_button.setToolTip("No prefixes available")
            self.launch_exe_button.setToolTip("No prefixes available")

    def _set_library_info(self, text: str) -> None:
        self.library_info.setText(text)
        self.library_info.setToolTip(text)

    def _set_library_status(self, text: str, accent: bool = False) -> None:
        self.library_state_chip.setText(text)
        _decorate_chip(self.library_state_chip, accent=accent)

    def filtered_entries(self) -> list[AppEntry]:
        query = self.search_edit.text().strip().lower()
        favorites_only = self.favorites_only.isChecked()
        hide_system_apps = self.hide_system_apps.isChecked()
        result: list[AppEntry] = []
        for entry in self.app_entries:
            if favorites_only and not entry.is_favorite:
                continue
            if hide_system_apps and is_system_executable(entry.exe_path, entry.display_name):
                continue
            haystack = f"{entry.display_name} {entry.exe_path} {pathlib.Path(entry.prefix).name}".lower()
            if query and query not in haystack:
                continue
            result.append(entry)
        return result

    def current_columns(self) -> int:
        return 1

    def clear_grid(self) -> None:
        while self.grid_layout.count():
            item = self.grid_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self.app_cards.clear()
        self._rendered_count = 0
        self._is_appending = False

    def schedule_render_app_wall(self) -> None:
        self._render_timer.start()

    def render_app_wall(self) -> None:
        self.filtered_app_entries = self.filtered_entries()
        self.rebuild_app_wall()

    def rebuild_app_wall(self, preserve_count: bool = False) -> None:
        entries = self.filtered_app_entries if preserve_count else self.filtered_entries()
        if not preserve_count:
            self.filtered_app_entries = entries

        previous_rendered_count = self._rendered_count

        self.clear_grid()

        if self._scanning_prefixes:
            self._set_library_info(f"{len(entries)} visible | {len(self._scanning_prefixes)} scanning")
            self._set_library_status(f"Scanning {len(self._scanning_prefixes)}")
        else:
            self._set_library_info(f"{len(entries)} apps visible")
            self._set_library_status("Ready", accent=True)
        self.list_header.setVisible(bool(entries))

        if not entries:
            empty = QLabel("No apps match the current filter.")
            empty.setObjectName("MutedText")
            empty.setAlignment(Qt.AlignCenter)
            self.grid_layout.addWidget(empty, 0, 0)
            self._last_columns = self.current_columns()
            return

        columns = self.current_columns()
        self._last_columns = columns
        target_count = INITIAL_RENDER_COUNT
        if preserve_count:
            target_count = max(previous_rendered_count, INITIAL_RENDER_COUNT)
        self.append_cards(min(len(entries), target_count))
        self._fill_timer.start()

    def append_cards(self, target_count: int) -> None:
        if self._is_appending:
            return
        self._is_appending = True
        entries = self.filtered_app_entries
        columns = self._last_columns or self.current_columns()
        start_index = self._rendered_count
        for index in range(start_index, target_count):
            entry = entries[index]
            card = AppCard()
            card.set_content(
                entry.display_name,
                self.poster_meta(entry),
                self.poster_prefix(entry),
                entry.exe_path,
                self.app_art_path(entry),
                self.app_art_zoom(entry),
                entry.is_favorite,
                self.poster_tooltip(entry),
            )
            card.playRequested.connect(lambda entry=entry: self.launch_entry(entry))
            card.settingsRequested.connect(lambda entry=entry: self.open_app_settings(entry))
            card.favoriteToggled.connect(lambda checked, entry=entry: self.toggle_entry_favorite(entry, checked))
            card.removeRequested.connect(lambda entry=entry: self.confirm_remove_entry(entry))
            card.artClicked.connect(lambda entry=entry: self.open_app_artwork(entry))
            self.app_cards[entry.key] = card
            self.grid_layout.addWidget(card, index // columns, index % columns)

        self._rendered_count = target_count
        self.grid_host.adjustSize()
        total_entries = len(entries)
        if self._scanning_prefixes:
            self._set_library_info(f"{self._rendered_count}/{total_entries} loaded | {len(self._scanning_prefixes)} scanning")
            self._set_library_status(f"Scanning {len(self._scanning_prefixes)}")
        else:
            self._set_library_info(f"{self._rendered_count}/{total_entries} apps loaded")
            self._set_library_status("Ready", accent=True)

        self.grid_layout.setColumnStretch(0, 1)
        self._is_appending = False

    def fill_viewport_if_needed(self) -> None:
        if self._is_appending:
            self._fill_timer.start()
            return
        if self._rendered_count >= len(self.filtered_app_entries):
            return
        scrollbar = self.scroll_area.verticalScrollBar()
        if scrollbar.maximum() > 0:
            return
        next_count = min(len(self.filtered_app_entries), self._rendered_count + LOAD_MORE_BATCH)
        if next_count == self._rendered_count:
            return
        self.append_cards(next_count)
        if self._rendered_count < len(self.filtered_app_entries):
            self._fill_timer.start()

    def on_scroll_changed(self, value: int) -> None:
        if self._is_appending:
            return
        scrollbar = self.scroll_area.verticalScrollBar()
        if value < scrollbar.maximum() - SCROLL_LOAD_THRESHOLD:
            return
        if self._rendered_count >= len(self.filtered_app_entries):
            return
        next_count = min(len(self.filtered_app_entries), self._rendered_count + LOAD_MORE_BATCH)
        self.append_cards(next_count)

    def poster_meta(self, entry: AppEntry) -> str:
        runtime_text = "Wine" if not entry.runtime_tag else entry.runtime_tag
        if self.config.effective_gamescope(entry.prefix, entry.exe_path).enabled:
            return f"{runtime_text} + GS"
        return runtime_text

    def poster_prefix(self, entry: AppEntry) -> str:
        return pathlib.Path(entry.prefix).name or entry.prefix

    def poster_tooltip(self, entry: AppEntry) -> str:
        lines = [entry.exe_path, f"Prefix: {entry.prefix}"]
        if self.config.effective_gamescope(entry.prefix, entry.exe_path).enabled:
            lines.append("Gamescope: enabled")
        return "\n\n".join(lines)

    def app_art_path(self, entry: AppEntry) -> str:
        return self.config.app_art_override(entry.prefix, entry.exe_path) or ""

    def app_art_zoom(self, entry: AppEntry) -> int:
        return self.config.app_art_zoom(entry.prefix, entry.exe_path)

    def launch_entry(self, entry: AppEntry) -> bool:
        try:
            result = self.launcher.launch(entry.prefix, entry.exe_path, entry.runtime_tag)
        except Exception as error:
            self.logger.add("ERROR", f"Launch failed: {error}", "Launcher")
            return False
        self.statusBar().showMessage(f"{entry.display_name} launched with {result.runtime_label}")
        return True

    def toggle_entry_favorite(self, entry: AppEntry, is_favorite: bool) -> None:
        if is_favorite:
            self.config.add_favorite(entry.prefix, entry.exe_path)
            self.statusBar().showMessage(f"{entry.display_name} added to favorites")
        else:
            self.config.remove_favorite(entry.prefix, entry.exe_path)
            self.statusBar().showMessage(f"{entry.display_name} removed from favorites")
        self.update_app_entries()

    def show_add_app_dialog(self) -> None:
        if not self.prefixes:
            self.statusBar().showMessage("No prefixes available")
            return

        dialog = AddAppDialog(self.prefixes, self._settings_prefix_hint, self)
        if dialog.exec() != QDialog.Accepted:
            return
        prefix = dialog.selected_prefix()
        exe_path = dialog.selected_path()
        if not prefix or not exe_path:
            return
        self.add_app_to_prefix(prefix, exe_path)

    def show_launch_exe_dialog(self) -> None:
        if not self.prefixes:
            self.statusBar().showMessage("No prefixes available")
            return

        dialog = LaunchExeDialog(self.prefixes, self.installed_tags, self.config, self._settings_prefix_hint, self)
        if dialog.exec() != QDialog.Accepted:
            return

        prefix = dialog.selected_prefix()
        exe_path = dialog.selected_path()
        if not prefix or not exe_path:
            return

        runtime_tag = dialog.selected_runtime()
        gamescope_settings = dialog.selected_gamescope()
        launch_args = dialog.selected_arguments()
        try:
            result = self.launcher.launch(prefix, exe_path, runtime_tag, gamescope_settings, launch_args)
        except Exception as error:
            self.logger.add("ERROR", f"Launch failed: {error}", "Launcher")
            self.statusBar().showMessage(f"Launch failed: {error}")
            return

        self._settings_prefix_hint = prefix
        if dialog.should_add_to_library():
            self.add_app_to_prefix(prefix, exe_path)
            self.config.set_app_runtime_override(prefix, exe_path, dialog.runtime_override_value())
            self.config.set_app_gamescope_override(prefix, exe_path, gamescope_settings)
            self.update_app_entries()

        app_name = normalize_app_name(exe_path)
        self.statusBar().showMessage(f"{app_name} launched with {result.runtime_label}")

    def add_app_to_prefix(self, prefix: str, exe_path: str) -> None:
        prefix_name = pathlib.Path(prefix).name or prefix
        app_name = normalize_app_name(exe_path)
        already_visible = f"{prefix}::{exe_path}" in self.app_entries_by_key
        was_hidden = exe_path in self.config.hidden_apps_for(prefix)
        if was_hidden:
            self.config.unhide_app(prefix, exe_path)
        added = self.config.add_manual_app(prefix, exe_path)
        self._settings_prefix_hint = prefix
        self.update_app_entries()

        if was_hidden and not added:
            self.statusBar().showMessage(f"{app_name} restored to {prefix_name}")
            return

        if not added:
            self.statusBar().showMessage(f"{app_name} is already linked to {prefix_name}")
            return

        if already_visible:
            self.statusBar().showMessage(f"{app_name} is now pinned to {prefix_name}")
        else:
            self.statusBar().showMessage(f"{app_name} added to {prefix_name}")
        self.logger.add("INFO", f"Added {exe_path} to prefix {prefix}", "Library")

    def confirm_remove_entry(self, entry: AppEntry) -> None:
        app_name = entry.display_name
        if (
            QMessageBox.question(
                self,
                "Remove App",
                f"Remove {app_name} from the library?\n\nThis does not uninstall the app. You can add it again later with Add App.",
            )
            != QMessageBox.Yes
        ):
            return
        self.remove_entry_from_library(entry)

    def remove_entry_from_library(self, entry: AppEntry) -> None:
        removed = self.config.remove_app_from_library(entry.prefix, entry.exe_path)
        self._settings_prefix_hint = entry.prefix
        self.update_app_entries()
        if removed:
            self.statusBar().showMessage(f"{entry.display_name} removed from the library")
            self.logger.add("INFO", f"Removed {entry.exe_path} from the library", "Library")
        else:
            self.statusBar().showMessage(f"{entry.display_name} is already hidden")

    def open_app_settings(self, entry: AppEntry) -> None:
        self._settings_prefix_hint = entry.prefix
        dialog = AppPosterSettingsDialog(
            self.config,
            self.installed_tags,
            entry.display_name,
            entry.prefix,
            entry.exe_path,
            self.show_settings,
            self,
        )
        dialog.exec()
        self.update_app_entries()

    def open_app_artwork(self, entry: AppEntry) -> None:
        dialog = AppArtworkDialog(self.config, self.logger, entry.display_name, entry.prefix, entry.exe_path, self)
        if dialog.exec() == QDialog.Accepted:
            self.render_app_wall()
            self.statusBar().showMessage(f"Artwork updated for {entry.display_name}")

    def show_settings(self, prefix_hint: str | None = None) -> None:
        if prefix_hint is not None:
            self._settings_prefix_hint = prefix_hint

        dialog = SettingsDialog(
            self.config,
            self.installed_tags,
            self.prefixes,
            self._settings_prefix_hint,
            self,
        )
        if dialog.exec() == QDialog.Accepted:
            self.pm.refresh_directory()
            self.pm.query_installed()
            self.refresh_prefixes()
            self.logger.add("INFO", "Settings updated", "Settings")

    def show_logs(self) -> None:
        LogsDialog(self.logger, self).exec()

    def show_proton_hub(self) -> None:
        ProtonHubDialog(self.pm, self.logger, self).exec()
        self.pm.query_installed()