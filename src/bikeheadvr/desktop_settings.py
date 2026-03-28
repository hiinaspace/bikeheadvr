from __future__ import annotations

import logging
import tomllib
from dataclasses import dataclass
from pathlib import Path

from platformdirs import user_config_path, user_log_path

from .app import RuntimeOptions

LOGGER = logging.getLogger(__name__)

APP_NAME = "bikeheadvr"
CONFIG_FILE_NAME = "config.toml"
LOG_FILE_NAME = "bikeheadvr.log"


@dataclass(frozen=True)
class DesktopSettings:
    locomotion_mode: str = "manual"
    pedal_calibration_enabled: bool = False
    verbose_logging: bool = False
    start_minimized: bool = False

    def to_runtime_options(self, log_file: Path | None = None) -> RuntimeOptions:
        return RuntimeOptions(
            locomotion_mode=self.locomotion_mode,
            pedal_calibration=self.pedal_calibration_enabled,
            verbose=self.verbose_logging,
            log_file=log_file,
        )


@dataclass(frozen=True)
class LoadResult:
    settings: DesktopSettings
    warning: str | None = None


def config_dir() -> Path:
    return user_config_path(APP_NAME, roaming=True, ensure_exists=True)


def config_path() -> Path:
    return config_dir() / CONFIG_FILE_NAME


def log_path() -> Path:
    return user_log_path(APP_NAME, ensure_exists=True) / LOG_FILE_NAME


def load_settings(path: Path | None = None) -> LoadResult:
    target = path or config_path()
    defaults = DesktopSettings()
    if not target.exists():
        return LoadResult(settings=defaults)

    try:
        raw = tomllib.loads(target.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        LOGGER.warning("Failed to load settings from %s: %s", target, exc)
        return LoadResult(
            settings=defaults,
            warning=(
                "Settings file was unreadable. Defaults were loaded for this session."
            ),
        )

    if not isinstance(raw, dict):
        return LoadResult(
            settings=defaults,
            warning="Settings file was invalid. Defaults were loaded for this session.",
        )

    locomotion_mode = raw.get("locomotion_mode", defaults.locomotion_mode)
    if locomotion_mode not in {"manual", "tracker"}:
        locomotion_mode = defaults.locomotion_mode

    return LoadResult(
        settings=DesktopSettings(
            locomotion_mode=locomotion_mode,
            pedal_calibration_enabled=_coerce_bool(
                raw.get(
                    "pedal_calibration_enabled",
                    defaults.pedal_calibration_enabled,
                )
            ),
            verbose_logging=_coerce_bool(
                raw.get("verbose_logging", defaults.verbose_logging)
            ),
            start_minimized=_coerce_bool(
                raw.get("start_minimized", defaults.start_minimized)
            ),
        )
    )


def save_settings(settings: DesktopSettings, path: Path | None = None) -> Path:
    target = path or config_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(_serialize_settings(settings), encoding="utf-8")
    return target


def _coerce_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return False


def _serialize_settings(settings: DesktopSettings) -> str:
    lines = [
        f'locomotion_mode = "{settings.locomotion_mode}"',
        f"pedal_calibration_enabled = {_format_bool(settings.pedal_calibration_enabled)}",
        f"verbose_logging = {_format_bool(settings.verbose_logging)}",
        f"start_minimized = {_format_bool(settings.start_minimized)}",
        "",
    ]
    return "\n".join(lines)


def _format_bool(value: bool) -> str:
    return "true" if value else "false"
