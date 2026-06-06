from __future__ import annotations

import json
import os
import hashlib
import pathlib
import shlex
import shutil
import subprocess
import tarfile
import tempfile
import threading
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import requests
from PySide6.QtCore import QObject, QTimer, Signal


CONFIG_DIR = pathlib.Path.home() / ".config" / "wine-manager"
CONFIG_FILE = CONFIG_DIR / "settings.json"
POSTER_CACHE_DIR = CONFIG_DIR / "posters"
POSTER_INDEX_FILE = CONFIG_DIR / "poster-cache.json"
GITHUB_API = "https://api.github.com/repos/GloriousEggroll/proton-ge-custom/releases"
STEAM_STORE_SEARCH_API = "https://store.steampowered.com/api/storesearch"
STEAM_APPDETAILS_API = "https://store.steampowered.com/api/appdetails"
WIKIMEDIA_COMMONS_API = "https://commons.wikimedia.org/w/api.php"
POSTER_PROVIDER = "wikimedia-commons-v1"
POSTER_QUERY_INTERVAL_SECONDS = 0.5
POSTER_RATE_LIMIT_COOLDOWN_SECONDS = 30.0
POSTER_MIN_SCORE = 8
SYSTEM_POSTER_NAMES = {
    "arp",
    "attrib",
    "ceflauncher",
    "certutil",
    "cmd",
    "conhost",
    "control",
    "cscript",
    "dxdiag",
    "expand",
    "find",
    "hostname",
    "iexplore",
    "msbuild",
    "msiexec",
    "net",
    "netsh",
    "notepad",
    "ping",
    "powershell",
    "reg",
    "regedit",
    "regsvr32",
    "rundll32",
    "schtasks",
    "services",
    "svchost",
    "taskkill",
    "taskmgr",
    "uninstall",
    "uninstaller",
    "where",
    "whoami",
    "winemenubuilder",
    "winemine",
    "wordpad",
    "wow64 helper",
    "wscript",
    "write",
    "wuauserv",
    "wusa",
    "wsdl",
    "xbuild",
    "xcopy",
    "xsd",
}
REQUEST_HEADERS = {
    "Accept": "application/vnd.github+json",
    "User-Agent": "wine-manager/2.0",
}


def _safe_emit(signal, *args) -> None:
    try:
        signal.emit(*args)
    except RuntimeError:
        pass


def _coerce_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int | float):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return False


def _coerce_positive_int(value: object) -> int:
    try:
        return max(0, int(value or 0))
    except Exception:
        return 0


def _normalize_gamescope_settings(raw: object) -> dict:
    source = raw if isinstance(raw, dict) else {}
    return {
        "enabled": _coerce_bool(source.get("enabled", False)),
        "width": _coerce_positive_int(source.get("width", 0)),
        "height": _coerce_positive_int(source.get("height", 0)),
        "refresh_rate": _coerce_positive_int(source.get("refresh_rate", 0)),
        "fullscreen": _coerce_bool(source.get("fullscreen", False)),
        "borderless": _coerce_bool(source.get("borderless", False)),
        "extra_args": str(source.get("extra_args", "")).strip(),
    }


def _default_config() -> dict:
    return {
        "proton_dir": str(pathlib.Path.home() / ".local/share/proton-builds"),
        "default_proton": "",
        "proton_launch_backend": "umu",
        "umu_executable": "umu-run",
        "gamescope_defaults": _normalize_gamescope_settings({}),
        "prefix_proton_map": {},
        "prefix_gamescope_map": {},
        "app_proton_map": {},
        "app_gamescope_map": {},
        "app_art_map": {},
        "app_art_zoom_map": {},
        "extra_prefix_dirs": [],
        "prefix_hidden_apps": {},
        "prefix_manual_apps": {},
        "prefix_favorites": {},
    }


@dataclass(slots=True)
class GamescopeSettings:
    enabled: bool = False
    width: int = 0
    height: int = 0
    refresh_rate: int = 0
    fullscreen: bool = False
    borderless: bool = False
    extra_args: str = ""

    @classmethod
    def from_raw(cls, raw: object) -> GamescopeSettings:
        return cls(**_normalize_gamescope_settings(raw))

    def to_config(self) -> dict:
        return {
            "enabled": self.enabled,
            "width": max(0, int(self.width)),
            "height": max(0, int(self.height)),
            "refresh_rate": max(0, int(self.refresh_rate)),
            "fullscreen": bool(self.fullscreen),
            "borderless": bool(self.borderless),
            "extra_args": self.extra_args.strip(),
        }

    def command_prefix(self, executable: str = "gamescope") -> list[str]:
        if not self.enabled:
            return []

        command = [executable]
        if self.width > 0:
            command.extend(["-W", str(self.width)])
        if self.height > 0:
            command.extend(["-H", str(self.height)])
        if self.refresh_rate > 0:
            command.extend(["-r", str(self.refresh_rate)])
        if self.fullscreen:
            command.append("-f")
        if self.borderless:
            command.append("-b")
        if self.extra_args:
            try:
                command.extend(shlex.split(self.extra_args))
            except ValueError as error:
                raise RuntimeError(f"Invalid gamescope arguments: {error}") from error
        command.append("--")
        return command


