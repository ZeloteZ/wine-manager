#!/usr/bin/env python3
"""
Wine Manager

A modern GUI application for managing Wine prefixes and Proton-GE installations.

Features:
- Automatic Wine prefix discovery and management
- Proton-GE version management with automated downloads
- Dark theme interface optimized for productivity
- Favorites system for quick application access
- Cross-runtime support (Wine/Proton-GE)
- Application browser with system file filtering

Author: ZeloteZ
License: MIT
"""
# Standard library imports
import sys, os, threading, pathlib, tempfile, tarfile, shutil, json, subprocess
from datetime import datetime
from dataclasses import dataclass
from typing import List, Optional

# Third-party imports
import requests
from PySide6.QtWidgets import *
from PySide6.QtCore import Qt, Signal, QObject, QTimer
from PySide6.QtGui import QFont, QAction, QTextCursor

# ================================================================================
# Configuration Management
# ================================================================================

# Application configuration paths
CONFIG_DIR = pathlib.Path.home() / ".config" / "wine-manager"
CONFIG_FILE = CONFIG_DIR / "settings.json"

# Default configuration template
DEFAULT_CFG = {
    "proton_dir": "~/.local/share/proton-builds",  # Proton installation directory
    "default_proton": "",                          # Default Proton version
    "prefix_proton_map": {},                       # Prefix -> Proton version mapping
    "extra_prefix_dirs": [],                       # Additional prefix search directories
    "prefix_favorites": {}                         # Prefix -> favorite apps mapping
}

def load_cfg() -> dict:
    """
    Load application configuration from file.
    Creates default config if file doesn't exist.
    
    Returns:
        dict: Configuration dictionary with expanded paths
    """
    if not CONFIG_FILE.exists():
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(json.dumps(DEFAULT_CFG, indent=2))
    
    data = json.loads(CONFIG_FILE.read_text()) if CONFIG_FILE.exists() else {}
    cfg = DEFAULT_CFG.copy()
    cfg.update(data)
    
    # Expand user paths
    cfg["proton_dir"] = str(pathlib.Path(os.path.expanduser(cfg["proton_dir"])))
    cfg["extra_prefix_dirs"] = [str(pathlib.Path(os.path.expanduser(p))) for p in cfg.get("extra_prefix_dirs", [])]
    cfg["prefix_favorites"] = {k: list(v) for k, v in cfg.get("prefix_favorites", {}).items()}
    
    return cfg

def save_cfg(cfg: dict):
    """
    Save configuration to file.
    
    Args:
        cfg: Configuration dictionary to save
    """
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2))

# Load global configuration
CFG = load_cfg()

# ================================================================================
# Logging System
# ================================================================================

class LogManager(QObject):
    """
    Centralized logging system for capturing application output and errors.
    
    Collects logs from various sources including:
    - Application events and status messages
    - Wine/Proton process output and errors
    - System command execution results
    """
    
    logUpdated = Signal(str)  # Emitted when new log entry is added
    
    def __init__(self):
        super().__init__()
        self.logs = []
        self.max_logs = 1000  # Limit log entries to prevent memory issues
    
    def add_log(self, level: str, message: str, source: str = "App"):
        """
        Add a new log entry.
        
        Args:
            level: Log level (INFO, WARNING, ERROR, DEBUG)
            message: Log message
            source: Source of the log entry
        """
        timestamp = datetime.now().strftime("%H:%M:%S")
        log_entry = f"[{timestamp}] [{level}] [{source}] {message}"
        
        self.logs.append(log_entry)
        
        # Keep only recent logs
        if len(self.logs) > self.max_logs:
            self.logs = self.logs[-self.max_logs:]
        
        self.logUpdated.emit(log_entry)
        
        # Also print to console for debugging
        if level in ["ERROR", "WARNING"]:
            print(log_entry, file=sys.stderr)
        else:
            print(log_entry)
    
    def get_all_logs(self) -> str:
        """Get all logs as a single string."""
        return "\n".join(self.logs)
    
    def clear_logs(self):
        """Clear all log entries."""
        self.logs.clear()
        self.logUpdated.emit("Logs cleared")

# Global log manager instance
LOG_MANAGER = LogManager()

# ================================================================================
# Proton Manager
# ================================================================================
@dataclass
class ProtonRelease:
    """Data class representing a Proton-GE release from GitHub."""
    tag: str           # Version tag (e.g., "GE-Proton8-26")
    name: str          # Release name
    published: datetime # Publication date
    asset_url: str     # Download URL for the tar.gz file

