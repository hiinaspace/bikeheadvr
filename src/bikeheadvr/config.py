from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class OverlayTextureConfig:
    width_px: int = 512
    height_px: int = 512


@dataclass(frozen=True)
class OverlayPlacement:
    x_m: float
    y_m: float
    z_m: float
    yaw_deg: float
    pitch_deg: float = 0.0
    roll_deg: float = 0.0


@dataclass(frozen=True)
class ButtonConfig:
    id: str
    label: str
    key: str
    width_m: float
    placement: OverlayPlacement
    texture: OverlayTextureConfig = field(default_factory=OverlayTextureConfig)
    alpha: float = 0.5
    shape: str = "roundrect"
    always_visible: bool = True


@dataclass(frozen=True)
class DwellConfig:
    onset_delay_s: float = 0.2
    commit_duration_s: float = 0.6
    cooldown_s: float = 0.5


@dataclass(frozen=True)
class RenderConfig:
    dwell_steps: int = 12
    cooldown_steps: int = 10


@dataclass(frozen=True)
class OscConfig:
    host: str = "127.0.0.1"
    port: int = 9000
    vertical_axis: float = 1.0
    backward_axis: float = -1.0
    turn_axis: float = 1.0
    no_pose_failsafe_s: float = 0.5


@dataclass(frozen=True)
class CalibrationConfig:
    countdown_s: float = 3.0
    sample_window_s: float = 0.6


@dataclass(frozen=True)
class LeanTurnConfig:
    deadzone_m: float = 0.05
    full_scale_m: float = 0.30


@dataclass(frozen=True)
class DriveRampConfig:
    accelerate_to_full_s: float = 3.0
    brake_to_zero_s: float = 0.5


@dataclass(frozen=True)
class TrackerConfig:
    required_feet_count: int = 2
    dropout_grace_s: float = 0.35


@dataclass(frozen=True)
class PedalEstimationConfig:
    startup_calibration_enabled: bool = False
    calibration_duration_s: float = 4.0
    deadband_hz: float = 0.2
    full_speed_hz: float = 1.2
    magnitude_rise_s: float = 0.3
    magnitude_fall_s: float = 0.6
    center_follow_s: float = 2.0
    min_orbit_radius_m: float = 0.04
    min_samples: int = 30


@dataclass(frozen=True)
class CalibrationMessageConfig:
    key: str = "dev.bikeheadvr.overlay.calibration_message"
    label: str = "Calibrate"
    width_m: float = 0.65
    placement: OverlayPlacement = field(
        default_factory=lambda: OverlayPlacement(
            x_m=0.0,
            y_m=0.05,
            z_m=-1.0,
            yaw_deg=0.0,
        )
    )


@dataclass(frozen=True)
class AppConfig:
    tick_hz: float = 45.0
    startup_banner: str = "bikeheadvr Phase 5 calibration"
    locomotion_mode: str = "manual"
    dwell: DwellConfig = field(default_factory=DwellConfig)
    render: RenderConfig = field(default_factory=RenderConfig)
    osc: OscConfig = field(default_factory=OscConfig)
    calibration: CalibrationConfig = field(default_factory=CalibrationConfig)
    lean_turn: LeanTurnConfig = field(default_factory=LeanTurnConfig)
    drive_ramp: DriveRampConfig = field(default_factory=DriveRampConfig)
    tracker: TrackerConfig = field(default_factory=TrackerConfig)
    pedal_estimation: PedalEstimationConfig = field(
        default_factory=PedalEstimationConfig
    )
    calibration_message: CalibrationMessageConfig = field(
        default_factory=CalibrationMessageConfig
    )
    buttons: tuple[ButtonConfig, ...] = field(default_factory=lambda: default_buttons())


def yaw_facing_origin(x_m: float, z_m: float) -> float:
    import math

    return math.degrees(math.atan2(-x_m, -z_m))


def default_buttons() -> tuple[ButtonConfig, ...]:
    return (
        ButtonConfig(
            id="toggle",
            label="Toggle",
            key="dev.bikeheadvr.overlay.toggle",
            width_m=0.35,
            placement=OverlayPlacement(
                x_m=0.0,
                y_m=0.01,
                z_m=0.0,
                yaw_deg=0.0,
                pitch_deg=-90.0,
            ),
            shape="circle",
        ),
        ButtonConfig(
            id="forward",
            label="Forward",
            key="dev.bikeheadvr.overlay.forward",
            width_m=0.52,
            placement=OverlayPlacement(
                x_m=0.0,
                y_m=2.5,
                z_m=-2.0,
                yaw_deg=0.0,
            ),
        ),
        ButtonConfig(
            id="stop",
            label="Stop",
            key="dev.bikeheadvr.overlay.stop",
            width_m=0.52,
            placement=OverlayPlacement(
                x_m=0.0,
                y_m=0.8,
                z_m=-2.0,
                yaw_deg=0.0,
            ),
        ),
        ButtonConfig(
            id="backward",
            label="Backward",
            key="dev.bikeheadvr.overlay.backward",
            width_m=0.7,
            placement=OverlayPlacement(
                x_m=0.0,
                y_m=1.35,
                z_m=2.0,
                yaw_deg=180.0,
            ),
        ),
    )
