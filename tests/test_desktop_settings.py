from __future__ import annotations

import shutil
import uuid
from pathlib import Path

import pytest

from bikeheadvr.desktop_settings import (
    DesktopSettings,
    config_dir,
    load_settings,
    save_settings,
)


@pytest.fixture
def settings_dir() -> Path:
    root = Path(".pytest-tmp-fixtures")
    root.mkdir(exist_ok=True)
    path = root / f"case-{uuid.uuid4().hex}"
    path.mkdir()
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


def test_load_defaults_when_missing(settings_dir: Path) -> None:
    path = settings_dir / "config.toml"
    result = load_settings(path)
    assert result.settings == DesktopSettings()
    assert result.warning is None


def test_load_partial_config_uses_defaults(settings_dir: Path) -> None:
    path = settings_dir / "config.toml"
    path.write_text('locomotion_mode = "tracker"\n', encoding="utf-8")
    result = load_settings(path)
    assert result.settings == DesktopSettings(
        locomotion_mode="tracker",
        pedal_calibration_enabled=False,
        verbose_logging=False,
        start_minimized=False,
    )


def test_load_malformed_config_returns_warning(settings_dir: Path) -> None:
    path = settings_dir / "config.toml"
    path.write_text('locomotion_mode = "manual"\ninvalid = [\n', encoding="utf-8")
    result = load_settings(path)
    assert result.settings == DesktopSettings()
    assert result.warning is not None


def test_save_and_reload_round_trips(settings_dir: Path) -> None:
    settings = DesktopSettings(
        locomotion_mode="tracker",
        pedal_calibration_enabled=True,
        verbose_logging=True,
        start_minimized=True,
    )
    path = settings_dir / "config.toml"
    save_settings(settings, path)
    result = load_settings(path)
    assert result.settings == settings


def test_runtime_options_mapping() -> None:
    settings = DesktopSettings(
        locomotion_mode="tracker",
        pedal_calibration_enabled=True,
        verbose_logging=True,
    )
    options = settings.to_runtime_options(log_file=Path("bikeheadvr.log"))
    assert options.locomotion_mode == "tracker"
    assert options.pedal_calibration is True
    assert options.verbose is True
    assert options.log_file == Path("bikeheadvr.log")


def test_config_dir_uses_roaming_appdata(monkeypatch: pytest.MonkeyPatch) -> None:
    target = Path("C:/Users/test/AppData/Roaming/bikeheadvr")
    monkeypatch.setattr(
        "bikeheadvr.desktop_settings.user_config_path", lambda *args, **kwargs: target
    )
    assert config_dir() == target