class ProtonManager(QObject):
    """
    Manages Proton-GE installations, downloads, and updates.
    
    Handles communication with GitHub API to fetch release information,
    downloads and extracts Proton-GE builds, and manages local installations.
    """
    
    # Qt signals for asynchronous communication
    remoteReady = Signal(list)        # Emitted when remote releases are fetched
    installedReady = Signal(list)     # Emitted when local installations are scanned
    downloadProgress = Signal(str, int, int)  # tag, bytes_done, total_bytes
    installProgress = Signal(str, str)        # tag, status_message
    downloadFinished = Signal(str, bool, str) # tag, success, message
    uninstallFinished = Signal(str, bool, str) # tag, success, message

    # GitHub API configuration
    GITHUB_API = "https://api.github.com/repos/GloriousEggroll/proton-ge-custom/releases"
    CHUNK = 8192  # Download chunk size in bytes

    def __init__(self):
        """Initialize ProtonManager with configured directory."""
        super().__init__()
        self.proton_dir = pathlib.Path(CFG["proton_dir"])
        self.proton_dir.mkdir(parents=True, exist_ok=True)

    def query_remote(self):
        """Start background thread to fetch remote releases from GitHub."""
        threading.Thread(target=self._fetch_remote, daemon=True).start()

    def query_installed(self):
        """Start background thread to scan for locally installed Proton versions."""
        threading.Thread(target=self._emit_installed, daemon=True).start()

    def install(self, tag: str):
        """Start background thread to download and install a Proton version."""
        threading.Thread(target=self._install, args=(tag,), daemon=True).start()

    def uninstall(self, tag: str):
        """Start background thread to remove an installed Proton version."""
        threading.Thread(target=self._uninstall, args=(tag,), daemon=True).start()

    def _fetch_remote(self):
        """
        Fetch available Proton-GE releases from GitHub API.
        Runs in background thread and emits remoteReady signal.
        """
        try:
            r = requests.get(self.GITHUB_API, timeout=20)
            r.raise_for_status()
            lst: List[ProtonRelease] = []
            
            for rel in r.json():
                # Find tar.gz asset in release
                asset = next((a for a in rel.get("assets", []) if a["name"].endswith(".tar.gz")), None)
                if not asset: 
                    continue
                    
                lst.append(ProtonRelease(
                    tag=rel["tag_name"],
                    name=rel["name"],
                    published=datetime.fromisoformat(rel["published_at"].rstrip("Z")),
                    asset_url=asset["browser_download_url"],
                ))
            
            LOG_MANAGER.add_log("INFO", f"Fetched {len(lst)} Proton releases from GitHub", "ProtonManager")
            self.remoteReady.emit(lst)
        except Exception as e:
            error_msg = f"Failed to fetch Proton releases: {e}"
            LOG_MANAGER.add_log("ERROR", error_msg, "ProtonManager")
            print(f"[ProtonManager] fetch error: {e}", file=sys.stderr)
            self.remoteReady.emit([])

    def _emit_installed(self):
        """
        Scan local directory for installed Proton versions.
        Emits installedReady signal with list of installed tags.
        """
        try:
            tags = sorted(p.name for p in self.proton_dir.iterdir() if (p/"proton").exists())
        except Exception:
            tags = []
        self.installedReady.emit(tags)

    def _install(self, tag: str):
        """
        Download and install a specific Proton-GE version.
        
        Args:
            tag: Version tag to install (e.g., "GE-Proton8-26")
        """
        releases = self._sync_remote()
        rel = next((r for r in releases if r.tag == tag), None)
        if not rel:
            LOG_MANAGER.add_log("ERROR", f"Proton release {tag} not found", "ProtonManager")
            self.downloadFinished.emit(tag, False, "Release not found")
            return
            
        dest = self.proton_dir / tag
        if dest.exists():
            LOG_MANAGER.add_log("INFO", f"Proton {tag} already installed", "ProtonManager")
            self.downloadFinished.emit(tag, True, "Already installed")
            return
            
        LOG_MANAGER.add_log("INFO", f"Starting download of Proton {tag}", "ProtonManager")
        
        # Create temporary file for download
        fd, tmp = tempfile.mkstemp(suffix=".tar.gz")
        os.close(fd)
        
        try:
            # Download with progress reporting
            with requests.get(rel.asset_url, stream=True, timeout=30) as resp:
                resp.raise_for_status()
                total = int(resp.headers.get("Content-Length", 0))
                done = 0
                
                with open(tmp, "wb") as f:
                    for chunk in resp.iter_content(self.CHUNK):
                        if chunk:
                            f.write(chunk)
                            done += len(chunk)
                            self.downloadProgress.emit(tag, done, total)
            
            # Installation phase starts
            self.installProgress.emit(tag, "Extracting archive...")
            LOG_MANAGER.add_log("INFO", f"Extracting Proton {tag} archive", "ProtonManager")
            
            # Extract archive
            with tarfile.open(tmp, "r:gz") as tar:
                members = tar.getmembers()
                if not members:
                    raise RuntimeError("Empty archive")
                    
                # Get top-level directory name from archive
                top = members[0].name.split("/",1)[0]
                tar.extractall(self.proton_dir)
            
            # Finalizing installation
            self.installProgress.emit(tag, "Finalizing installation...")
            LOG_MANAGER.add_log("INFO", f"Finalizing Proton {tag} installation", "ProtonManager")
            
            # Rename to expected directory name
            extracted = self.proton_dir / top
            if extracted.exists():
                extracted.rename(dest)
                
            LOG_MANAGER.add_log("INFO", f"Successfully installed Proton {tag}", "ProtonManager")
            self.downloadFinished.emit(tag, True, "Installed")
            
        except Exception as e:
            error_msg = f"Failed to install Proton {tag}: {str(e)}"
            LOG_MANAGER.add_log("ERROR", error_msg, "ProtonManager")
            shutil.rmtree(dest, ignore_errors=True)
            self.downloadFinished.emit(tag, False, str(e))
        finally:
            pathlib.Path(tmp).unlink(missing_ok=True)

    def _uninstall(self, tag: str):
        """
        Remove an installed Proton version.
        
        Args:
            tag: Version tag to uninstall
        """
        dest = self.proton_dir / tag
        if not dest.exists():
            LOG_MANAGER.add_log("WARNING", f"Proton {tag} not installed, cannot uninstall", "ProtonManager")
            self.uninstallFinished.emit(tag, False, "Not installed")
            return
        try:
            shutil.rmtree(dest)
            LOG_MANAGER.add_log("INFO", f"Successfully uninstalled Proton {tag}", "ProtonManager")
            self.uninstallFinished.emit(tag, True, "Uninstalled")
        except Exception as e:
            error_msg = f"Failed to uninstall Proton {tag}: {str(e)}"
            LOG_MANAGER.add_log("ERROR", error_msg, "ProtonManager")
            self.uninstallFinished.emit(tag, False, str(e))

    def _sync_remote(self) -> List[ProtonRelease]:
        """
        Synchronously fetch remote releases (blocking call).
        Used internally for installation process.
        
        Returns:
            List of available ProtonRelease objects
        """
        evt = threading.Event()
        container: List[ProtonRelease] = []
        
        def cb(lst):
            nonlocal container
            container = lst
            evt.set()
            
        self.remoteReady.connect(cb)
        self.query_remote()
        evt.wait(20)  # 20 second timeout
        
        try:
            self.remoteReady.disconnect(cb)
        except:
            pass
        return container

    def proton_executable(self, tag: str) -> Optional[pathlib.Path]:
        """
        Get path to proton executable for a specific version.
        
        Args:
            tag: Proton version tag
            
        Returns:
            Path to proton executable or None if not found
        """
        exe = self.proton_dir / tag / "proton"
        return exe if exe.exists() else None

# ================================================================================
# Helper Functions
# ================================================================================

def discover_prefixes() -> List[str]:
    """
    Automatically discover Wine prefixes in common locations.
    
    Searches standard directories including:
    - ~/.wine (default Wine prefix)
    - ~/.local/share/wineprefixes
    - ~/.local/share/bottles (Bottles app prefixes)
    - User-configured additional directories
    
    Returns:
        List of valid Wine prefix paths
    """
    home = pathlib.Path.home()
    
    # Standard Wine prefix locations
    roots = [
        home/".wine",                                    # Default Wine prefix
        home/".local/share/wineprefixes",               # Common custom location
        home/".local/share/bottles/bottles",            # Bottles app
        home/".local/share/bottles/data/bottles",       # Bottles app (alternative)
        home/".var/app/com.usebottles.bottles/data/bottles",          # Flatpak Bottles
        home/".var/app/com.usebottles.bottles/data/bottles/bottles",  # Flatpak Bottles (nested)
    ]
    
    # Add user-configured directories
    for e in CFG["extra_prefix_dirs"]:
        roots.append(pathlib.Path(e))
    
    prefixes = set()
    
    # Search each root directory for valid prefixes
    for r in roots:
        if not r.exists(): 
            LOG_MANAGER.add_log("DEBUG", f"Root directory does not exist: {r}", "PrefixDiscovery")
            continue
            
        LOG_MANAGER.add_log("DEBUG", f"Scanning root directory: {r}", "PrefixDiscovery")
        
        # Check if the root directory itself is a prefix
        if (r/"system.reg").exists():
            prefixes.add(str(r))
            LOG_MANAGER.add_log("DEBUG", f"Found prefix (root): {r}", "PrefixDiscovery")
        
        # Check subdirectories for prefixes
        try:
            for c in r.iterdir():
                if not c.is_dir():
                    continue
                    
                # Check for system.reg (Wine prefix marker)
                if (c/"system.reg").exists():
                    prefixes.add(str(c))
                    LOG_MANAGER.add_log("DEBUG", f"Found prefix: {c}", "PrefixDiscovery")
                # Check for nested prefix structure (some tools use this)
                elif (c/"prefix"/"system.reg").exists():
                    prefixes.add(str(c/"prefix"))
                    LOG_MANAGER.add_log("DEBUG", f"Found nested prefix: {c}/prefix", "PrefixDiscovery")
        except PermissionError:
            LOG_MANAGER.add_log("WARNING", f"Permission denied scanning: {r}", "PrefixDiscovery")
        except Exception as e:
            LOG_MANAGER.add_log("WARNING", f"Error scanning {r}: {e}", "PrefixDiscovery")
    
    # Ensure default Wine prefix is included if it exists
    if (home/".wine").exists() and (home/".wine"/"system.reg").exists():
        prefixes.add(str(home/".wine"))
        LOG_MANAGER.add_log("DEBUG", f"Added default Wine prefix: {home}/.wine", "PrefixDiscovery")
    
    result = sorted(prefixes)
    LOG_MANAGER.add_log("INFO", f"Total prefixes discovered: {len(result)}", "PrefixDiscovery")
    
    return result

