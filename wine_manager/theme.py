from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication


THEME_COLORS = {
    "bg": "#111318",
    "surface": "#171a21",
    "surface_alt": "#20242c",
    "input": "#0c0e12",
    "border": "#343944",
    "text": "#e8e5dc",
    "muted": "#9b9589",
    "accent": "#c89445",
    "success": "#7fa98e",
    "danger": "#c77e73",
}


LOG_LEVEL_COLORS = {
    "ERROR": THEME_COLORS["danger"],
    "WARNING": THEME_COLORS["accent"],
    "INFO": THEME_COLORS["success"],
    "DEFAULT": THEME_COLORS["text"],
}


def apply_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    app.setFont(QFont("Cantarell", 10))
    app.setPalette(_build_palette())
    app.setStyleSheet(_build_stylesheet())


def _build_palette() -> QPalette:
    colors = THEME_COLORS
    palette = QPalette()
    role = QPalette.ColorRole
    group = QPalette.ColorGroup
    palette.setColor(role.Window, QColor(colors["bg"]))
    palette.setColor(role.WindowText, QColor(colors["text"]))
    palette.setColor(role.Base, QColor(colors["input"]))
    palette.setColor(role.AlternateBase, QColor(colors["surface_alt"]))
    palette.setColor(role.ToolTipBase, QColor(colors["surface_alt"]))
    palette.setColor(role.ToolTipText, QColor(colors["text"]))
    palette.setColor(role.Text, QColor(colors["text"]))
    palette.setColor(role.Button, QColor(colors["surface"]))
    palette.setColor(role.ButtonText, QColor(colors["text"]))
    palette.setColor(role.BrightText, QColor(colors["text"]))
    palette.setColor(role.Link, QColor(colors["accent"]))
    palette.setColor(role.LinkVisited, QColor(colors["accent"]))
    palette.setColor(role.Highlight, QColor(colors["accent"]))
    palette.setColor(role.HighlightedText, QColor(colors["text"]))
    palette.setColor(role.PlaceholderText, QColor(colors["muted"]))

    disabled_text = QColor(colors["muted"])
    palette.setColor(group.Disabled, role.WindowText, disabled_text)
    palette.setColor(group.Disabled, role.Text, disabled_text)
    palette.setColor(group.Disabled, role.ButtonText, disabled_text)
    palette.setColor(group.Disabled, role.Base, QColor(colors["input"]))
    palette.setColor(group.Disabled, role.Button, QColor(colors["surface"]))
    palette.setColor(group.Disabled, role.Highlight, QColor(colors["border"]))
    palette.setColor(group.Disabled, role.HighlightedText, QColor(colors["muted"]))
    return palette


