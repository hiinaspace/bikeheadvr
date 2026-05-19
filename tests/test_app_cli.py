from __future__ import annotations

from pathlib import Path

import pytest

from bikeheadvr.app import (
    RuntimeOptions,
    _skating_playspace_yaw_offset_deg,
    _skating_tracker_height_warning,
    _skating_world_yaw_from_local_yaw,
    _standing_position_from_raw,
    _standing_vector_from_raw_yaw,
    _standing_yaw_from_raw_yaw,
    build_runtime_config,
    parse_args,
)
from bikeheadvr.skating_estimation import (
    SkatingCalibrationModel,
    SkatingEstimate,
    SkatingFootCalibration,
)


def test_parse_skating_mode_options() -> None:
    args = parse_args(
        [
            "--locomotion-mode",
            "skating",
            "--skating-playspace-turn",
            "--no-skating-playspace-turn",
            "--skating-record-only",
            "--skating-record-path",
            "skate.jsonl",
            "--skating-debug-overlays",
            "--skating-push-yaw-gain",
            "3",
            "--skating-tracker-velocity-blend",
            "0.5",
            "--skating-contact-leave-m",
            "0.07",
            "--skating-contact-tilt-zero-load-deg",
            "30",
            "--skating-balance-load-radius-m",
            "0.2",
            "--skating-balance-load-min",
            "0.1",
            "--skating-balance-load-max",
            "1.4",
            "--skating-recovery-relief-min-scale",
            "0.2",
            "--skating-forward-glide-preserve-min-scale",
            "0.3",
            "--skating-stop-snap-speed-m-s",
            "0.12",
            "--skating-stop-snap-hold-s",
            "0.25",
            "--skating-reorientation-recovery-speed-m-s",
            "0.55",
            "--skating-reorientation-recovery-max-foot-speed-m-s",
            "0.3",
            "--skating-reorientation-recovery-perp-scale",
            "0.1",
            "--skating-steering-roll-sign",
            "-1",
            "--skating-steering-roll-deadzone-deg",
            "7",
            "--skating-steering-roll-full-deg",
            "22",
            "--skating-steering-min-speed-m-s",
            "0.25",
            "--skating-steering-yaw-rate-deg-s",
            "80",
            "--duration",
            "1.5",
        ]
    )

    assert args.locomotion_mode == "skating"
    assert args.skating_playspace_turn is True
    assert args.no_skating_playspace_turn is True
    assert args.skating_record_only is True
    assert args.skating_record_path == Path("skate.jsonl")
    assert args.skating_debug_overlays is True
    assert args.skating_push_yaw_gain == 3.0
    assert args.skating_tracker_velocity_blend == 0.5
    assert args.skating_contact_leave_m == 0.07
    assert args.skating_contact_tilt_zero_load_deg == 30.0
    assert args.skating_balance_load_radius_m == 0.2
    assert args.skating_balance_load_min == 0.1
    assert args.skating_balance_load_max == 1.4
    assert args.skating_recovery_relief_min_scale == 0.2
    assert args.skating_forward_glide_preserve_min_scale == 0.3
    assert args.skating_stop_snap_speed_m_s == 0.12
    assert args.skating_stop_snap_hold_s == 0.25
    assert args.skating_reorientation_recovery_speed_m_s == 0.55
    assert args.skating_reorientation_recovery_max_foot_speed_m_s == 0.3
    assert args.skating_reorientation_recovery_perp_scale == 0.1
    assert args.skating_steering_roll_sign == -1.0
    assert args.skating_steering_roll_deadzone_deg == 7.0
    assert args.skating_steering_roll_full_deg == 22.0
    assert args.skating_steering_min_speed_m_s == 0.25
    assert args.skating_steering_yaw_rate_deg_s == 80.0
    assert args.duration == 1.5


def test_runtime_options_default_to_skating_playspace_turn_disabled() -> None:
    options = RuntimeOptions(locomotion_mode="skating")
    config = build_runtime_config(options)

    assert options.skating_playspace_turn is False
    assert options.skating_debug_overlays is None
    assert options.skating_record_only is False
    assert config.skating.debug_foot_overlay_enabled is False
    assert config.skating.debug_ghost_overlay_enabled is False
    assert config.skating.steering_roll_sign == -1.0