class ConfigStore:
    def __init__(self):
        self.data = self._load()

    def _load(self) -> dict:
        if not CONFIG_FILE.exists():
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            CONFIG_FILE.write_text(json.dumps(_default_config(), indent=2), encoding="utf-8")

        try:
            raw = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            raw = {}

        config = _default_config()
        config.update(raw)
        config["proton_dir"] = str(pathlib.Path(os.path.expanduser(config["proton_dir"])))
        config["proton_launch_backend"] = "direct" if str(config.get("proton_launch_backend", "umu")).strip().lower() == "direct" else "umu"
        config["umu_executable"] = str(config.get("umu_executable") or "umu-run").strip() or "umu-run"
        config["gamescope_defaults"] = _normalize_gamescope_settings(config.get("gamescope_defaults", {}))
        config["extra_prefix_dirs"] = [
            str(pathlib.Path(os.path.expanduser(path))) for path in config.get("extra_prefix_dirs", [])
        ]
        config["prefix_hidden_apps"] = {
            prefix: list(paths) for prefix, paths in config.get("prefix_hidden_apps", {}).items()
        }
        config["prefix_manual_apps"] = {
            prefix: list(paths) for prefix, paths in config.get("prefix_manual_apps", {}).items()
        }
        config["prefix_favorites"] = {
            prefix: list(paths) for prefix, paths in config.get("prefix_favorites", {}).items()
        }
        config["prefix_proton_map"] = {
            prefix: runtime for prefix, runtime in config.get("prefix_proton_map", {}).items()
        }
        config["prefix_gamescope_map"] = {
            prefix: _normalize_gamescope_settings(settings)
            for prefix, settings in config.get("prefix_gamescope_map", {}).items()
        }
        config["app_proton_map"] = {
            app_key: runtime for app_key, runtime in config.get("app_proton_map", {}).items()
        }
        config["app_gamescope_map"] = {
            app_key: _normalize_gamescope_settings(settings)
            for app_key, settings in config.get("app_gamescope_map", {}).items()
        }
        config["app_art_map"] = {
            app_key: str(pathlib.Path(os.path.expanduser(path)))
            for app_key, path in config.get("app_art_map", {}).items()
            if path
        }
        config["app_art_zoom_map"] = {
            app_key: int(value)
            for app_key, value in config.get("app_art_zoom_map", {}).items()
            if isinstance(value, int | float | str) and str(value).strip()
        }
        return config

    def save(self) -> None:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(json.dumps(self.data, indent=2), encoding="utf-8")

    @property
    def proton_dir(self) -> pathlib.Path:
        return pathlib.Path(self.data["proton_dir"])

    def set_proton_dir(self, directory: str) -> None:
        self.data["proton_dir"] = str(pathlib.Path(os.path.expanduser(directory)))
        self.save()

    @property
    def default_runtime(self) -> str:
        return self.data.get("default_proton", "")

    def set_default_runtime(self, runtime_tag: str) -> None:
        self.data["default_proton"] = runtime_tag
        self.save()

    @property
    def proton_launch_backend(self) -> str:
        return "direct" if str(self.data.get("proton_launch_backend", "umu")).strip().lower() == "direct" else "umu"

    def set_proton_launch_backend(self, backend: str) -> None:
        self.data["proton_launch_backend"] = "direct" if str(backend).strip().lower() == "direct" else "umu"
        self.save()

    @property
    def umu_executable(self) -> str:
        return str(self.data.get("umu_executable") or "umu-run").strip() or "umu-run"

    def default_gamescope(self) -> GamescopeSettings:
        return GamescopeSettings.from_raw(self.data.get("gamescope_defaults", {}))

    def set_default_gamescope(self, settings: GamescopeSettings) -> None:
        self.data["gamescope_defaults"] = settings.to_config()
        self.save()

    def runtime_override(self, prefix: str) -> Optional[str]:
        return self.data.get("prefix_proton_map", {}).get(prefix)

    def set_runtime_override(self, prefix: str, runtime_tag: Optional[str]) -> None:
        mapping = self.data.setdefault("prefix_proton_map", {})
        if runtime_tag is None:
            mapping.pop(prefix, None)
        else:
            mapping[prefix] = runtime_tag
        self.save()

    def gamescope_override(self, prefix: str) -> Optional[GamescopeSettings]:
        raw = self.data.get("prefix_gamescope_map", {}).get(prefix)
        if raw is None:
            return None
        return GamescopeSettings.from_raw(raw)

    def set_gamescope_override(self, prefix: str, settings: Optional[GamescopeSettings]) -> None:
        mapping = self.data.setdefault("prefix_gamescope_map", {})
        if settings is None:
            mapping.pop(prefix, None)
        else:
            mapping[prefix] = settings.to_config()
        self.save()

    def app_runtime_override(self, prefix: str, exe_path: str) -> Optional[str]:
        return self.data.get("app_proton_map", {}).get(f"{prefix}::{exe_path}")

    def set_app_runtime_override(self, prefix: str, exe_path: str, runtime_tag: Optional[str]) -> None:
        mapping = self.data.setdefault("app_proton_map", {})
        app_key = f"{prefix}::{exe_path}"
        if runtime_tag is None:
            mapping.pop(app_key, None)
        else:
            mapping[app_key] = runtime_tag
        self.save()

    def app_gamescope_override(self, prefix: str, exe_path: str) -> Optional[GamescopeSettings]:
        raw = self.data.get("app_gamescope_map", {}).get(f"{prefix}::{exe_path}")
        if raw is None:
            return None
        return GamescopeSettings.from_raw(raw)

    def set_app_gamescope_override(
        self,
        prefix: str,
        exe_path: str,
        settings: Optional[GamescopeSettings],
    ) -> None:
        mapping = self.data.setdefault("app_gamescope_map", {})
        app_key = f"{prefix}::{exe_path}"
        if settings is None:
            mapping.pop(app_key, None)
        else:
            mapping[app_key] = settings.to_config()
        self.save()

    def effective_gamescope(self, prefix: str, exe_path: Optional[str] = None) -> GamescopeSettings:
        settings = self.default_gamescope()
        prefix_override = self.gamescope_override(prefix)
        if prefix_override is not None:
            settings = prefix_override

        if exe_path is None:
            return settings

        app_override = self.app_gamescope_override(prefix, exe_path)
        if app_override is not None:
            return app_override
        return settings

    def app_art_override(self, prefix: str, exe_path: str) -> Optional[str]:
        app_key = f"{prefix}::{exe_path}"
        path = self.data.get("app_art_map", {}).get(app_key)
        if not path:
            return None
        normalized = str(pathlib.Path(os.path.expanduser(path)))
        if pathlib.Path(normalized).exists():
            return normalized
        return None

    def set_app_art_override(self, prefix: str, exe_path: str, art_path: Optional[str]) -> None:
        mapping = self.data.setdefault("app_art_map", {})
        app_key = f"{prefix}::{exe_path}"
        if not art_path:
            mapping.pop(app_key, None)
            self.data.setdefault("app_art_zoom_map", {}).pop(app_key, None)
        else:
            mapping[app_key] = str(pathlib.Path(os.path.expanduser(art_path)))
        self.save()

    def app_art_zoom(self, prefix: str, exe_path: str) -> int:
        app_key = f"{prefix}::{exe_path}"
        raw_value = self.data.get("app_art_zoom_map", {}).get(app_key, 0)
        try:
            return max(-95, min(400, int(raw_value)))
        except Exception:
            return 0

    def set_app_art_zoom(self, prefix: str, exe_path: str, zoom: Optional[int]) -> None:
        mapping = self.data.setdefault("app_art_zoom_map", {})
        app_key = f"{prefix}::{exe_path}"
        if zoom is None:
            mapping.pop(app_key, None)
        else:
            mapping[app_key] = max(-95, min(400, int(zoom)))
        self.save()

    def extra_prefix_dirs(self) -> list[str]:
        return list(self.data.get("extra_prefix_dirs", []))

    def add_prefix_dir(self, directory: str) -> bool:
        normalized = str(pathlib.Path(os.path.expanduser(directory)))
        entries = self.data.setdefault("extra_prefix_dirs", [])
        if normalized in entries:
            return False
        entries.append(normalized)
        self.save()
        return True

    def remove_prefix_dir(self, directory: str) -> bool:
        normalized = str(pathlib.Path(os.path.expanduser(directory)))
        entries = self.data.setdefault("extra_prefix_dirs", [])
        if normalized not in entries:
            return False
        entries.remove(normalized)
        self.save()
        return True

    def favorites_for(self, prefix: str) -> list[str]:
        return list(self.data.get("prefix_favorites", {}).get(prefix, []))

    def hidden_apps_for(self, prefix: str) -> list[str]:
        return list(self.data.get("prefix_hidden_apps", {}).get(prefix, []))

    def hide_app(self, prefix: str, exe_path: str) -> bool:
        hidden_apps = self.data.setdefault("prefix_hidden_apps", {}).setdefault(prefix, [])
        if exe_path in hidden_apps:
            return False
        hidden_apps.append(exe_path)
        self.save()
        return True

    def unhide_app(self, prefix: str, exe_path: str) -> bool:
        hidden_apps = self.data.setdefault("prefix_hidden_apps", {}).get(prefix, [])
        if exe_path not in hidden_apps:
            return False
        hidden_apps.remove(exe_path)
        self.save()
        return True

    def manual_apps_for(self, prefix: str) -> list[str]:
        return list(self.data.get("prefix_manual_apps", {}).get(prefix, []))

    def add_manual_app(self, prefix: str, exe_path: str) -> bool:
        manual_apps = self.data.setdefault("prefix_manual_apps", {}).setdefault(prefix, [])
        if exe_path in manual_apps:
            return False
        manual_apps.append(exe_path)
        self.save()
        return True

    def remove_manual_app(self, prefix: str, exe_path: str) -> bool:
        manual_apps = self.data.setdefault("prefix_manual_apps", {}).get(prefix, [])
        if exe_path not in manual_apps:
            return False
        manual_apps.remove(exe_path)
        self.save()
        return True

    def remove_app_from_library(self, prefix: str, exe_path: str) -> bool:
        changed = False

        manual_apps = self.data.setdefault("prefix_manual_apps", {}).get(prefix, [])
        if exe_path in manual_apps:
            manual_apps.remove(exe_path)
            changed = True

        favorites = self.data.setdefault("prefix_favorites", {}).get(prefix, [])
        if exe_path in favorites:
            favorites.remove(exe_path)
            changed = True

        hidden_apps = self.data.setdefault("prefix_hidden_apps", {}).setdefault(prefix, [])
        if exe_path not in hidden_apps:
            hidden_apps.append(exe_path)
            changed = True

        app_key = f"{prefix}::{exe_path}"
        runtime_overrides = self.data.setdefault("app_proton_map", {})
        if app_key in runtime_overrides:
            runtime_overrides.pop(app_key, None)
            changed = True

        gamescope_overrides = self.data.setdefault("app_gamescope_map", {})
        if app_key in gamescope_overrides:
            gamescope_overrides.pop(app_key, None)
            changed = True

        art_overrides = self.data.setdefault("app_art_map", {})
        if app_key in art_overrides:
            art_overrides.pop(app_key, None)
            changed = True

        art_zoom_overrides = self.data.setdefault("app_art_zoom_map", {})
        if app_key in art_zoom_overrides:
            art_zoom_overrides.pop(app_key, None)
            changed = True

        if changed:
            self.save()
        return changed

    def add_favorite(self, prefix: str, exe_path: str) -> bool:
        favorites = self.data.setdefault("prefix_favorites", {}).setdefault(prefix, [])
        if exe_path in favorites:
            return False
        favorites.append(exe_path)
        self.save()
        return True

    def remove_favorite(self, prefix: str, exe_path: str) -> bool:
        favorites = self.data.setdefault("prefix_favorites", {}).get(prefix, [])
        if exe_path not in favorites:
            return False
        favorites.remove(exe_path)
        self.save()
        return True

    def favorite_count(self, prefix: str) -> int:
        return len(self.data.get("prefix_favorites", {}).get(prefix, []))

    def total_favorites(self) -> int:
        return sum(len(items) for items in self.data.get("prefix_favorites", {}).values())