class ProgramScanner(QObject):
    """
    Scans Wine prefixes for Windows executable files.
    
    Provides background scanning functionality to find .exe files
    within a Wine prefix's drive_c directory structure.
    """
    scanned = Signal(list)  # Emitted with list of found executable paths
    
    def scan(self, prefix: str):
        """Start background scan of prefix for executable files."""
        threading.Thread(target=self._scan, args=(prefix,), daemon=True).start()
    
    def _scan(self, prefix: str):
        """
        Scan prefix directory for .exe files.
        
        Args:
            prefix: Path to Wine prefix to scan
        """
        p = pathlib.Path(prefix)
        
        # Determine drive_c location (varies by prefix type)
        drive = p/"drive_c" if (p/"drive_c").exists() else p/"prefix"/"drive_c"
        progs: List[str] = []
        
        if drive.exists():
            # Recursively find all .exe files
            for f in drive.rglob("*"):
                if f.suffix.lower() == ".exe" and f.is_file():
                    progs.append(str(f))
                    
        self.scanned.emit(progs)

# ================================================================================
# Main Application Window
# ================================================================================

class WineManager(QMainWindow):
    """
    Main application window providing Wine prefix management.
    
    Features:
    - Wine prefix discovery and listing
    - Proton-GE version management
    - Application launcher with favorites
    - Dark theme interface
    - Runtime selection (Wine/Proton-GE)
    """
    def __init__(self):
        """Initialize main window and setup UI components."""
        super().__init__()
        self.setWindowTitle("🍷 Wine Manager")
        self.setMinimumSize(800, 600)
        
        # Initialize core components
        self.pm = ProtonManager()
        self.scanner = ProgramScanner()
        self.releases: List[ProtonRelease] = []
        self.installed_tags: List[str] = []
        self.allApps: List[str] = []
        
        # Setup UI and load data
        self._setup_ui()
        self._apply_dark_theme()
        self._connect_signals()
        self.load_prefixes()

    def _setup_ui(self):
        """Create and configure the user interface layout."""
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setSpacing(8)
        layout.setContentsMargins(8, 8, 8, 8)
        
        # Create top toolbar with action buttons
        toolbar = QHBoxLayout()
        self.refresh_btn = QPushButton("🔄 Refresh")
        self.add_prefix_btn = QPushButton("📁 Add Dir")
        self.proton_btn = QPushButton("⚙️ Proton")
        self.logs_btn = QPushButton("📋 Logs")
        
        toolbar.addWidget(self.refresh_btn)
        toolbar.addWidget(self.add_prefix_btn)
        toolbar.addWidget(self.proton_btn)
        toolbar.addWidget(self.logs_btn)
        toolbar.addStretch()
        
        # Add statistics display
        self.stats_label = QLabel("📊 0 Prefixes")
        toolbar.addWidget(self.stats_label)
        layout.addLayout(toolbar)
        
        # Create main content area with splitter
        splitter = QSplitter(Qt.Horizontal)
        
        # Left panel: Wine prefix management
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(4, 4, 4, 4)
        
        # Prefix search functionality
        self.prefix_search = QLineEdit()
        self.prefix_search.setPlaceholderText("🔍 Search prefixes...")
        left_layout.addWidget(self.prefix_search)
        
        # Prefix list display
        self.prefix_list = QListWidget()
        self.prefix_list.setMinimumWidth(300)
        left_layout.addWidget(self.prefix_list)
        
        splitter.addWidget(left_widget)
        
        # Right panel: Runtime and launch controls
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(4, 4, 4, 4)
        
        # Runtime selection section
        runtime_group = QGroupBox("🎯 Runtime Selection")
        runtime_layout = QVBoxLayout(runtime_group)
        
        runtime_info = QLabel("Applies to all launch options below:")
        runtime_info.setStyleSheet("color: #888888; font-style: italic; margin-bottom: 4px;")
        runtime_layout.addWidget(runtime_info)
        
        self.runtime_combo = QComboBox()
        self.runtime_combo.addItem("🍷 Wine", "")
        runtime_layout.addWidget(self.runtime_combo)
        
        right_layout.addWidget(runtime_group)
        
        # Application launch options
        launch_group = QGroupBox("⚡ Launch Options")
        launch_layout = QVBoxLayout(launch_group)
        
        self.launch_exe_btn = QPushButton("📂 choose custom .exe to run...")
        launch_layout.addWidget(self.launch_exe_btn)
        
        right_layout.addWidget(launch_group)
        
        # Favorites management section
        fav_group = QGroupBox("⭐ Favorites")
        fav_layout = QVBoxLayout(fav_group)
        
        fav_info = QLabel("Uses selected runtime above")
        fav_info.setStyleSheet("color: #888888; font-style: italic; margin-bottom: 4px;")
        fav_layout.addWidget(fav_info)
        
        self.favorites_list = QListWidget()
        self.favorites_list.setMaximumHeight(200)
        fav_layout.addWidget(self.favorites_list)
        
        fav_buttons = QHBoxLayout()
        self.browse_apps_btn = QPushButton("🎮 Browse Apps")
        self.remove_fav_btn = QPushButton("🗑️ Remove")
        self.launch_fav_btn = QPushButton("🚀 Launch")
        fav_buttons.addWidget(self.browse_apps_btn)
        fav_buttons.addWidget(self.remove_fav_btn)
        fav_buttons.addWidget(self.launch_fav_btn)
        fav_layout.addLayout(fav_buttons)
        
        right_layout.addWidget(fav_group)
        right_layout.addStretch()
        
        # Configure splitter proportions
        splitter.addWidget(right_widget)
        splitter.setSizes([400, 300])
        
        layout.addWidget(splitter)
        
        # Create status bar for user feedback
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("🔗 Ready")
        
        # Initialize button states
        self._update_button_states()

    def _apply_dark_theme(self):
        """Apply modern dark theme styling to the application."""
        self.setStyleSheet("""
            QMainWindow { background: #1a1a1a; color: #ffffff; }
            QWidget { background: #1a1a1a; color: #ffffff; }
            QListWidget {
                background: #2d2d2d; border: 1px solid #404040; border-radius: 4px;
                padding: 4px; alternate-background-color: #333333;
            }
            QListWidget::item { padding: 8px; border-radius: 4px; margin: 1px; }
            QListWidget::item:selected { background: #4CAF50; color: white; }
            QListWidget::item:hover { background: #404040; }
            QTableWidget {
                background: #2d2d2d; border: 1px solid #404040; border-radius: 4px;
                gridline-color: #404040;
            }
            QTableWidget::item { padding: 8px; }
            QTableWidget::item:selected { background: #4CAF50; color: white; }
            QHeaderView::section {
                background: #333333; color: #ffffff; padding: 8px;
                border: none; font-weight: bold;
            }
            QComboBox {
                background: #2d2d2d; border: 1px solid #404040; border-radius: 4px;
                padding: 6px; color: #ffffff; min-height: 20px;
            }
            QComboBox:hover { border-color: #4CAF50; }
            QComboBox QAbstractItemView {
                background: #2d2d2d; border: 1px solid #404040;
                color: #ffffff; selection-background-color: #4CAF50;
            }
            QLineEdit {
                background: #2d2d2d; border: 1px solid #404040; border-radius: 4px;
                padding: 6px; color: #ffffff;
            }
            QLineEdit:focus { border-color: #4CAF50; }
            QPushButton {
                background: #2d2d2d; color: #ffffff; border: 1px solid #404040;
                border-radius: 4px; padding: 6px 12px; font-weight: bold;
            }
            QPushButton:hover { background: #404040; border-color: #4CAF50; }
            QPushButton:pressed { background: #4CAF50; }
            QPushButton:disabled { background: #1a1a1a; color: #666666; }
            QGroupBox {
                font-weight: bold; border: 1px solid #404040; border-radius: 4px;
                margin-top: 8px; padding-top: 8px;
            }
            QGroupBox::title {
                subcontrol-origin: margin; left: 8px; padding: 0 4px;
                background: #1a1a1a; color: #4CAF50;
            }
            QProgressBar {
                border: 1px solid #404040; border-radius: 4px; text-align: center;
                background: #2d2d2d; color: #ffffff;
            }
            QProgressBar::chunk {
                background: #4CAF50; border-radius: 3px; margin: 1px;
            }
            QStatusBar {
                background: #1e1e1e; border-top: 1px solid #404040; color: #ffffff;
            }
            QDialog { background: #1a1a1a; color: #ffffff; }
        """)

    def _connect_signals(self):
        """Connect UI element signals to their respective handler methods."""
        # Main action buttons
        self.refresh_btn.clicked.connect(self.load_prefixes)
        self.add_prefix_btn.clicked.connect(self.add_prefix_dir)
        self.proton_btn.clicked.connect(self.show_proton_manager)
        self.logs_btn.clicked.connect(self.show_logs)
        
        # Launch and favorites buttons
        self.launch_exe_btn.clicked.connect(self.launch_exe_file)
        self.browse_apps_btn.clicked.connect(self.browse_apps)
        self.remove_fav_btn.clicked.connect(self.remove_favorite)
        self.launch_fav_btn.clicked.connect(self.launch_favorite)
        
        # Interactive elements
        self.prefix_search.textChanged.connect(self._filter_prefixes)
        self.prefix_list.currentItemChanged.connect(self.on_prefix_changed)
        self.favorites_list.currentItemChanged.connect(self._update_button_states)
        self.favorites_list.itemDoubleClicked.connect(self.launch_favorite)
        
        # Proton manager signals
        self.pm.remoteReady.connect(self.on_remote_releases)
        self.pm.installedReady.connect(self.on_installed_releases)
        self.pm.downloadProgress.connect(self.on_download_progress)
        self.pm.installProgress.connect(self.on_install_progress)
        self.pm.downloadFinished.connect(self.on_download_finished)
        self.pm.uninstallFinished.connect(self.on_uninstall_finished)
        
        # Application scanner signal
        self.scanner.scanned.connect(self.on_apps_scanned)

    def _update_button_states(self):
        """Update button enabled/disabled states based on current selection."""
        has_prefix = bool(self.current_prefix())
        has_fav = bool(self.favorites_list.currentItem())
        
        self.launch_exe_btn.setEnabled(has_prefix)
        self.browse_apps_btn.setEnabled(has_prefix)
        self.remove_fav_btn.setEnabled(has_fav)
        self.launch_fav_btn.setEnabled(has_fav)

    def current_prefix(self) -> Optional[str]:
        """
        Get the currently selected Wine prefix path.
        
        Returns:
            Path to selected prefix or None if nothing selected
        """
        item = self.prefix_list.currentItem()
        if not item:
            return None
            
        text = item.text()
        # Parse prefix path from display text (remove emoji prefixes)
        if text.startswith("📁 "):
            return text[2:]
        elif text.startswith("⭐ "):
            return text.split(" ", 1)[1].split(" (")[0]
        return text

    def load_prefixes(self):
        """Discover and load Wine prefixes into the list widget."""
        LOG_MANAGER.add_log("INFO", "Scanning for Wine prefixes", "PrefixManager")
        self.prefix_list.clear()
        prefixes = discover_prefixes()
        
        # Add each prefix to the list with appropriate icon
        for prefix in prefixes:
            fav_count = len(CFG["prefix_favorites"].get(prefix, []))
            if fav_count > 0:
                item_text = f"⭐ {prefix} ({fav_count})"
            else:
                item_text = f"📁 {prefix}"
            
            item = QListWidgetItem(item_text)
            item.setToolTip(prefix)
            self.prefix_list.addItem(item)
        
        # Update UI state
        self.stats_label.setText(f"📊 {len(prefixes)} Prefixes")
        self._update_button_states()
        
        LOG_MANAGER.add_log("INFO", f"Found {len(prefixes)} Wine prefixes", "PrefixManager")
        
        # Refresh Proton installation data
        self.pm.query_installed()

    def _filter_prefixes(self):
        """Filter prefix list based on search text."""
        search_text = self.prefix_search.text().lower()
        for i in range(self.prefix_list.count()):
            item = self.prefix_list.item(i)
            item.setHidden(search_text not in item.text().lower())

    def on_prefix_changed(self):
        """Handle prefix selection change event."""
        self._update_button_states()
        self.load_favorites()

    def load_favorites(self):
        """Load and display favorite applications for the current prefix."""
        self.favorites_list.clear()
        prefix = self.current_prefix()
        if not prefix:
            return
        
        favorites = CFG["prefix_favorites"].get(prefix, [])
        for fav_path in favorites:
            app_name = pathlib.Path(fav_path).name
            item = QListWidgetItem(f"🎮 {app_name}")
            item.setToolTip(fav_path)
            item.setData(Qt.UserRole, fav_path)
            self.favorites_list.addItem(item)
        
        self._update_button_states()

    def add_prefix_dir(self):
        """Add a new directory to search for Wine prefixes."""
        global CFG  # Declare global at the beginning of the function
        
        directory = QFileDialog.getExistingDirectory(self, "Select Directory to Search for Wine Prefixes")
        if not directory:
            return
            
        # Check if directory is already in the search list
        if directory in CFG["extra_prefix_dirs"]:
            QMessageBox.information(self, "ℹ️ Already Added", f"Directory is already in search list:\n{directory}")
            # Still refresh the prefix list in case new prefixes were added to this directory
            self.load_prefixes()
            return
            
        # Count how many prefixes were found before adding this directory
        old_prefixes = set(discover_prefixes())
        
        # Add directory to search paths and update global config
        CFG["extra_prefix_dirs"].append(directory)
        save_cfg(CFG)
        
        # Reload global configuration to ensure discover_prefixes uses updated config
        CFG = load_cfg()
        
        # Count how many prefixes are found after adding the directory
        new_prefixes = set(discover_prefixes())
        found_count = len(new_prefixes) - len(old_prefixes)
        
        LOG_MANAGER.add_log("INFO", f"Added search directory: {directory} (found {found_count} new prefixes)", "PrefixManager")
        
        if found_count > 0:
            QMessageBox.information(self, "✅ Directory Added", 
                f"Added search directory:\n{directory}\n\nFound {found_count} new Wine prefix(es).")
        else:
            QMessageBox.information(self, "✅ Directory Added", 
                f"Added search directory:\n{directory}\n\nNo Wine prefixes found in this directory.")
        
        self.load_prefixes()

    def show_proton_manager(self):
        """Open the Proton version management dialog."""
        LOG_MANAGER.add_log("INFO", "Opening Proton manager", "UI")
        dialog = ProtonManagerDialog(self.pm, self.releases, self.installed_tags, self)
        dialog.exec()

    def show_logs(self):
        """Open the application logs dialog."""
        LOG_MANAGER.add_log("INFO", "Opening logs viewer", "UI")
        dialog = LogsDialog(self)
        dialog.exec()

    def launch_exe_file(self):
        """Launch a custom Windows executable file through file browser."""
        prefix = self.current_prefix()
        if not prefix:
            return
        
        LOG_MANAGER.add_log("INFO", f"Opening file browser for prefix {prefix}", "UI")
        
        # Start file dialog in prefix's drive_c directory
        start_dir = str(pathlib.Path(prefix) / "drive_c")
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select EXE", start_dir, "Executable Files (*.exe)"
        )
        
        if file_path:
            LOG_MANAGER.add_log("INFO", f"Selected executable: {file_path}", "UI")
            runtime = self.runtime_combo.currentData()
            self._launch_path(prefix, file_path, runtime)

    def browse_apps(self):
        """Browse and select applications installed in the current prefix."""
        prefix = self.current_prefix()
        if not prefix:
            return
        
        LOG_MANAGER.add_log("INFO", f"Browsing applications in prefix {prefix}", "UI")
        
        dialog = AppsDialog(prefix, self.scanner, self.installed_tags, self)
        if dialog.exec() == QDialog.Accepted and dialog.selected_app:
            # Add selected app to favorites automatically
            favorites = CFG["prefix_favorites"].setdefault(prefix, [])
            if dialog.selected_app not in favorites:
                favorites.append(dialog.selected_app)
                save_cfg(CFG)
                self.load_favorites()
                self.load_prefixes()  # Refresh star indicator
                LOG_MANAGER.add_log("INFO", f"Added {dialog.selected_app} to favorites", "Favorites")

    def remove_favorite(self):
        """Remove the selected application from favorites list."""
        item = self.favorites_list.currentItem()
        prefix = self.current_prefix()
        if not (item and prefix):
            return
        
        app_path = item.data(Qt.UserRole)
        favorites = CFG["prefix_favorites"].get(prefix, [])
        if app_path in favorites:
            favorites.remove(app_path)
            save_cfg(CFG)
            self.load_favorites()
            self.load_prefixes()  # Refresh star indicator

    def launch_favorite(self):
        """Launch the selected favorite application."""
        item = self.favorites_list.currentItem()
        prefix = self.current_prefix()
        if not (item and prefix):
            return
        
        app_path = item.data(Qt.UserRole)
        runtime = self.runtime_combo.currentData()
        self._launch_path(prefix, app_path, runtime)

    def _launch_path(self, prefix: str, exe_path: str, runtime_tag: Optional[str]):
        """
        Launch a Windows executable using the specified runtime.
        
        Args:
            prefix: Wine prefix path
            exe_path: Path to executable file
            runtime_tag: Proton version tag (None for Wine)
        """
        if not prefix or not exe_path:
            QMessageBox.critical(self, "❌ Error", "Invalid prefix or executable path.")
            return
        
        app_name = pathlib.Path(exe_path).name
        self.status_bar.showMessage(f"🚀 Launching {app_name}...")
        LOG_MANAGER.add_log("INFO", f"Launching {app_name} in prefix {prefix}", "Launcher")
        
        # Setup environment variables
        env = os.environ.copy()
        env["WINEPREFIX"] = prefix
        
        try:
            if runtime_tag:
                # Launch with Proton-GE
                proton_exe = self.pm.proton_executable(runtime_tag)
                if not proton_exe:
                    error_msg = f"Proton {runtime_tag} not found"
                    LOG_MANAGER.add_log("ERROR", error_msg, "Launcher")
                    QMessageBox.critical(self, "❌ Error", error_msg)
                    return
                
                # Add required Steam environment variables for Proton
                env["STEAM_COMPAT_DATA_PATH"] = prefix
                env["STEAM_COMPAT_CLIENT_INSTALL_PATH"] = "/usr"  # Fallback Steam path
                
                command = [str(proton_exe), "run", exe_path]
                runtime_display = f"Proton {runtime_tag}"
                LOG_MANAGER.add_log("INFO", f"Using Proton-GE {runtime_tag}: {' '.join(command)}", "Launcher")
            else:
                # Launch with standard Wine
                command = ["wine", "start", "/unix", exe_path]
                runtime_display = "Wine"
                LOG_MANAGER.add_log("INFO", f"Using Wine: {' '.join(command)}", "Launcher")
            
            # Start the process and capture output
            process = subprocess.Popen(
                command, 
                env=env, 
                stdout=subprocess.PIPE, 
                stderr=subprocess.PIPE,
                text=True
            )
            
            # Log process start
            LOG_MANAGER.add_log("INFO", f"Started process PID {process.pid}", "Launcher")
            self.status_bar.showMessage(f"✅ Launched {app_name} with {runtime_display}")
            
            # Start background thread to capture output
            threading.Thread(
                target=self._capture_process_output, 
                args=(process, app_name, runtime_display), 
                daemon=True
            ).start()
            
        except Exception as e:
            error_msg = f"Failed to launch {app_name}: {str(e)}"
            LOG_MANAGER.add_log("ERROR", error_msg, "Launcher")
            QMessageBox.critical(self, "❌ Launch Error", error_msg)
            self.status_bar.showMessage("❌ Launch failed")

    def _capture_process_output(self, process: subprocess.Popen, app_name: str, runtime: str):
        """
        Capture and log output from launched process.
        
        Args:
            process: The subprocess to monitor
            app_name: Name of the application
            runtime: Runtime used (Wine/Proton)
        """
        try:
            # Wait for process and capture output
            stdout, stderr = process.communicate(timeout=30)  # 30 second timeout for initial output
            
            if stdout.strip():
                LOG_MANAGER.add_log("INFO", f"{app_name} stdout: {stdout.strip()}", f"{runtime}")
            
            if stderr.strip():
                # Log stderr as warning unless it contains critical errors
                log_level = "ERROR" if any(keyword in stderr.lower() for keyword in ["error", "failed", "exception"]) else "WARNING"
                LOG_MANAGER.add_log(log_level, f"{app_name} stderr: {stderr.strip()}", f"{runtime}")
                
        except subprocess.TimeoutExpired:
            # Process is still running, that's normal for GUI apps
            LOG_MANAGER.add_log("INFO", f"{app_name} is running in background", f"{runtime}")
        except Exception as e:
            LOG_MANAGER.add_log("WARNING", f"Could not capture output from {app_name}: {str(e)}", f"{runtime}")

    # ============================================================================
    # Proton Manager Signal Handlers
    # ============================================================================
    
    def on_remote_releases(self, releases):
        """Handle remote Proton releases being loaded."""
        self.releases = releases

    def on_installed_releases(self, tags):
        """Handle installed Proton versions being updated."""
        self.installed_tags = tags
        
        # Update runtime selection combo box
        current = self.runtime_combo.currentData()
        self.runtime_combo.clear()
        self.runtime_combo.addItem("🍷 Wine", "")
        
        for tag in tags:
            self.runtime_combo.addItem(f"⚙️ {tag}", tag)
        
        # Restore previous selection if still available
        index = self.runtime_combo.findData(current)
        self.runtime_combo.setCurrentIndex(index if index >= 0 else 0)

    def on_download_progress(self, tag, done, total):
        """Handle Proton download progress updates."""
        if total > 0:
            percent = int((done / total) * 100)
            self.status_bar.showMessage(f"⬇️ Downloading {tag}: {percent}%")

    def on_install_progress(self, tag, status_message):
        """Handle Proton installation progress updates."""
        self.status_bar.showMessage(f"⚙️ Installing {tag}: {status_message}")

    def on_download_finished(self, tag, success, message):
        """Handle Proton download completion."""
        if success:
            QMessageBox.information(self, "✅ Success", f"Installed Proton {tag}")
        else:
            QMessageBox.critical(self, "❌ Error", f"Failed to install {tag}\n{message}")
        self.pm.query_installed()
        self.status_bar.showMessage("🔗 Ready")

    def on_uninstall_finished(self, tag, success, message):
        """Handle Proton uninstall completion."""
        if success:
            QMessageBox.information(self, "✅ Success", f"Removed Proton {tag}")
        else:
            QMessageBox.critical(self, "❌ Error", f"Failed to remove {tag}\n{message}")
        self.pm.query_installed()

    def on_apps_scanned(self, apps):
        """Handle application scan completion."""
        self.allApps = apps