def test_runtime_options_apply_skating_tuning_overrides() -> None:
    config = build_runtime_config(
        RuntimeOptions(
            locomotion_mode="skating",
            skating_debug_overlays=True,
            skating_push_yaw_gain=3.0,
            skating_tracker_velocity_blend=0.5,
            skating_contact_leave_m=0.07,
            skating_contact_tilt_zero_load_deg=30.0,
            skating_balance_load_radius_m=0.2,
            skating_balance_load_min=0.1,
            skating_balance_load_max=1.4,
            skating_recovery_relief_min_scale=0.2,
            skating_forward_glide_preserve_min_scale=0.3,
            skating_stop_snap_speed_m_s=0.12,
            skating_stop_snap_hold_s=0.25,
            skating_reorientation_recovery_speed_m_s=0.55,
            skating_reorientation_recovery_max_foot_speed_m_s=0.3,
            skating_reorientation_recovery_perp_scale=0.1,
            skating_steering_roll_sign=-1.0,
            skating_steering_roll_deadzone_deg=7.0,
            skating_steering_roll_full_deg=22.0,
            skating_steering_min_speed_m_s=0.25,
            skating_steering_yaw_rate_deg_s=80.0,
        )
    )

    assert config.skating.debug_foot_overlay_enabled is True
    assert config.skating.debug_ghost_overlay_enabled is True
    assert config.skating.push_yaw_gain == 3.0
    assert config.skating.tracker_velocity_blend == 0.5
    assert config.skating.contact_leave_m == 0.07
    assert config.skating.contact_tilt_zero_load_deg == 30.0
    assert config.skating.balance_load_radius_m == 0.2
    assert config.skating.balance_load_min == 0.1
    assert config.skating.balance_load_max == 1.4
    assert config.skating.recovery_relief_min_scale == 0.2
    assert config.skating.forward_glide_preserve_min_scale == 0.3
    assert config.skating.stop_snap_speed_m_s == 0.12
    assert config.skating.stop_snap_hold_s == 0.25
    assert config.skating.reorientation_recovery_speed_m_s == 0.55
    assert config.skating.reorientation_recovery_max_foot_speed_m_s == 0.3
    assert config.skating.reorientation_recovery_perp_scale == 0.1
    assert config.skating.steering_roll_sign == -1.0
    assert config.skating.steering_roll_deadzone_deg == 7.0
    assert config.skating.steering_roll_full_deg == 22.0
    assert config.skating.steering_min_speed_m_s == 0.25
    assert config.skating.steering_yaw_rate_deg_s == 80.0


def test_skating_visual_yaw_converts_local_yaw_back_to_world_yaw() -> None:
    assert _skating_world_yaw_from_local_yaw(15.0, -30.0) == pytest.approx(45.0)
    assert _skating_world_yaw_from_local_yaw(15.0, 30.0) == pytest.approx(-15.0)


def test_skating_visuals_convert_raw_frame_to_current_standing_frame() -> None:
    raw_to_standing = (
        (0.0, 0.0, 1.0, 1.0),
        (0.0, 1.0, 0.0, 2.0),
        (-1.0, 0.0, 0.0, 3.0),
    )

    assert _standing_position_from_raw(
        (0.5, 0.25, -1.0),
        raw_to_standing,
    ) == pytest.approx((0.0, 2.25, 2.5))
    assert _standing_vector_from_raw_yaw(0.0, raw_to_standing) == pytest.approx(
        (-1.0, 0.0)
    )
    assert _standing_yaw_from_raw_yaw(0.0, raw_to_standing) == pytest.approx(90.0)


def test_skating_playspace_yaw_uses_corrected_body_yaw_sign() -> None:
    class FakeRuntime:
        def raw_yaw_to_standing_yaw(self, yaw_deg: float) -> float:
            return yaw_deg + 90.0

    model = SkatingCalibrationModel(
        center_x_m=0.0,
        center_z_m=0.0,
        yaw_deg=15.0,
        standing_hmd_y_m=1.7,
        feet={},
    )

    yaw_deg = _skating_playspace_yaw_offset_deg(
        FakeRuntime(),
        model,
        SkatingEstimate(body_yaw_deg=30.0),
    )

    assert yaw_deg == pytest.approx(-30.0)


def test_skating_playspace_yaw_falls_back_when_raw_transform_unavailable() -> None:
    class FakeRuntime:
        def raw_yaw_to_standing_yaw(self, _yaw_deg: float) -> None:
            return None

    model = SkatingCalibrationModel(
        center_x_m=0.0,
        center_z_m=0.0,
        yaw_deg=15.0,
        standing_hmd_y_m=1.7,
        feet={},
    )

    yaw_deg = _skating_playspace_yaw_offset_deg(
        FakeRuntime(),
        model,
        SkatingEstimate(body_yaw_deg=30.0),
    )

    assert yaw_deg == pytest.approx(-30.0)


def test_skating_tracker_height_warning_flags_mismatched_feet() -> None:
    model = SkatingCalibrationModel(
        center_x_m=0.0,
        center_z_m=0.0,
        yaw_deg=0.0,
        standing_hmd_y_m=1.7,
        feet={
            "left": SkatingFootCalibration(
                serial="left",
                side="left",
                ground_y_m=0.05,
                yaw_offset_deg=0.0,
                baseline_right_m=-0.2,
                baseline_forward_m=0.0,
            ),
            "right": SkatingFootCalibration(
                serial="right",
                side="right",
                ground_y_m=0.91,
                yaw_offset_deg=0.0,
                baseline_right_m=0.2,
                baseline_forward_m=0.0,
            ),
        },
    )

    warning = _skating_tracker_height_warning(model)

    assert warning is not None
    assert "0.86 m" in warning