class LogManager(QObject):
    logUpdated = Signal(str)

    def __init__(self):
        super().__init__()
        self.logs: list[str] = []
        self.max_logs = 1000

    def add(self, level: str, message: str, source: str = "App") -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        entry = f"[{timestamp}] [{level}] [{source}] {message}"
        self.logs.append(entry)
        if len(self.logs) > self.max_logs:
            self.logs = self.logs[-self.max_logs :]
        self.logUpdated.emit(entry)
        stream = None if level in {"INFO", "DEBUG"} else __import__("sys").stderr
        print(entry, file=stream)

    def clear(self) -> None:
        self.logs.clear()
        self.logUpdated.emit("Logs cleared")

    def recent(self, limit: int = 8) -> list[str]:
        return list(self.logs[-limit:])

    def dump(self) -> str:
        return "\n".join(self.logs)


@dataclass(slots=True)
class ProtonRelease:
    tag: str
    name: str
    published: datetime
    asset_url: str


@dataclass(slots=True)
class AppEntry:
    key: str
    prefix: str
    exe_path: str
    display_name: str
    runtime_tag: str
    is_favorite: bool


@dataclass(slots=True)
class ArtworkSuggestion:
    key: str
    title: str
    source: str
    image_path: str
    attribution: str


def normalize_app_name(value: str) -> str:
    name = pathlib.Path(value).stem
    lowered = name.lower()
    for prefix in ["play", "start", "launch", "run", "game", "setup"]:
        if lowered.startswith(f"{prefix}_") or lowered.startswith(f"{prefix}-"):
            name = name[len(prefix) + 1 :]
            lowered = name.lower()
    tokens = [token for token in name.replace("_", " ").replace("-", " ").split() if token]
    return " ".join(tokens) if tokens else pathlib.Path(value).stem


