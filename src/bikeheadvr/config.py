from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class OverlayTextureConfig:
    width_px: int = 1024
    height_px: int = 512


@dataclass(frozen=True)
class OverlayPlacement:
    x_m: float = 0.0
    y_m: float = 1.45
    z_m: float = -2.0
    yaw_deg: float = 0.0
    pitch_deg: float = 0.0
    roll_deg: float = 0.0


@dataclass(frozen=True)
class OverlayConfig:
    key: str = "dev.bikeheadvr.overlay.main"
    name: str = "bikeheadvr Phase 1"
    width_m: float = 1.2
    alpha: float = 1.0
    texture: OverlayTextureConfig = OverlayTextureConfig()
    placement: OverlayPlacement = OverlayPlacement()


@dataclass(frozen=True)
class AppConfig:
    tick_hz: float = 30.0
    startup_banner: str = "bikeheadvr Phase 1 static overlay"
    overlay: OverlayConfig = OverlayConfig()