# ================================================================================
# Dialog Classes
# ================================================================================

class ProtonManagerDialog(QDialog):
    """
    Dialog for managing Proton-GE installations.
    
    Provides interface to:
    - View available Proton-GE releases
    - Download and install new versions
    - Remove installed versions
    - Track installation progress
    """
    def __init__(self, pm: ProtonManager, releases: List[ProtonRelease], installed: List[str], parent=None):
        """
        Initialize Proton manager dialog.
        
        Args:
            pm: ProtonManager instance
            releases: List of available releases
            installed: List of installed version tags
            parent: Parent widget
        """
        super().__init__(parent)
        self.pm = pm
        self.releases = releases
        self.installed = set(installed)
        
        self.setWindowTitle("⚙️ Proton Manager")
        self.setMinimumSize(800, 500)
        
        layout = QVBoxLayout(self)
        
        # Create header with refresh button
        header = QHBoxLayout()
        header.addWidget(QLabel("📦 Proton-GE Releases"))
        header.addStretch()
        refresh_btn = QPushButton("🔄 Refresh")
        refresh_btn.clicked.connect(lambda: (pm.query_remote(), pm.query_installed()))
        header.addWidget(refresh_btn)
        layout.addLayout(header)
        
        # Progress bar for downloads
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        layout.addWidget(self.progress)
        
        # Setup releases table
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Tag", "Name", "Date", "Action"])
        
        # Configure table column behavior
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)  # Tag column
        header.setSectionResizeMode(1, QHeaderView.Stretch)         # Name column (stretches)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)  # Date column
        header.setSectionResizeMode(3, QHeaderView.Fixed)           # Action column
        self.table.setColumnWidth(3, 180)  # Fixed width for action buttons
        
        # Configure table appearance
        self.table.setWordWrap(True)
        self.table.setAlternatingRowColors(True)
        
        layout.addWidget(self.table)
        
        # Connect ProtonManager signals
        pm.remoteReady.connect(self.populate_table)
        pm.installedReady.connect(self.update_installed)
        pm.downloadProgress.connect(self.show_progress)
        pm.installProgress.connect(self.show_install_progress)
        pm.downloadFinished.connect(self.hide_progress)
        pm.uninstallFinished.connect(self.hide_progress)
        
        # Initialize data
        pm.query_remote()
        pm.query_installed()

    def populate_table(self, releases):
        """Populate table with available releases."""
        self.releases = releases
        self.update_table()

    def update_installed(self, installed):
        """Update list of installed versions."""
        self.installed = set(installed)
        self.update_table()

    def update_table(self):
        """Update the releases table with current data."""
        self.table.setRowCount(len(self.releases))
        
        for i, release in enumerate(self.releases):
            # Tag column
            tag_item = QTableWidgetItem(release.tag)
            tag_item.setToolTip(release.tag)
            self.table.setItem(i, 0, tag_item)
            
            # Name column with tooltip for long names
            name_item = QTableWidgetItem(release.name)
            name_item.setToolTip(release.name)
            self.table.setItem(i, 1, name_item)
            
            # Date column
            date_item = QTableWidgetItem(release.published.strftime("%Y-%m-%d"))
            date_item.setToolTip(release.published.strftime("%Y-%m-%d %H:%M"))
            self.table.setItem(i, 2, date_item)
            
            # Action button (install/remove)
            is_installed = release.tag in self.installed
            if is_installed:
                btn = QPushButton("🗑️ Remove")
                btn.setToolTip(f"Uninstall {release.tag}")
                btn.clicked.connect(lambda checked, tag=release.tag: self.pm.uninstall(tag))
            else:
                btn = QPushButton("⬇️ Install")
                btn.setToolTip(f"Install {release.tag}")
                btn.clicked.connect(lambda checked, tag=release.tag: self.pm.install(tag))
            
            btn.setMinimumWidth(160)
            btn.setFixedHeight(30)
            self.table.setCellWidget(i, 3, btn)
        
        # Auto-resize rows to fit content
        self.table.resizeRowsToContents()

    def show_progress(self, tag, done, total):
        """Show download progress."""
        if total > 0:
            self.progress.setVisible(True)
            self.progress.setValue(int((done / total) * 100))

    def show_install_progress(self, tag, status_message):
        """Show installation progress."""
        self.progress.setVisible(True)
        self.progress.setValue(100)  # Keep at 100% but show different message
        # You could add a status label here if needed

    def hide_progress(self, *args):
        """Hide progress bar."""
        self.progress.setVisible(False)