def is_system_executable(exe_path: str, display_name: str = "") -> bool:
    lower_path = exe_path.lower()
    if any(part in lower_path for part in ["/windows/", "\\windows\\", "/system32/", "\\system32\\"]):
        return True

    normalized_name = normalize_app_name(display_name or exe_path).strip().lower()
    return bool(normalized_name) and normalized_name in SYSTEM_POSTER_NAMES


def search_artwork_suggestions(app_name: str, limit: int = 6) -> list[ArtworkSuggestion]:
    normalized_name = normalize_app_name(app_name).strip()
    lowered_name = normalized_name.lower()
    if not normalized_name or lowered_name in SYSTEM_POSTER_NAMES:
        return []

    ranked: dict[str, dict] = {}
    name_variants = _build_artwork_name_variants(normalized_name)

    for query in name_variants:
        for candidate in _query_steam_artwork_candidates(query, normalized_name):
            current = ranked.get(candidate["key"])
            if current is None or candidate["score"] > current["score"]:
                ranked[candidate["key"]] = candidate

    wikimedia_queries: list[str] = []
    for variant in name_variants:
        wikimedia_queries.extend(
            [
                f'"{variant}" video game cover art',
                f'"{variant}" video game icon',
                f'"{variant}" logo',
                variant,
            ]
        )

    seen_queries: set[str] = set()
    for query in wikimedia_queries:
        if query in seen_queries:
            continue
        seen_queries.add(query)
        for candidate in _query_wikimedia_artwork_candidates(query, normalized_name):
            current = ranked.get(candidate["key"])
            if current is None or candidate["score"] > current["score"]:
                ranked[candidate["key"]] = candidate
        if len(ranked) >= limit * 2:
            break

    suggestions: list[ArtworkSuggestion] = []
    for candidate in sorted(ranked.values(), key=lambda item: item["score"], reverse=True)[:limit]:
        try:
            image_path = _download_cached_artwork(candidate["thumbnail"], candidate["key"])
        except Exception:
            continue
        suggestions.append(
            ArtworkSuggestion(
                key=candidate["key"],
                title=candidate["title"],
                source=candidate["source"],
                image_path=image_path,
                attribution=candidate["attribution"],
            )
        )
    return suggestions


def _build_artwork_name_variants(app_name: str) -> list[str]:
    variants: list[str] = []

    def add_variant(value: str) -> None:
        candidate = " ".join(value.replace("_", " ").split()).strip(" -:_[]()")
        if candidate and candidate not in variants:
            variants.append(candidate)

    add_variant(app_name)
    for separator in [":", " - ", "(", "["]:
        if separator in app_name:
            add_variant(app_name.split(separator, 1)[0])

    tokens = app_name.split()
    suffix_noise = {
        "edition",
        "ultimate",
        "complete",
        "remastered",
        "definitive",
        "deluxe",
        "launcher",
        "demo",
        "trial",
        "beta",
        "alpha",
        "goty",
        "year",
        "game",
        "pack",
    }
    trimmed = list(tokens)
    while len(trimmed) > 1 and trimmed[-1].strip("()[]").lower() in suffix_noise:
        trimmed.pop()
    add_variant(" ".join(trimmed))
    return variants


def _query_steam_artwork_candidates(query: str, app_name: str) -> list[dict]:
    try:
        response = requests.get(
            STEAM_STORE_SEARCH_API,
            headers=REQUEST_HEADERS,
            params={"term": query, "l": "english", "cc": "us"},
            timeout=20,
        )
        response.raise_for_status()
        results = response.json().get("items", [])
    except Exception:
        return []

    normalized_app_name = normalize_app_name(app_name).strip().lower()
    app_tokens = {token.lower() for token in normalized_app_name.replace("-", " ").split() if len(token) > 2}
    app_markers = _series_markers(normalized_app_name)
    prelim_ranked: list[dict] = []

    for result in results:
        if result.get("type") != "app":
            continue

        title = normalize_app_name(result.get("name") or "").strip()
        if not title:
            continue
        lower_title = title.lower()
        candidate_markers = _series_markers(lower_title)
        if app_markers and candidate_markers and not (app_markers & candidate_markers):
            continue
        score = sum(3 for token in app_tokens if token in lower_title)
        if lower_title == normalized_app_name:
            score += 18
        elif normalized_app_name and (lower_title.startswith(normalized_app_name) or normalized_app_name.startswith(lower_title)):
            score += 10
        elif normalized_app_name and normalized_app_name in lower_title:
            score += 6

        if result.get("platforms", {}).get("windows"):
            score += 1
        if score < 4:
            continue

        prelim_ranked.append(
            {
                "app_id": int(result.get("id") or 0),
                "title": title,
                "fallback_thumbnail": result.get("tiny_image") or "",
                "score": score,
            }
        )

    prelim_ranked.sort(key=lambda item: item["score"], reverse=True)
    candidates: list[dict] = []
    for result in prelim_ranked[:4]:
        artwork_url, artwork_kind, app_type = _fetch_steam_artwork_url(result["app_id"], result["fallback_thumbnail"])
        if app_type and app_type not in {"game"}:
            continue
        if not artwork_url:
            continue

        score = result["score"] + (6 if artwork_kind == "header" else 2)
        candidates.append(
            {
                "key": f"steam-{result['app_id']}-{artwork_kind}",
                "title": result["title"],
                "thumbnail": artwork_url,
                "attribution": f"https://store.steampowered.com/app/{result['app_id']}/",
                "source": "Steam artwork" if artwork_kind == "header" else "Steam capsule",
                "score": score,
            }
        )
    return candidates


def _fetch_steam_artwork_url(app_id: int, fallback_thumbnail: str) -> tuple[str, str, str]:
    if app_id <= 0:
        return fallback_thumbnail, "search", ""

    try:
        response = requests.get(
            STEAM_APPDETAILS_API,
            headers=REQUEST_HEADERS,
            params={"appids": str(app_id), "l": "english", "cc": "us"},
            timeout=20,
        )
        response.raise_for_status()
        data = (response.json().get(str(app_id)) or {}).get("data") or {}
    except Exception:
        data = {}

    app_type = str(data.get("type") or "")
    for key in ["header_image", "capsule_image", "capsule_imagev5"]:
        value = data.get(key)
        if value:
            return value, "header" if key == "header_image" else "capsule", app_type
    return fallback_thumbnail, "search", app_type


