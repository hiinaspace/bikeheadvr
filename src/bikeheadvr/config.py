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
class SkatingConfig:
    debug_foot_overlay_enabled: bool = False
    debug_foot_overlay_length_m: float = 0.34
    debug_foot_overlay_y_offset_m: float = 0.035
    debug_ghost_overlay_enabled: bool = False
    debug_ghost_forward_m: float = 1.5
    debug_ghost_y_offset_m: float = 0.08
    debug_force_arrow_scale_m: float = 0.06
    debug_velocity_arrow_scale_m: float = 0.35
    debug_arrow_min_width_m: float = 0.12
    debug_arrow_max_width_m: float = 0.75
    contact_enter_m: float = 0.05
    contact_leave_m: float = 0.08
    contact_full_load_m: float = 0.02
    contact_tilt_full_load_deg: float = 10.0
    contact_tilt_zero_load_deg: float = 35.0
    tracker_velocity_blend: float = 0.0
    max_foot_speed_m_s: float = 10.0
    push_yaw_gain: float = 1.0
    passive_brake_speed_m_s: float = 0.25
    passive_brake_deadzone_deg: float = 35.0
    passive_brake_full_angle_deg: float = 80.0
    passive_brake_min_scale: float = 0.0
    landing_grace_s: float = 0.45
    landing_brake_min_scale: float = 0.0
    balance_load_enabled: bool = True
    balance_load_radius_m: float = 0.8
    balance_load_min: float = 0.75
    balance_load_max: float = 1.15
    recovery_relief_enabled: bool = True
    recovery_relief_foot_speed_m_s: float = 0.15
    recovery_relief_full_speed_m_s: float = 0.45
    recovery_relief_body_forward_min_m_s: float = -0.5
    recovery_relief_yaw_full_deg: float = 25.0
    recovery_relief_yaw_none_deg: float = 60.0
    recovery_relief_min_scale: float = 0.05
    forward_glide_preserve_enabled: bool = True
    forward_glide_preserve_min_speed_m_s: float = 0.12
    forward_glide_preserve_full_speed_m_s: float = 0.5
    forward_glide_preserve_yaw_full_deg: float = 25.0
    forward_glide_preserve_yaw_none_deg: float = 60.0
    forward_glide_preserve_min_scale: float = 0.0
    stop_snap_speed_m_s: float = 0.08
    stop_snap_yaw_rate_deg_s: float = 10.0
    stop_snap_hold_s: float = 0.35
    reorientation_recovery_enabled: bool = True
    reorientation_recovery_speed_m_s: float = 0.45
    reorientation_recovery_mismatch_deg: float = 45.0
    reorientation_recovery_skate_alignment_deg: float = 35.0
    reorientation_recovery_contact_load: float = 0.25
    reorientation_recovery_max_foot_speed_m_s: float = 0.2
    reorientation_recovery_perp_scale: float = 0.0
    steering_enabled: bool = True
    steering_roll_sign: float = -1.0
    steering_roll_deadzone_deg: float = 5.0
    steering_roll_full_deg: float = 20.0
    steering_min_speed_m_s: float = 0.15
    steering_full_speed_m_s: float = 1.2
    steering_yaw_rate_deg_s: float = 95.0
    steering_response_per_s: float = 8.0
    steering_min_load: float = 0.15
    steering_landing_grace_s: float = 0.25
    steering_landing_min_scale: float = 0.0
    longitudinal_drag_per_s: float = 0.18
    lateral_drag_per_s: float = 7.5
    coast_drag_per_s: float = 0.08
    angular_drag_per_s: float = 2.4
    torque_gain_per_s: float = 0.0
    max_speed_m_s: float = 3.0
    full_speed_m_s: float = 2.2
    max_yaw_rate_deg_s: float = 180.0
    dropout_grace_s: float = 0.25
    dropout_fall_s: float = 0.7
    playspace_yaw_deadzone_deg: float = 1.0


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
    skating: SkatingConfig = field(default_factory=SkatingConfig)
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