def _build_stylesheet() -> str:
    return """
        QWidget {{
            color: {text};
            font-family: Cantarell, "Segoe UI", sans-serif;
        }}
        QWidget#WindowFrame {{
            background: {bg};
        }}
        QMainWindow,
        QDialog {{
            background: {bg};
        }}
        QWidget#HeaderCard,
        QFrame#HeaderCard {{
            background: {surface};
            border: none;
            border-bottom: 1px solid {border};
            border-radius: 0;
        }}
        QFrame#SidebarCard,
        QFrame#SectionCard,
        QFrame#HeroCard,
        QFrame#ReleaseCard,
        QFrame#EmptyCard,
        QFrame#PosterCard {{
            background: {surface};
            border: none;
            border-radius: 0;
        }}
        QToolTip {{
            background: {surface_alt};
            color: {text};
            border: 1px solid {border};
            padding: 6px 8px;
        }}
        QLabel#HeroTitle {{
            color: {text};
            font-size: 17pt;
            font-weight: 700;
            letter-spacing: 0.01em;
        }}
        QLabel#HeroSubtitle {{
            color: {muted};
            font-size: 9.5pt;
        }}
        QLabel#SectionTitle {{
            color: {text};
            font-size: 13pt;
            font-weight: 700;
        }}
        QLabel#SectionSubtitle,
        QLabel#MutedText {{
            color: {muted};
        }}
        QFrame#SettingsHeader {{
            background: {surface};
            border: none;
            border-bottom: 1px solid {border};
            border-radius: 0;
        }}
        QLabel#SettingsTitle {{
            color: {text};
            font-size: 17pt;
            font-weight: 700;
        }}
        QListWidget#SettingsNav {{
            background: {surface};
            border: none;
            border-right: 1px solid {border};
            border-radius: 0;
            padding: 0;
            outline: none;
        }}
        QListWidget#SettingsNav::item {{
            border: none;
            border-radius: 0;
            padding: 10px 10px;
            margin: 0;
            color: {muted};
            font-weight: 700;
        }}
        QListWidget#SettingsNav::item:selected {{
            background: {surface_alt};
            color: {text};
        }}
        QListWidget#SettingsNav::item:hover:!selected {{
            background: {surface_alt};
            color: {text};
        }}
        QFrame#SettingsFooter {{
            background: transparent;
            border: none;
        }}
        QLabel#StatBadgeValue {{
            color: {text};
            font-size: 16pt;
            font-weight: 700;
        }}
        QLabel#StatBadgeLabel {{
            color: {muted};
            font-size: 7.5pt;
            font-weight: 700;
            letter-spacing: 0.12em;
            text-transform: uppercase;
        }}
        QFrame#StatBadge {{
            background: transparent;
            border: none;
            border-radius: 0;
        }}
        QFrame#HeaderDivider {{
            background: {border};
            border: none;
        }}
        QLabel[chip="true"] {{
            background: {surface_alt};
            color: {text};
            border: none;
            border-radius: 0;
            padding: 5px 10px;
            font-weight: 600;
        }}
        QLabel[accent="true"] {{
            background: {surface_alt};
            color: {accent};
            border-color: {accent};
            font-weight: 700;
        }}
        QPushButton#HeaderButton {{
            background: {surface_alt};
            color: {text};
            border: none;
            border-bottom: 2px solid {accent};
            border-radius: 0;
            padding: 10px 18px;
            font-weight: 700;
        }}
        QPushButton#HeaderButton:hover {{
            background: {surface_alt};
        }}
        QPushButton#HeaderButton:pressed {{
            background: {surface};
        }}
        QPushButton#HeaderAction {{
            background: transparent;
            color: {text};
            border: none;
            border-radius: 0;
            padding: 9px 18px;
            font-weight: 600;
        }}
        QPushButton#HeaderAction:hover {{
            background: {surface_alt};
            color: {text};
        }}
        QPushButton#HeaderAction:pressed {{
            background: {surface};
        }}
        QLineEdit,
        QComboBox,
        QSpinBox,
        QListWidget,
        QTextEdit,
        QTextBrowser,
        QPlainTextEdit {{
            background: {input};
            color: {text};
            border: 1px solid {border};
            border-radius: 0;
            padding: 10px 12px;
            selection-background-color: {accent};
            selection-color: {text};
        }}
        QComboBox::drop-down {{
            border: none;
            width: 24px;
        }}
        QSpinBox::up-button,
        QSpinBox::down-button {{
            border: none;
            width: 20px;
        }}
        QAbstractItemView {{
            background: {surface_alt};
            color: {text};
            border: 1px solid {border};
            selection-background-color: {accent};
            selection-color: {text};
        }}
        QLineEdit:focus,
        QComboBox:focus,
        QSpinBox:focus,
        QListWidget:focus,
        QTextEdit:focus,
        QTextBrowser:focus,
        QPlainTextEdit:focus {{
            border: 1px solid {accent};
        }}
        QListWidget::item {{
            border: none;
            border-radius: 0;
            padding: 10px;
            margin: 1px 0;
        }}
        QListWidget#CompactReleaseList::item {{
            padding: 2px;
            margin: 1px 0;
            border: none;
        }}
        QListWidget::item:selected {{
            background: {accent};
            color: {text};
        }}
        QListWidget::item:hover:!selected {{
            background: {surface_alt};
        }}
        QPushButton,
        QToolButton {{
            background: {surface_alt};
            color: {text};
            border: none;
            border-radius: 0;
            padding: 9px 16px;
            font-weight: 600;
        }}
        QPushButton:hover,
        QToolButton:hover {{
            background: {surface_alt};
        }}
        QPushButton:pressed,
        QToolButton:pressed {{
            background: {surface};
        }}
        QPushButton:disabled,
        QToolButton:disabled {{
            color: {muted};
            border-color: {border};
            background: {surface};
        }}
        QPushButton[variant="primary"] {{
            background: {surface_alt};
            color: {text};
            border-bottom: 2px solid {accent};
        }}
        QPushButton[variant="primary"]:hover {{
            background: {surface_alt};
        }}
        QPushButton[variant="primary"]:pressed {{
            background: {surface};
        }}
        QPushButton[variant="secondary"] {{
            background: {success};
            color: {bg};
            border: none;
        }}
        QPushButton[variant="secondary"]:hover {{
            background: {success};
            border-color: {success};
        }}
        QPushButton[variant="secondary"]:pressed {{
            background: {success};
            border-color: {success};
        }}
        QPushButton[variant="danger"] {{
            background: {danger};
            color: {bg};
            border: none;
        }}
        QPushButton[variant="danger"]:hover {{
            background: {danger};
            border-color: {danger};
        }}
        QPushButton[variant="danger"]:pressed {{
            background: {danger};
            border-color: {danger};
        }}
        QWidget#AppListHeader {{
            background: {input};
            border: none;
            border-radius: 0;
        }}
        QLabel#AppListHeaderLabel {{
            color: {muted};
            font-size: 8pt;
            font-weight: 700;
            letter-spacing: 0.10em;
            text-transform: uppercase;
        }}
        QFrame#AppCard {{
            border-radius: 0;
            background: {surface};
            border: none;
            border-bottom: 1px solid {border};
        }}
        QFrame#AppCard:hover {{
            background: {surface_alt};
        }}
        QWidget#AppActionsPanel {{
            background: transparent;
            border: none;
            border-radius: 0;
        }}
        QWidget#AppActionsPanel QPushButton {{
            border-radius: 0;
            padding: 6px 10px;
        }}
        QWidget#AppActionsPanel QPushButton[variant="secondary"] {{
            background: {success};
            color: {bg};
        }}
        QWidget#AppActionsPanel QPushButton[variant="danger"] {{
            background: {danger};
            color: {bg};
        }}
        QLabel#AppCardArt {{
            background: {surface_alt};
            border: none;
            border-radius: 2px;
        }}
        QLabel#AppCardArt:hover {{
            background: {surface_alt};
        }}
        QLabel#AppCardTitle {{
            font-size: 12pt;
            font-weight: 700;
            color: {text};
        }}
        QLabel#AppCardPath {{
            color: {muted};
            font-size: 8.5pt;
        }}
        QLabel#AppCardSummary {{
            color: {muted};
            font-size: 8.8pt;
        }}
        QPushButton#AppFavoriteButton {{
            background: transparent;
            border: none;
            border-radius: 0;
            padding: 0;
            font-size: 15pt;
            font-weight: 800;
            color: {muted};
        }}
        QPushButton#AppFavoriteButton:hover {{
            background: {surface_alt};
            color: {accent};
        }}
        QPushButton#AppFavoriteButton:checked {{
            background: {accent};
            color: {bg};
        }}
        QPushButton#AppFavoriteButton:checked:hover {{
            background: {accent};
            border-color: {accent};
        }}
        QLabel#AppCardChip,
        QLabel#AppCardChipRuntime,
        QLabel#AppCardChipPrefix {{
            border-radius: 0;
            padding: 7px 10px;
            font-size: 8.5pt;
            font-weight: 600;
            letter-spacing: 0.03em;
        }}
        QLabel#AppCardChip {{
            background: {surface_alt};
            border: none;
            color: {muted};
        }}
        QLabel#AppCardChipRuntime {{
            background: {surface_alt};
            border: none;
            color: {text};
        }}
        QLabel#AppCardChipPrefix {{
            background: {surface_alt};
            border: none;
            color: {text};
        }}
        QFrame#PosterCard {{
            border-radius: 0;
            background: {surface};
            border: none;
        }}
        QLabel#ArtworkPreview {{
            background: {surface};
            border: none;
            border-radius: 0;
            padding: 6px;
        }}
        QListWidget#ArtworkSuggestionList::item {{
            min-height: 84px;
            padding: 8px;
        }}
        QLabel#PosterImage {{
            background: {surface_alt};
            border: none;
            border-top-left-radius: 22px;
            border-top-right-radius: 22px;
        }}
        QWidget#PosterOverlay {{
            background: qlineargradient(
                x1: 0, y1: 0, x2: 0, y2: 1,
                stop: 0 {bg},
                stop: 0.46 {surface},
                stop: 1 {bg}
            );
            border-top-left-radius: 22px;
            border-top-right-radius: 22px;
        }}
        QWidget#PosterInfoPanel {{
            background: {surface};
            border: none;
            border-radius: 0;
        }}
        QWidget#PosterOverlay QPushButton {{
            background: {input};
            border: none;
            color: {text};
            border-radius: 0;
            padding: 8px 12px;
            font-weight: 700;
        }}
        QWidget#PosterOverlay QPushButton:hover {{
            background: {surface_alt};
            border-color: {border};
        }}
        QLabel#PosterHoverTitle {{
            font-size: 11pt;
            font-weight: 700;
            color: {text};
        }}
        QLabel#PosterHoverMeta {{
            color: {text};
            font-size: 9pt;
            letter-spacing: 0.06em;
        }}
        QLabel#PosterHoverPrefix {{
            color: {muted};
            font-size: 8.5pt;
            letter-spacing: 0.04em;
        }}
        QCheckBox {{
            spacing: 10px;
            color: {text};
            font-weight: 600;
        }}
        QCheckBox::indicator {{
            width: 18px;
            height: 18px;
            border-radius: 0;
            border: 1px solid {border};
            background: {input};
        }}
        QCheckBox::indicator:hover {{
            border-color: {accent};
        }}
        QCheckBox::indicator:checked {{
            background: {accent};
            border-color: {accent};
        }}
        QCheckBox::indicator:disabled {{
            border-color: {border};
            background: {surface};
        }}
        QProgressBar {{
            background: {input};
            color: {text};
            border: 1px solid {border};
            border-radius: 0;
            text-align: center;
            min-height: 20px;
        }}
        QProgressBar::chunk {{
            background: qlineargradient(
                x1: 0, y1: 0, x2: 1, y2: 0,
                stop: 0 {success},
                stop: 1 {success}
            );
            border-radius: 0;
            margin: 2px;
        }}
        QStatusBar {{
            background: {surface};
            border-top: 1px solid {border};
            color: {muted};
        }}
        QStatusBar::item {{
            border: none;
        }}
        QMenu {{
            background: {surface};
            color: {text};
            border: 1px solid {border};
        }}
        QMenu::item {{
            padding: 7px 18px;
            border-radius: 0;
            margin: 2px 6px;
        }}
        QMenu::item:selected {{
            background: {surface_alt};
        }}
        QScrollBar:vertical {{
            background: transparent;
            width: 7px;
            margin: 4px 0;
        }}
        QScrollBar::handle:vertical {{
            background: {accent};
            border-radius: 3px;
            min-height: 32px;
        }}
        QScrollBar::handle:vertical:hover {{
            background: {accent};
        }}
        QScrollBar:horizontal {{
            background: transparent;
            height: 7px;
            margin: 0 4px;
        }}
        QScrollBar::handle:horizontal {{
            background: {accent};
            border-radius: 3px;
            min-width: 32px;
        }}
        QScrollBar::handle:horizontal:hover {{
            background: {accent};
        }}
        QScrollBar::add-line:vertical,
        QScrollBar::sub-line:vertical,
        QScrollBar::add-page:vertical,
        QScrollBar::sub-page:vertical,
        QScrollBar::add-line:horizontal,
        QScrollBar::sub-line:horizontal,
        QScrollBar::add-page:horizontal,
        QScrollBar::sub-page:horizontal {{
            background: transparent;
            width: 0;
            height: 0;
        }}
    """.format_map(THEME_COLORS)