def _series_markers(value: str) -> set[str]:
    roman_numerals = {"i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x"}
    markers: set[str] = set()
    for token in value.replace("-", " ").split():
        cleaned = token.strip("()[]:,.!?").lower()
        if cleaned.isdigit() or cleaned in roman_numerals:
            markers.add(cleaned)
    return markers


def _query_wikimedia_artwork_candidates(query: str, app_name: str) -> list[dict]:
    try:
        response = requests.get(
            WIKIMEDIA_COMMONS_API,
            headers=REQUEST_HEADERS,
            params={
                "action": "query",
                "format": "json",
                "generator": "search",
                "gsrsearch": query,
                "gsrnamespace": 6,
                "gsrlimit": 12,
                "prop": "imageinfo",
                "iiprop": "url|size|mime",
                "iiurlwidth": 480,
            },
            timeout=20,
        )
        response.raise_for_status()
        results = list((response.json().get("query") or {}).get("pages", {}).values())
    except Exception:
        return []

    normalized_app_name = normalize_app_name(app_name).strip().lower()
    app_tokens = {token.lower() for token in normalized_app_name.replace("-", " ").split() if len(token) > 2}
    ranked: list[dict] = []
    for result in results:
        title = (result.get("title") or "").replace("File:", "")
        lower_title = title.lower()
        imageinfo = (result.get("imageinfo") or [{}])[0]
        image_url = imageinfo.get("thumburl") or imageinfo.get("url") or ""
        if not image_url:
            continue

        mime = (imageinfo.get("mime") or "").lower()
        if mime.startswith("application/"):
            continue

        width = imageinfo.get("thumbwidth") or imageinfo.get("width") or 0
        height = imageinfo.get("thumbheight") or imageinfo.get("height") or 0
        if width <= 0 or height <= 0:
            continue

        score = sum(3 for token in app_tokens if token in lower_title)
        if normalized_app_name and normalized_app_name in lower_title:
            score += 8

        is_icon_like = any(token in lower_title for token in ["icon", "logo", "banner"])
        is_image_like = any(token in lower_title for token in ["cover", "box art", "poster", "key art", "artwork"])
        if is_icon_like:
            score += 4
        if is_image_like:
            score += 5
        if "game" in lower_title or "video" in lower_title:
            score += 1
        if "screenshot" in lower_title or "photo" in lower_title:
            score -= 8
        if "fan art" in lower_title or "wallpaper" in lower_title:
            score -= 4
        if is_icon_like and abs(width - height) <= max(width, height) * 0.2:
            score += 1
        if is_image_like and height > width:
            score += 2
        if mime.endswith("svg+xml"):
            score -= 1
        if score < 5:
            continue

        ranked.append(
            {
                "key": str(result.get("pageid") or title),
                "title": title,
                "thumbnail": image_url,
                "attribution": imageinfo.get("descriptionurl", ""),
                "source": "Wikimedia icon" if is_icon_like and not is_image_like else "Wikimedia image",
                "score": score,
            }
        )

    return ranked


def _download_cached_artwork(url: str, image_id: str) -> str:
    POSTER_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    target = POSTER_CACHE_DIR / f"artwork-{image_id}.jpg"
    if target.exists() and target.stat().st_size > 0:
        return str(target)

    response = requests.get(url, headers=REQUEST_HEADERS, timeout=20)
    response.raise_for_status()
    target.write_bytes(response.content)
    return str(target)


def aggregate_apps(
    prefixes: list[str],
    scanner_cache: dict[str, list[str]],
    config: ConfigStore,
    installed_tags: list[str],
) -> list[AppEntry]:
    entries: dict[str, AppEntry] = {}
    installed = set(installed_tags)

    for prefix in prefixes:
        override = config.runtime_override(prefix)
        prefix_runtime = config.default_runtime if override is None else override
        if prefix_runtime and prefix_runtime not in installed:
            prefix_runtime = ""

        favorites = set(config.favorites_for(prefix))
        hidden_apps = set(config.hidden_apps_for(prefix))
        known_apps: list[str] = []
        seen_paths: set[str] = set()
        for exe_path in [*config.manual_apps_for(prefix), *favorites, *scanner_cache.get(prefix, [])]:
            if exe_path in seen_paths:
                continue
            seen_paths.add(exe_path)
            known_apps.append(exe_path)

        for exe_path in known_apps:
            if exe_path in hidden_apps:
                continue
            key = f"{prefix}::{exe_path}"
            app_runtime = config.app_runtime_override(prefix, exe_path)
            runtime_tag = prefix_runtime if app_runtime is None else app_runtime
            if runtime_tag and runtime_tag not in installed:
                runtime_tag = ""
            entries[key] = AppEntry(
                key=key,
                prefix=prefix,
                exe_path=exe_path,
                display_name=normalize_app_name(exe_path),
                runtime_tag=runtime_tag,
                is_favorite=exe_path in favorites,
            )

    return sorted(
        entries.values(),
        key=lambda entry: (
            not entry.is_favorite,
            entry.display_name.lower(),
            pathlib.Path(entry.prefix).name.lower(),
        ),
    )


def discover_prefixes(config: ConfigStore, logger: LogManager) -> list[str]:
    home = pathlib.Path.home()
    roots = [
        home / ".wine",
        home / ".local/share/wineprefixes",
        home / ".local/share/bottles/bottles",
        home / ".local/share/bottles/data/bottles",
        home / ".var/app/com.usebottles.bottles/data/bottles",
        home / ".var/app/com.usebottles.bottles/data/bottles/bottles",
    ]
    roots.extend(pathlib.Path(path) for path in config.extra_prefix_dirs())

    prefixes: set[str] = set()
    for root in roots:
        if not root.exists():
            continue

        if (root / "system.reg").exists():
            prefixes.add(str(root))

        try:
            for child in root.iterdir():
                if not child.is_dir():
                    continue
                if (child / "system.reg").exists():
                    prefixes.add(str(child))
                elif (child / "prefix" / "system.reg").exists():
                    prefixes.add(str(child / "prefix"))
        except PermissionError:
            logger.add("WARNING", f"Permission denied while scanning {root}", "PrefixDiscovery")
        except Exception as error:
            logger.add("WARNING", f"Failed to scan {root}: {error}", "PrefixDiscovery")

    logger.add("INFO", f"Discovered {len(prefixes)} Wine prefixes", "PrefixDiscovery")
    return sorted(prefixes)