class AppsDialog(QDialog):
    """
    Dialog for browsing and selecting applications within a Wine prefix.
    
    Features:
    - Scans prefix for Windows executables
    - Provides search and filtering capabilities
    - Allows launching apps or adding them to favorites
    - Filters out system files by default
    """
    def __init__(self, prefix: str, scanner: ProgramScanner, installed_tags: List[str], parent=None):
        """
        Initialize applications browser dialog.
        
        Args:
            prefix: Wine prefix path to scan
            scanner: ProgramScanner instance
            installed_tags: List of installed Proton tags (unused in current version)
            parent: Parent widget
        """
        super().__init__(parent)
        self.prefix = prefix
        self.scanner = scanner
        self.selected_app = None
        
        self.setWindowTitle("🎮 Applications")
        self.setMinimumSize(500, 400)
        
        layout = QVBoxLayout(self)
        
        # Header showing current prefix
        layout.addWidget(QLabel(f"Applications in: {pathlib.Path(prefix).name}"))
        
        # Search and filter controls
        filter_layout = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("🔍 Search...")
        self.hide_system = QCheckBox("Hide system files")
        self.hide_system.setChecked(True)
        
        filter_layout.addWidget(self.search)
        filter_layout.addWidget(self.hide_system)
        layout.addLayout(filter_layout)
        
        # Applications list
        self.apps_list = QListWidget()
        layout.addWidget(self.apps_list)
        
        # Action buttons
        buttons = QHBoxLayout()
        buttons.addStretch()
        add_fav_btn = QPushButton("⭐ Add to Favorites")
        launch_btn = QPushButton("🚀 Launch")
        close_btn = QPushButton("❌ Close")
        
        buttons.addWidget(add_fav_btn)
        buttons.addWidget(launch_btn)
        buttons.addWidget(close_btn)
        layout.addLayout(buttons)
        
        # Connect signals
        self.search.textChanged.connect(self.filter_apps)
        self.hide_system.stateChanged.connect(self.filter_apps)
        add_fav_btn.clicked.connect(self.add_favorite)
        launch_btn.clicked.connect(self.launch_app)
        close_btn.clicked.connect(self.reject)
        self.apps_list.itemDoubleClicked.connect(self.launch_app)
        
        # Connect scanner signal
        scanner.scanned.connect(self.populate_apps)
        
        # Start scanning
        self.apps_list.addItem("🔍 Scanning...")
        scanner.scan(prefix)

    def populate_apps(self, apps):
        """Populate list with discovered applications."""
        self.all_apps = apps
        self.filter_apps()

    def filter_apps(self):
        """Filter application list based on search text and system file setting."""
        search_text = self.search.text().lower()
        hide_sys = self.hide_system.isChecked()
        
        self.apps_list.clear()
        
        for app_path in self.all_apps:
            path_lower = app_path.lower()
            
            # Skip Windows system files if filter is enabled
            if hide_sys and ("\\windows\\" in path_lower or "/windows/" in path_lower):
                continue
            
            # Skip apps that don't match search text
            if search_text and search_text not in path_lower:
                continue
            
            # Add app to filtered list
            app_name = pathlib.Path(app_path).name
            item = QListWidgetItem(f"🎮 {app_name}")
            item.setToolTip(app_path)
            item.setData(Qt.UserRole, app_path)
            self.apps_list.addItem(item)

    def add_favorite(self):
        """Add selected application to favorites and close dialog."""
        item = self.apps_list.currentItem()
        if item:
            self.selected_app = item.data(Qt.UserRole)
            self.accept()

    def launch_app(self):
        """Launch selected application directly with Wine."""
        item = self.apps_list.currentItem()
        if item:
            app_path = item.data(Qt.UserRole)
            
            # Setup Wine environment and launch
            env = os.environ.copy()
            env["WINEPREFIX"] = self.prefix
            
            try:
                subprocess.Popen(["wine", "start", "/unix", app_path], env=env)
                QMessageBox.information(self, "✅ Success", f"Launched {pathlib.Path(app_path).name}")
            except Exception as e:
                error_msg = f"Launch failed: {str(e)}"
                LOG_MANAGER.add_log("ERROR", error_msg, "AppsDialog")
                QMessageBox.critical(self, "❌ Error", error_msg)

