from __future__ import annotations

from pathlib import Path

from bikeheadvr.app import (
    RuntimeOptions,
    _skating_tracker_height_warning,
    build_runtime_config,
    parse_args,
)
from bikeheadvr.skating_estimation import (
    SkatingCalibrationModel,
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
            "--duration",
            "1.5",
        ]
    )

    assert args.locomotion_mode == "skating"
    assert args.skating_playspace_turn is True
    assert args.no_skating_playspace_turn is True
    assert args.skating_record_only is True
    assert args.skating_record_path == Path("skate.jsonl")
    assert args.skating_push_yaw_gain == 3.0
    assert args.skating_tracker_velocity_blend == 0.5
    assert args.skating_contact_leave_m == 0.07
    assert args.skating_contact_tilt_zero_load_deg == 30.0
    assert args.skating_balance_load_radius_m == 0.2
    assert args.skating_balance_load_min == 0.1
    assert args.skating_balance_load_max == 1.4
    assert args.skating_recovery_relief_min_scale == 0.2
    assert args.skating_forward_glide_preserve_min_scale == 0.3
    assert args.duration == 1.5


def test_runtime_options_default_to_skating_playspace_turn_disabled() -> None:
    options = RuntimeOptions(locomotion_mode="skating")

    assert options.skating_playspace_turn is False
    assert options.skating_record_only is False


def test_runtime_options_apply_skating_tuning_overrides() -> None:
    config = build_runtime_config(
        RuntimeOptions(
            locomotion_mode="skating",
            skating_push_yaw_gain=3.0,
            skating_tracker_velocity_blend=0.5,
            skating_contact_leave_m=0.07,
            skating_contact_tilt_zero_load_deg=30.0,
            skating_balance_load_radius_m=0.2,
            skating_balance_load_min=0.1,
            skating_balance_load_max=1.4,
            skating_recovery_relief_min_scale=0.2,
            skating_forward_glide_preserve_min_scale=0.3,
        )
    )

    assert config.skating.push_yaw_gain == 3.0
    assert config.skating.tracker_velocity_blend == 0.5
    assert config.skating.contact_leave_m == 0.07
    assert config.skating.contact_tilt_zero_load_deg == 30.0
    assert config.skating.balance_load_radius_m == 0.2
    assert config.skating.balance_load_min == 0.1
    assert config.skating.balance_load_max == 1.4
    assert config.skating.recovery_relief_min_scale == 0.2
    assert config.skating.forward_glide_preserve_min_scale == 0.3


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