class ProgramScanner(QObject):
    scanned = Signal(str, list)
    scanStarted = Signal(str)

    def __init__(self, logger: LogManager):
        super().__init__()
        self.logger = logger
        self.cache: dict[str, list[str]] = {}

    def scan(self, prefix: str, force: bool = False) -> None:
        if prefix in self.cache and not force:
            cached = list(self.cache[prefix])
            QTimer.singleShot(0, lambda prefix=prefix, apps=cached: _safe_emit(self.scanned, prefix, apps))
            return
        threading.Thread(target=self._scan, args=(prefix,), daemon=True).start()

    def _scan(self, prefix: str) -> None:
        _safe_emit(self.scanStarted, prefix)
        prefix_path = pathlib.Path(prefix)
        drive = prefix_path / "drive_c"
        if not drive.exists():
            drive = prefix_path / "prefix" / "drive_c"

        apps: list[str] = []
        if drive.exists():
            for file_path in drive.rglob("*.exe"):
                if file_path.is_file():
                    apps.append(str(file_path))

        apps.sort(key=lambda entry: pathlib.Path(entry).name.lower())
        self.cache[prefix] = apps
        self.logger.add("INFO", f"Indexed {len(apps)} applications in {prefix}", "ProgramScanner")
        _safe_emit(self.scanned, prefix, apps)