class LogsDialog(QDialog):
    """
    Dialog for viewing application logs and debugging information.
    
    Features:
    - Real-time log updates
    - Log level filtering
    - Copy and export functionality
    - Clear logs option
    """
    
    def __init__(self, parent=None):
        """Initialize logs viewer dialog."""
        super().__init__(parent)
        self.setWindowTitle("📋 Application Logs")
        self.setMinimumSize(800, 600)
        
        layout = QVBoxLayout(self)
        
        # Header with controls
        header = QHBoxLayout()
        header.addWidget(QLabel("📋 Application Logs & Debug Information"))
        header.addStretch()
        
        # Log level filter
        self.level_filter = QComboBox()
        self.level_filter.addItems(["All", "INFO", "WARNING", "ERROR", "DEBUG"])
        self.level_filter.currentTextChanged.connect(self.filter_logs)
        header.addWidget(QLabel("Filter:"))
        header.addWidget(self.level_filter)
        
        # Control buttons
        clear_btn = QPushButton("🗑️ Clear")
        copy_btn = QPushButton("📋 Copy All")
        export_btn = QPushButton("💾 Export")
        refresh_btn = QPushButton("🔄 Refresh")
        
        clear_btn.clicked.connect(self.clear_logs)
        copy_btn.clicked.connect(self.copy_logs)
        export_btn.clicked.connect(self.export_logs)
        refresh_btn.clicked.connect(self.refresh_logs)
        
        header.addWidget(clear_btn)
        header.addWidget(copy_btn)
        header.addWidget(export_btn)
        header.addWidget(refresh_btn)
        
        layout.addLayout(header)
        
        # Search box
        search_layout = QHBoxLayout()
        search_layout.addWidget(QLabel("🔍 Search:"))
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Search logs...")
        self.search_box.textChanged.connect(self.filter_logs)
        search_layout.addWidget(self.search_box)
        layout.addLayout(search_layout)
        
        # Logs display
        self.logs_text = QTextEdit()
        self.logs_text.setReadOnly(True)
        self.logs_text.setFont(QFont("Consolas, monospace", 9))
        layout.addWidget(self.logs_text)
        
        # Statistics
        self.stats_label = QLabel("📊 0 log entries")
        layout.addWidget(self.stats_label)
        
        # Close button
        close_layout = QHBoxLayout()
        close_layout.addStretch()
        close_btn = QPushButton("❌ Close")
        close_btn.clicked.connect(self.accept)
        close_layout.addWidget(close_btn)
        layout.addLayout(close_layout)
        
        # Connect to log manager
        LOG_MANAGER.logUpdated.connect(self.on_log_updated)
        
        # Initial load
        self.refresh_logs()
    
    def refresh_logs(self):
        """Refresh the logs display."""
        self.filter_logs()
    
    def filter_logs(self):
        """Filter logs based on level and search text."""
        level_filter = self.level_filter.currentText()
        search_text = self.search_box.text().lower()
        
        all_logs = LOG_MANAGER.logs
        filtered_logs = []
        
        for log_entry in all_logs:
            # Level filtering
            if level_filter != "All" and f"[{level_filter}]" not in log_entry:
                continue
            
            # Search filtering
            if search_text and search_text not in log_entry.lower():
                continue
            
            filtered_logs.append(log_entry)
        
        # Update display
        self.logs_text.clear()
        
        for log_entry in filtered_logs:
            # Color code by log level
            if "[ERROR]" in log_entry:
                self.logs_text.append(f'<span style="color: #ff6b6b;">{log_entry}</span>')
            elif "[WARNING]" in log_entry:
                self.logs_text.append(f'<span style="color: #ffd93d;">{log_entry}</span>')
            elif "[INFO]" in log_entry:
                self.logs_text.append(f'<span style="color: #6bcf7f;">{log_entry}</span>')
            else:
                self.logs_text.append(f'<span style="color: #ffffff;">{log_entry}</span>')
        
        # Auto-scroll to bottom
        cursor = self.logs_text.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.logs_text.setTextCursor(cursor)
        
        # Update statistics
        self.stats_label.setText(f"📊 {len(filtered_logs)} log entries (of {len(all_logs)} total)")
    
    def on_log_updated(self, log_entry: str):
        """Handle new log entry."""
        # Only update if the new entry matches current filters
        level_filter = self.level_filter.currentText()
        search_text = self.search_box.text().lower()
        
        should_show = True
        
        if level_filter != "All" and f"[{level_filter}]" not in log_entry:
            should_show = False
        
        if search_text and search_text not in log_entry.lower():
            should_show = False
        
        if should_show:
            # Add new entry with color coding
            if "[ERROR]" in log_entry:
                self.logs_text.append(f'<span style="color: #ff6b6b;">{log_entry}</span>')
            elif "[WARNING]" in log_entry:
                self.logs_text.append(f'<span style="color: #ffd93d;">{log_entry}</span>')
            elif "[INFO]" in log_entry:
                self.logs_text.append(f'<span style="color: #6bcf7f;">{log_entry}</span>')
            else:
                self.logs_text.append(f'<span style="color: #ffffff;">{log_entry}</span>')
            
            # Auto-scroll to bottom
            cursor = self.logs_text.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.End)
            self.logs_text.setTextCursor(cursor)
        
        # Update statistics regardless
        filtered_count = len([log for log in LOG_MANAGER.logs 
                            if (level_filter == "All" or f"[{level_filter}]" in log)
                            and (not search_text or search_text in log.lower())])
        self.stats_label.setText(f"📊 {filtered_count} log entries (of {len(LOG_MANAGER.logs)} total)")
    
    def clear_logs(self):
        """Clear all logs after confirmation."""
        reply = QMessageBox.question(
            self, "Clear Logs", 
            "Are you sure you want to clear all logs?",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            LOG_MANAGER.clear_logs()
            self.logs_text.clear()
            self.stats_label.setText("📊 0 log entries")
    
    def copy_logs(self):#!/usr/bin/env python3
"""
Wine Manager

A modern GUI application for managing Wine prefixes and Proton-GE installations.

Features:
- Automatic Wine prefix discovery and management
- Proton-GE version management with automated downloads
- Dark theme interface optimized for productivity
- Favorites system for quick application access
- Cross-runtime support (Wine/Proton-GE)
- Application browser with system file filtering

Author: ZeloteZ
License: MIT
"""
# Standard library imports
import sys, os, threading, pathlib, tempfile, tarfile, shutil, json, subprocess
from datetime import datetime
from dataclasses import dataclass
from typing import List, Optional

# Third-party imports
import requests
from PySide6.QtWidgets import *
from PySide6.QtCore import Qt, Signal, QObject, QTimer
from PySide6.QtGui import QFont, QAction, QTextCursor

# ================================================================================
# Configuration Management
# ================================================================================

# Application configuration paths
CONFIG_DIR = pathlib.Path.home() / ".config" / "wine-manager"
CONFIG_FILE = CONFIG_DIR / "settings.json"

# Default configuration template#!/usr/bin/env python3
"""
Wine Manager

A modern GUI application for managing Wine prefixes and Proton-GE installations.

Features:
- Automatic Wine prefix discovery and management
- Proton-GE version management with automated downloads
- Dark theme interface optimized for productivity
- Favorites system for quick application access
- Cross-runtime support (Wine/Proton-GE)
- Application browser with system file filtering

Author: ZeloteZ
License: MIT
"""
# Standard library imports
import sys, os, threading, pathlib, tempfile, tarfile, shutil, json, subprocess
from datetime import datetime
from dataclasses import dataclass
from typing import List, Optional

# Third-party imports
import requests
from PySide6.QtWidgets import *
from PySide6.QtCore import Qt, Signal, QObject, QTimer
from PySide6.QtGui import QFont, QAction, QTextCursor

# ================================================================================
# Configuration Management
# ================================================================================

# Application configuration paths
CONFIG_DIR = pathlib.Path.home() / ".config" / "wine-manager"
CONFIG_FILE = CONFIG_DIR / "settings.json"

# Default configuration template
DEFAULT_CFG = {
    "proton_dir": "~/.local/share/proton-builds",  # Proton installation directory
    "default_proton": "",                          # Default Proton version
    "prefix_proton_map": {},                       # Prefix -> Proton version mapping
    "extra_prefix_dirs": [],                       # Additional prefix search directories
    "prefix_favorites": {}                         # Prefix -> favorite apps mapping
}

def load_cfg() -> dict:
    """
    Load application configuration from file.
    Creates default config if file doesn't exist.
    
    Returns:
        dict: Configuration dictionary with expanded paths
    """
    if not CONFIG_FILE.exists():
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(json.dumps(DEFAULT_CFG, indent=2))
    
    data = json.loads(CONFIG_FILE.read_text()) if CONFIG_FILE.exists() else {}
    cfg = DEFAULT_CFG.copy()
    cfg.update(data)
    
    # Expand user paths
    cfg["proton_dir"] = str(pathlib.Path(os.path.expanduser(cfg["proton_dir"])))
    cfg["extra_prefix_dirs"] = [str(pathlib.Path(os.path.expanduser(p))) for p in cfg.get("extra_prefix_dirs", [])]
    cfg["prefix_favorites"] = {k: list(v) for k, v in cfg.get("prefix_favorites", {}).items()}
    
    return cfg

def save_cfg(cfg: dict):
    """
    Save configuration to file.
    
    Args:
        cfg: Configuration dictionary to save

DEFAULT_CFG = {
    "proton_dir": "~/.local/share/proton-builds",  # Proton installation directory
    "default_proton": "",                          # Default Proton version
    "prefix_proton_map": {},                       # Prefix -> Proton version mapping
    "extra_prefix_dirs": [],                       # Additional prefix search directories
    "prefix_favorites": {}                         # Prefix -> favorite apps mapping
}

def load_cfg() -> dict:
    """
    Load application configuration from file.
    Creates default config if file doesn't exist.
    
    Returns:
        dict: Configuration dictionary with expanded paths
    """
    if not CONFIG_FILE.exists():
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(json.dumps(DEFAULT_CFG, indent=2))
    
    data = json.loads(CONFIG_FILE.read_text()) if CONFIG_FILE.exists() else {}
    cfg = DEFAULT_CFG.copy()
    cfg.update(data)
    
    # Expand user paths
    cfg["proton_dir"] = str(pathlib.Path(os.path.expanduser(cfg["proton_dir"])))
    cfg["extra_prefix_dirs"] = [str(pathlib.Path(os.path.expanduser(p))) for p in cfg.get("extra_prefix_dirs", [])]
    cfg["prefix_favorites"] = {k: list(v) for k, v in cfg.get("prefix_favorites", {}).items()}
    
    return cfg

def save_cfg(cfg: dict):
    """
    Save configuration to file.
    
    Args:
        cfg: Configuration dictionary to save

        """Copy all visible logs to clipboard."""
        clipboard = QApplication.clipboard()
        clipboard.setText(self.logs_text.toPlainText())
        QMessageBox.information(self, "📋 Copied", "Logs copied to clipboard!")
    
    def export_logs(self):
        """Export logs to a file."""
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Export Logs", 
            f"wine_manager_logs_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt",
            "Text Files (*.txt);;All Files (*)"
        )
        
        if file_path:
            try:
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write("Wine Manager - Application Logs\n")
                    f.write("=" * 50 + "\n")
                    f.write(f"Exported: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                    f.write("=" * 50 + "\n\n")
                    f.write(LOG_MANAGER.get_all_logs())
                
                QMessageBox.information(self, "💾 Exported", f"Logs exported to:\n{file_path}")
                LOG_MANAGER.add_log("INFO", f"Logs exported to {file_path}", "LogsDialog")
                
            except Exception as e:
                error_msg = f"Failed to export logs: {str(e)}"
                LOG_MANAGER.add_log("ERROR", error_msg, "LogsDialog")
                QMessageBox.critical(self, "❌ Export Error", error_msg)

# ================================================================================
# Application Entry Point
# ================================================================================

if __name__ == "__main__":
    """Main application entry point."""
    app = QApplication(sys.argv)
    app.setApplicationName("Wine Manager")
    
    # Initialize logging
    LOG_MANAGER.add_log("INFO", "Starting Wine Manager", "System")
    LOG_MANAGER.add_log("INFO", f"Python version: {sys.version}", "System")
    LOG_MANAGER.add_log("INFO", f"PySide6 version: {app.applicationVersion()}", "System")
    
    # Create and show main window
    window = WineManager()
    window.show()
    
    LOG_MANAGER.add_log("INFO", "Main window created and displayed", "System")
    
    # Center window on screen
    screen = app.primaryScreen().geometry()
    window.move(
        (screen.width() - window.width()) // 2,
        (screen.height() - window.height()) // 2
    )
    
    LOG_MANAGER.add_log("INFO", "Application startup complete", "System")
    
    # Start application event loop
    try:
        sys.exit(app.exec())
    except KeyboardInterrupt:
        LOG_MANAGER.add_log("INFO", "Application terminated by user", "System")
    except Exception as e:
        LOG_MANAGER.add_log("ERROR", f"Application crashed: {str(e)}", "System")
        raise