class PosterService(QObject):
    posterReady = Signal(str, str, str)

    def __init__(self, logger: LogManager):
        super().__init__()
        self.logger = logger
        POSTER_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        self.index = self._load_index()
        self._inflight: set[str] = set()
        self._pending_keys: dict[str, list[str]] = {}
        self._queue: deque[str] = deque()
        self._queue_lock = threading.Lock()
        self._queue_event = threading.Event()
        self._last_request_at = 0.0
        self._rate_limited_until = 0.0
        self._rate_limit_logged = False
        self._worker = threading.Thread(target=self._process_queue, daemon=True)
        self._worker.start()

    def _load_index(self) -> dict:
        try:
            return json.loads(POSTER_INDEX_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save_index(self) -> None:
        POSTER_INDEX_FILE.write_text(json.dumps(self.index, indent=2), encoding="utf-8")

    def request_poster(self, app_key: str, app_name: str, exe_path: str = "") -> None:
        cached = self.index.get(app_name)
        if cached and cached.get("provider") == POSTER_PROVIDER:
            image_path = cached.get("image_path", "")
            if image_path and pathlib.Path(image_path).exists():
                QTimer.singleShot(0, lambda: _safe_emit(self.posterReady, app_key, image_path, cached.get("attribution", "")))
                return
            if cached.get("resolved"):
                QTimer.singleShot(0, lambda: _safe_emit(self.posterReady, app_key, "", cached.get("attribution", "")))
                return

        if not self._should_fetch_poster(app_name, exe_path):
            self.index[app_name] = {
                "image_path": "",
                "attribution": "",
                "resolved": True,
                "provider": POSTER_PROVIDER,
            }
            self._save_index()
            QTimer.singleShot(0, lambda: _safe_emit(self.posterReady, app_key, "", ""))
            return

        with self._queue_lock:
            listeners = self._pending_keys.setdefault(app_name, [])
            if app_key not in listeners:
                listeners.append(app_key)
            if app_name not in self._inflight:
                self._inflight.add(app_name)
                self._queue.append(app_name)
                self._queue_event.set()

    def _process_queue(self) -> None:
        while True:
            self._queue_event.wait()
            with self._queue_lock:
                if not self._queue:
                    self._queue_event.clear()
                    continue
                app_name = self._queue.popleft()

            now = time.monotonic()
            if self._rate_limited_until > now:
                time.sleep(self._rate_limited_until - now)

            elapsed = time.monotonic() - self._last_request_at
            if elapsed < POSTER_QUERY_INTERVAL_SECONDS:
                time.sleep(POSTER_QUERY_INTERVAL_SECONDS - elapsed)

            self._last_request_at = time.monotonic()
            self._resolve_poster(app_name)

    def _resolve_poster(self, app_name: str) -> None:
        queries = [
            f'"{app_name}" video game',
            f'"{app_name}" game cover',
            app_name,
        ]

        best_result = None
        for query in queries:
            best_result = self._query_wikimedia_commons(query, app_name)
            if self._rate_limited_until > time.monotonic():
                break
            if best_result is not None:
                break

        image_path = ""
        attribution = ""
        if best_result is not None:
            try:
                image_path = self._download_thumbnail(best_result["thumbnail"], best_result["id"])
                attribution = best_result.get("attribution", "")
                self.index[app_name] = {
                    "image_path": image_path,
                    "attribution": attribution,
                    "resolved": True,
                    "provider": POSTER_PROVIDER,
                }
                self._save_index()
                self.logger.add("INFO", f"Found poster for {app_name}", "PosterService")
            except Exception as error:
                self.logger.add("WARNING", f"Poster download failed for {app_name}: {error}", "PosterService")
        else:
            self.index[app_name] = {
                "image_path": "",
                "attribution": "",
                "resolved": True,
                "provider": POSTER_PROVIDER,
            }
            self._save_index()

        with self._queue_lock:
            app_keys = self._pending_keys.pop(app_name, [])
            self._inflight.discard(app_name)
        for app_key in app_keys:
            _safe_emit(self.posterReady, app_key, image_path, attribution)

    def _should_fetch_poster(self, app_name: str, exe_path: str) -> bool:
        normalized_name = normalize_app_name(app_name).strip().lower()
        if not normalized_name or normalized_name in SYSTEM_POSTER_NAMES:
            return False

        if len(normalized_name) <= 3:
            return False

        tokens = [token for token in normalized_name.replace("-", " ").split() if token]
        if tokens and all(len(token) <= 3 for token in tokens):
            return False

        if is_system_executable(exe_path, app_name):
            return False

        return True

    def _query_wikimedia_commons(self, query: str, app_name: str) -> Optional[dict]:
        try:
            response = requests.get(
                WIKIMEDIA_COMMONS_API,
                headers=REQUEST_HEADERS,
                params={
                    "action": "query",
                    "format": "json",
                    "generator": "search",
                    "gsrsearch": query,
                    "gsrnamespace": 6,
                    "gsrlimit": 10,
                    "prop": "imageinfo",
                    "iiprop": "url|size|mime",
                    "iiurlwidth": 480,
                },
                timeout=20,
            )
            response.raise_for_status()
            results = list((response.json().get("query") or {}).get("pages", {}).values())
            self._rate_limit_logged = False
        except Exception as error:
            status_code = getattr(getattr(error, "response", None), "status_code", None)
            if status_code == 429:
                self._rate_limited_until = time.monotonic() + POSTER_RATE_LIMIT_COOLDOWN_SECONDS
                if not self._rate_limit_logged:
                    self.logger.add(
                        "WARNING",
                        "Wikimedia is rate limiting requests. Poster lookup will pause briefly.",
                        "PosterService",
                    )
                    self._rate_limit_logged = True
                return None
            self.logger.add("WARNING", f"Wikimedia lookup failed for {app_name}: {error}", "PosterService")
            return None

        app_tokens = {token.lower() for token in normalize_app_name(app_name).split() if len(token) > 2}
        normalized_app_name = normalize_app_name(app_name).strip().lower()
        ranked: list[tuple[int, dict]] = []
        for result in results:
            title = (result.get("title") or "").replace("File:", "")
            lower_title = title.lower()
            imageinfo = (result.get("imageinfo") or [{}])[0]
            image_url = imageinfo.get("thumburl") or imageinfo.get("url") or ""
            if not image_url:
                continue
            mime = (imageinfo.get("mime") or "").lower()
            if mime.startswith("application/"):
                continue
            width = imageinfo.get("thumbwidth") or imageinfo.get("width") or 0
            height = imageinfo.get("thumbheight") or imageinfo.get("height") or 0
            if width <= 0 or height <= 0:
                continue
            score = sum(3 for token in app_tokens if token in lower_title)
            if normalized_app_name and normalized_app_name in lower_title:
                score += 6
            if "cover" in lower_title or "box art" in lower_title:
                score += 5
            if "poster" in lower_title or "key art" in lower_title:
                score += 4
            if "logo" in lower_title:
                score -= 4
            if "game" in lower_title or "video" in lower_title:
                score += 1
            if "screenshot" in lower_title or "photo" in lower_title or "icon" in lower_title:
                score -= 6
            if "fan art" in lower_title or "wallpaper" in lower_title:
                score -= 3
            if height > width:
                score += 2
            elif width == height:
                score -= 2
            if mime.endswith("svg+xml"):
                score -= 3
            if score < POSTER_MIN_SCORE:
                continue
            ranked.append(
                (
                    score,
                    {
                        "id": str(result.get("pageid") or title),
                        "thumbnail": image_url,
                        "attribution": imageinfo.get("descriptionurl", ""),
                    },
                )
            )

        if not ranked:
            return None
        ranked.sort(key=lambda item: item[0], reverse=True)
        return ranked[0][1]

    def _download_thumbnail(self, url: str, image_id: str) -> str:
        response = requests.get(url, headers=REQUEST_HEADERS, timeout=20)
        response.raise_for_status()
        target = POSTER_CACHE_DIR / f"{image_id}.jpg"
        target.write_bytes(response.content)
        return str(target)


class ProtonManager(QObject):
    remoteReady = Signal(list)
    installedReady = Signal(list)
    downloadProgress = Signal(str, int, int)
    installProgress = Signal(str, str)
    downloadFinished = Signal(str, bool, str)
    uninstallFinished = Signal(str, bool, str)

    def __init__(self, config: ConfigStore, logger: LogManager):
        super().__init__()
        self.config = config
        self.logger = logger
        self.refresh_directory()

    def refresh_directory(self) -> None:
        self.proton_dir = self.config.proton_dir
        self.proton_dir.mkdir(parents=True, exist_ok=True)

    def query_remote(self) -> None:
        threading.Thread(target=self._fetch_remote_async, daemon=True).start()

    def query_installed(self) -> None:
        threading.Thread(target=self._emit_installed, daemon=True).start()

    def install(self, tag: str) -> None:
        threading.Thread(target=self._install, args=(tag,), daemon=True).start()

    def uninstall(self, tag: str) -> None:
        threading.Thread(target=self._uninstall, args=(tag,), daemon=True).start()

    def proton_executable(self, tag: str) -> Optional[pathlib.Path]:
        exe = self.proton_dir / tag / "proton"
        return exe if exe.exists() else None

    def _emit_installed(self) -> None:
        try:
            tags = sorted(path.name for path in self.proton_dir.iterdir() if (path / "proton").exists())
        except Exception:
            tags = []
        _safe_emit(self.installedReady, tags)

    def _fetch_remote_async(self) -> None:
        _safe_emit(self.remoteReady, self._fetch_remote_sync())

    def _fetch_remote_sync(self) -> list[ProtonRelease]:
        try:
            response = requests.get(GITHUB_API, headers=REQUEST_HEADERS, timeout=20)
            response.raise_for_status()
            releases: list[ProtonRelease] = []
            for entry in response.json():
                asset = next(
                    (item for item in entry.get("assets", []) if item.get("name", "").endswith(".tar.gz")),
                    None,
                )
                if not asset:
                    continue
                releases.append(
                    ProtonRelease(
                        tag=entry["tag_name"],
                        name=entry["name"],
                        published=datetime.fromisoformat(entry["published_at"].rstrip("Z")),
                        asset_url=asset["browser_download_url"],
                    )
                )
            self.logger.add("INFO", f"Fetched {len(releases)} Proton releases", "ProtonManager")
            return releases
        except Exception as error:
            self.logger.add("ERROR", f"Could not fetch Proton releases: {error}", "ProtonManager")
            return []

    def _install(self, tag: str) -> None:
        releases = self._fetch_remote_sync()
        release = next((entry for entry in releases if entry.tag == tag), None)
        if not release:
            _safe_emit(self.downloadFinished, tag, False, "Release not found")
            return

        destination = self.proton_dir / tag
        if destination.exists():
            _safe_emit(self.downloadFinished, tag, True, "Already installed")
            return

        archive_fd, archive_path = tempfile.mkstemp(suffix=".tar.gz")
        os.close(archive_fd)

        try:
            with requests.get(release.asset_url, headers=REQUEST_HEADERS, stream=True, timeout=30) as response:
                response.raise_for_status()
                total = int(response.headers.get("Content-Length", 0))
                done = 0
                with open(archive_path, "wb") as handle:
                    for chunk in response.iter_content(8192):
                        if not chunk:
                            continue
                        handle.write(chunk)
                        done += len(chunk)
                        _safe_emit(self.downloadProgress, tag, done, total)

            _safe_emit(self.installProgress, tag, "Extracting archive")
            with tempfile.TemporaryDirectory(prefix="wine-manager-proton-") as staging_root:
                self._extract_archive(pathlib.Path(archive_path), pathlib.Path(staging_root))
                extracted = next(
                    (path for path in pathlib.Path(staging_root).iterdir() if path.is_dir() and (path / "proton").exists()),
                    None,
                )
                if extracted is None:
                    raise RuntimeError("Archive does not contain a Proton build")
                shutil.move(str(extracted), str(destination))

            self.logger.add("INFO", f"Installed Proton {tag}", "ProtonManager")
            _safe_emit(self.downloadFinished, tag, True, "Installed")
        except Exception as error:
            shutil.rmtree(destination, ignore_errors=True)
            self.logger.add("ERROR", f"Could not install Proton {tag}: {error}", "ProtonManager")
            _safe_emit(self.downloadFinished, tag, False, str(error))
        finally:
            pathlib.Path(archive_path).unlink(missing_ok=True)

    def _extract_archive(self, archive_path: pathlib.Path, staging_root: pathlib.Path) -> None:
        with tarfile.open(archive_path, "r:gz") as archive:
            for member in archive.getmembers():
                resolved = (staging_root / member.name).resolve(strict=False)
                if not str(resolved).startswith(str(staging_root.resolve())):
                    raise RuntimeError("Archive contains an invalid path")
            archive.extractall(staging_root)

    def _uninstall(self, tag: str) -> None:
        destination = self.proton_dir / tag
        if not destination.exists():
            _safe_emit(self.uninstallFinished, tag, False, "Not installed")
            return

        try:
            shutil.rmtree(destination)
            self.logger.add("INFO", f"Removed Proton {tag}", "ProtonManager")
            _safe_emit(self.uninstallFinished, tag, True, "Removed")
        except Exception as error:
            self.logger.add("ERROR", f"Could not remove Proton {tag}: {error}", "ProtonManager")
            _safe_emit(self.uninstallFinished, tag, False, str(error))


@dataclass(slots=True)
class LaunchResult:
    pid: int
    command: list[str]
    runtime_label: str


class LaunchService:
    def __init__(self, proton_manager: ProtonManager, config: ConfigStore, logger: LogManager):
        self.proton_manager = proton_manager
        self.config = config
        self.logger = logger

    def launch(
        self,
        prefix: str,
        exe_path: str,
        runtime_tag: str,
        gamescope_settings: GamescopeSettings | None = None,
        launch_args: list[str] | None = None,
    ) -> LaunchResult:
        env = os.environ.copy()
        env["WINEPREFIX"] = prefix
        launch_args = list(launch_args or [])
        if gamescope_settings is None:
            gamescope_settings = self.config.effective_gamescope(prefix, exe_path)

        if runtime_tag:
            proton_exe = self.proton_manager.proton_executable(runtime_tag)
            if proton_exe is None:
                raise RuntimeError(f"Proton {runtime_tag} is not installed")
            if self.config.proton_launch_backend == "umu":
                base_command, runtime_label = self._build_umu_command(
                    env, exe_path, launch_args, runtime_tag, proton_exe.parent
                )
            else:
                base_command, runtime_label = self._build_direct_proton_command(
                    env, prefix, exe_path, launch_args, runtime_tag, proton_exe
                )
        else:
            base_command = ["wine", "start", "/unix", exe_path] + launch_args
            runtime_label = "Wine"

        if gamescope_settings.enabled:
            gamescope_executable = shutil.which("gamescope")
            if gamescope_executable is None:
                raise RuntimeError("gamescope is enabled, but the gamescope executable was not found")
            command = gamescope_settings.command_prefix(gamescope_executable) + base_command
            runtime_label = f"{runtime_label} via gamescope"
        else:
            command = base_command

        process = subprocess.Popen(
            command,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self.logger.add(
            "INFO",
            f"Launched {pathlib.Path(exe_path).name} via {runtime_label} (PID {process.pid})",
            "Launcher",
        )
        threading.Thread(
            target=self._capture_output,
            args=(process, pathlib.Path(exe_path).name, runtime_label),
            daemon=True,
        ).start()
        return LaunchResult(pid=process.pid, command=command, runtime_label=runtime_label)

    @staticmethod
    def _game_id(exe_path: str) -> str:
        digest = hashlib.sha1(exe_path.encode("utf-8")).hexdigest()[:12]
        return f"umu-wine-manager-{digest}"

    def _build_umu_command(
        self,
        env: dict,
        exe_path: str,
        launch_args: list[str],
        runtime_tag: str,
        proton_path: pathlib.Path,
    ) -> tuple[list[str], str]:
        umu_executable = shutil.which(self.config.umu_executable)
        if umu_executable is None:
            raise RuntimeError(
                f"umu-run ({self.config.umu_executable}) was not found. Install umu-launcher "
                "or switch the Proton launch backend to legacy direct mode in Settings."
            )
        env["GAMEID"] = self._game_id(exe_path)
        env.setdefault("STORE", "none")
        env["PROTONPATH"] = str(proton_path)
        command = [umu_executable, exe_path] + launch_args
        return command, f"Proton {runtime_tag} via umu-run"

    def _build_direct_proton_command(
        self,
        env: dict,
        prefix: str,
        exe_path: str,
        launch_args: list[str],
        runtime_tag: str,
        proton_exe: pathlib.Path,
    ) -> tuple[list[str], str]:
        env["STEAM_COMPAT_DATA_PATH"] = prefix
        env.setdefault("STEAM_COMPAT_CLIENT_INSTALL_PATH", "/usr")
        command = [str(proton_exe), "run", exe_path] + launch_args
        return command, f"Proton {runtime_tag} direct legacy"

    def _capture_output(self, process: subprocess.Popen, app_name: str, runtime_label: str) -> None:
        try:
            stdout, stderr = process.communicate(timeout=20)
        except subprocess.TimeoutExpired:
            self.logger.add("INFO", f"{app_name} is still running", runtime_label)
            return
        except Exception as error:
            self.logger.add("WARNING", f"Could not monitor {app_name}: {error}", runtime_label)
            return

        if stdout.strip():
            self.logger.add("INFO", stdout.strip(), runtime_label)
        if stderr.strip():
            level = "ERROR" if any(token in stderr.lower() for token in ["error", "failed", "exception"]) else "WARNING"
            self.logger.add(level, stderr.strip(), runtime_label)