from __future__ import annotations

import math

import pytest

from bikeheadvr.config import SkatingConfig, TrackerConfig
from bikeheadvr.skating_estimation import (
    SkatingEstimator,
    build_skating_calibration,
    infer_skating_body_position,
    map_local_velocity_to_axes,
    tracker_tilt_deg,
)
from bikeheadvr.vr_runtime import DevicePose, HmdPose, TrackerPose


def hmd(yaw_deg: float = 0.0, y_m: float = 1.7) -> HmdPose:
    yaw_rad = math.radians(yaw_deg)
    return HmdPose(
        position=(0.0, y_m, 0.0),
        direction=(-math.sin(yaw_rad), 0.0, -math.cos(yaw_rad)),
    )


def hmd_at(
    right_m: float,
    forward_m: float,
    yaw_deg: float = 0.0,
    y_m: float = 1.7,
) -> HmdPose:
    yaw_rad = math.radians(yaw_deg)
    return HmdPose(
        position=(right_m, y_m, -forward_m),
        direction=(-math.sin(yaw_rad), 0.0, -math.cos(yaw_rad)),
    )


def tracker(
    serial: str,
    right_m: float,
    y_m: float,
    forward_m: float,
    yaw_deg: float = 0.0,
    device_index: int = 1,
    velocity_m_s: tuple[float, float, float] = (0.0, 0.0, 0.0),
    orientation: tuple[
        tuple[float, float, float],
        tuple[float, float, float],
        tuple[float, float, float],
    ]
    | None = None,
) -> TrackerPose:
    return TrackerPose(
        device_index=device_index,
        serial=serial,
        position=(right_m, y_m, -forward_m),
        orientation=orientation or orientation_from_yaw(yaw_deg),
        velocity_m_s=velocity_m_s,
    )


def orientation_from_yaw(
    yaw_deg: float,
) -> tuple[
    tuple[float, float, float],
    tuple[float, float, float],
    tuple[float, float, float],
]:
    yaw_rad = math.radians(yaw_deg)
    return (
        (math.cos(yaw_rad), 0.0, math.sin(yaw_rad)),
        (0.0, 1.0, 0.0),
        (-math.sin(yaw_rad), 0.0, math.cos(yaw_rad)),
    )


def orientation_from_pitch(
    pitch_deg: float,
) -> tuple[
    tuple[float, float, float],
    tuple[float, float, float],
    tuple[float, float, float],
]:
    pitch_rad = math.radians(pitch_deg)
    return (
        (1.0, 0.0, 0.0),
        (0.0, math.cos(pitch_rad), -math.sin(pitch_rad)),
        (0.0, math.sin(pitch_rad), math.cos(pitch_rad)),
    )


def orientation_from_yaw_pitch(
    yaw_deg: float,
    pitch_deg: float,
) -> tuple[
    tuple[float, float, float],
    tuple[float, float, float],
    tuple[float, float, float],
]:
    yaw = orientation_from_yaw(yaw_deg)
    pitch = orientation_from_pitch(pitch_deg)
    return tuple(
        tuple(sum(yaw[row][idx] * pitch[idx][col] for idx in range(3)) for col in range(3))
        for row in range(3)
    )


def heading_local_tracker(
    serial: str,
    right_m: float,
    y_m: float,
    forward_m: float,
    heading_yaw_deg: float,
    foot_yaw_deg: float,
    device_index: int,
) -> TrackerPose:
    yaw_rad = math.radians(heading_yaw_deg)
    world_x = right_m * math.cos(yaw_rad) - forward_m * math.sin(yaw_rad)
    world_z = -right_m * math.sin(yaw_rad) - forward_m * math.cos(yaw_rad)
    return TrackerPose(
        device_index=device_index,
        serial=serial,
        position=(world_x, y_m, world_z),
        orientation=orientation_from_yaw(heading_yaw_deg + foot_yaw_deg),
    )


def transformed_hmd(
    right_m: float,
    forward_m: float,
    heading_yaw_deg: float,
    *,
    x_offset_m: float,
    z_offset_m: float,
    local_yaw_deg: float = 0.0,
) -> HmdPose:
    x_m, z_m = transformed_xz(
        right_m,
        forward_m,
        heading_yaw_deg,
        x_offset_m=x_offset_m,
        z_offset_m=z_offset_m,
    )
    yaw_deg = heading_yaw_deg + local_yaw_deg
    yaw_rad = math.radians(yaw_deg)
    return HmdPose(
        position=(x_m, 1.7, z_m),
        direction=(-math.sin(yaw_rad), 0.0, -math.cos(yaw_rad)),
    )


def transformed_tracker(
    serial: str,
    right_m: float,
    y_m: float,
    forward_m: float,
    heading_yaw_deg: float,
    foot_yaw_deg: float,
    device_index: int,
    *,
    x_offset_m: float,
    z_offset_m: float,
) -> TrackerPose:
    x_m, z_m = transformed_xz(
        right_m,
        forward_m,
        heading_yaw_deg,
        x_offset_m=x_offset_m,
        z_offset_m=z_offset_m,
    )
    return TrackerPose(
        device_index=device_index,
        serial=serial,
        position=(x_m, y_m, z_m),
        orientation=orientation_from_yaw(heading_yaw_deg + foot_yaw_deg),
    )


def transformed_xz(
    right_m: float,
    forward_m: float,
    yaw_deg: float,
    *,
    x_offset_m: float,
    z_offset_m: float,
) -> tuple[float, float]:
    yaw_rad = math.radians(yaw_deg)
    return (
        x_offset_m + right_m * math.cos(yaw_rad) - forward_m * math.sin(yaw_rad),
        z_offset_m - right_m * math.sin(yaw_rad) - forward_m * math.cos(yaw_rad),
    )


def default_feet(yaw_deg: float = 0.0) -> list[TrackerPose]:
    return [
        tracker("left", -0.2, 0.0, 0.0, yaw_deg, 1),
        tracker("right", 0.2, 0.0, 0.0, yaw_deg, 2),
    ]


def device(
    serial: str,
    y_m: float,
    device_class_name: str = "GenericTracker",
) -> DevicePose:
    return DevicePose(
        device_index=10,
        serial=serial,
        device_class=3,
        device_class_name=device_class_name,
        controller_role=0,
        controller_role_name="Invalid",
        position=(0.1, y_m, -0.2),
        orientation=orientation_from_yaw(0.0),
    )


def calibrated_estimator(
    config: SkatingConfig | None = None,
    feet: list[TrackerPose] | None = None,
) -> SkatingEstimator:
    estimator = SkatingEstimator(TrackerConfig(required_feet_count=2), config or config_for_tests())
    model = build_skating_calibration(
        0.0,
        0.0,
        0.0,
        hmd(),
        feet or default_feet(),
        2,
    )
    assert model is not None
    estimator.apply_calibration(model)
    return estimator


def config_for_tests() -> SkatingConfig:
    return SkatingConfig(
        coast_drag_per_s=0.0,
        longitudinal_drag_per_s=0.1,
        lateral_drag_per_s=5.0,
        angular_drag_per_s=0.0,
        torque_gain_per_s=5.0,
        dropout_grace_s=0.2,
        dropout_fall_s=0.5,
    )


def warm_contact(estimator: SkatingEstimator, feet: list[TrackerPose]) -> None:
    estimator.update(0.0, hmd(), feet)
    estimator.update(0.1, hmd(), feet)


def test_skating_calibration_records_feet_and_yaw_offsets() -> None:
    feet = default_feet(yaw_deg=15.0)
    model = build_skating_calibration(0.0, 0.0, 0.0, hmd(), feet, 2)

    assert model is not None
    assert model.standing_hmd_y_m == pytest.approx(1.7)
    assert model.feet["left"].side == "left"
    assert model.feet["right"].side == "right"
    assert model.feet["left"].ground_y_m == pytest.approx(0.0)
    assert model.feet["left"].yaw_offset_deg == pytest.approx(15.0)


def test_contact_hysteresis_keeps_grounded_until_leave_height() -> None:
    estimator = calibrated_estimator()
    feet = default_feet()
    warm_contact(estimator, feet)

    still_grounded = [
        tracker("left", -0.2, 0.07, 0.0),
        tracker("right", 0.2, 0.0, 0.0),
    ]
    estimate = estimator.update(0.2, hmd(), still_grounded)
    assert estimate.grounded_feet == 2

    lifted = [
        tracker("left", -0.2, 0.11, 0.0),
        tracker("right", 0.2, 0.0, 0.0),
    ]
    estimate = estimator.update(0.3, hmd(), lifted)
    assert estimate.grounded_feet == 1


def test_estimate_reports_per_foot_grounding_and_skate_yaw() -> None:
    feet = default_feet(yaw_deg=15.0)
    estimator = calibrated_estimator(feet=feet)
    warm_contact(estimator, feet)

    turning_feet = [
        tracker("left", -0.2, 0.0, 0.0, 45.0),
        tracker("right", 0.2, 0.2, 0.0, 15.0),
    ]
    estimate = estimator.update(0.2, hmd(), turning_feet)

    assert estimate.feet["left"].grounded is True
    assert estimate.feet["left"].contact_load == pytest.approx(1.0)
    assert estimate.feet["left"].skate_yaw_deg == pytest.approx(30.0)
    assert estimate.feet["right"].grounded is False
    assert estimate.feet["right"].contact_load == pytest.approx(0.0)


def test_skate_yaw_is_an_axis_not_a_direction() -> None:
    estimator = calibrated_estimator()
    warm_contact(estimator, default_feet())

    backwards_same_axis = [
        tracker("left", -0.2, 0.0, 0.0, 180.0),
        tracker("right", 0.2, 0.0, 0.0, 0.0),
    ]
    estimate = estimator.update(0.2, hmd(), backwards_same_axis)

    assert estimate.feet["left"].skate_yaw_deg == pytest.approx(0.0)


def test_nearly_lifted_grounded_foot_has_reduced_braking_load() -> None:
    config = config_for_tests()
    estimator = calibrated_estimator(config=config)
    warm_contact(estimator, default_feet())
    estimator._state.velocity_forward_m_s = 1.0

    full_brake = [
        tracker("left", -0.2, 0.0, 0.0, 90.0),
        tracker("right", 0.2, 0.2, 0.0),
    ]
    full_estimate = estimator.update(0.2, hmd(), full_brake)

    estimator = calibrated_estimator(config=config)
    warm_contact(estimator, default_feet())
    estimator._state.velocity_forward_m_s = 1.0
    light_brake = [
        tracker("left", -0.2, 0.05, 0.0, 90.0),
        tracker("right", 0.2, 0.2, 0.0),
    ]
    light_estimate = estimator.update(0.2, hmd(), light_brake)

    assert light_estimate.feet["left"].grounded is True
    assert 0.0 < light_estimate.feet["left"].contact_load < 1.0
    assert light_estimate.velocity_forward_m_s > full_estimate.velocity_forward_m_s


def test_tilted_grounded_foot_has_reduced_contact_load() -> None:
    config = config_for_tests()
    estimator = calibrated_estimator(config=config)
    warm_contact(estimator, default_feet())
    estimator._state.velocity_forward_m_s = 1.0

    flat_brake = [
        tracker("left", -0.2, 0.0, 0.0, 90.0),
        tracker("right", 0.2, 0.2, 0.0),
    ]
    flat_estimate = estimator.update(0.2, hmd(), flat_brake)

    estimator = calibrated_estimator(config=config)
    warm_contact(estimator, default_feet())
    estimator._state.velocity_forward_m_s = 1.0
    tilted_brake = [
        tracker(
            "left",
            -0.2,
            0.0,
            0.0,
            orientation=orientation_from_yaw_pitch(90.0, 30.0),
        ),
        tracker("right", 0.2, 0.2, 0.0),
    ]
    tilted_estimate = estimator.update(0.2, hmd(), tilted_brake)

    assert 0.0 < tilted_estimate.feet["left"].contact_load < 1.0
    assert tilted_estimate.feet["left"].tilt_deg == pytest.approx(30.0)
    assert tilted_estimate.velocity_forward_m_s > flat_estimate.velocity_forward_m_s


def test_balance_load_shifts_toward_body_center() -> None:
    estimator = calibrated_estimator(
        config=SkatingConfig(
            coast_drag_per_s=0.0,
            longitudinal_drag_per_s=0.1,
            lateral_drag_per_s=5.0,
            angular_drag_per_s=0.0,
            torque_gain_per_s=5.0,
            balance_load_radius_m=0.3,
            balance_load_min=0.2,
            balance_load_max=1.6,
        )
    )
    warm_contact(estimator, default_feet())

    estimate = estimator.update(
        0.2,
        hmd(),
        default_feet(),
        body_position=(0.2, 1.0, 0.0),
    )

    assert estimate.feet["right"].balance_load > 1.0
    assert estimate.feet["left"].balance_load < 1.0
    assert estimate.feet["right"].force_load > estimate.feet["left"].force_load


def test_hip_tracker_is_preferred_body_position() -> None:
    feet = default_feet()

    position = infer_skating_body_position(
        hmd(),
        [
            device("left", 0.0),
            device("right", 0.0),
            device("hip", 0.9),
            device("controller", 1.2, "Controller"),
        ],
        feet,
    )

    assert position == pytest.approx((0.1, 0.9, -0.2))


def test_tracker_tilt_ignores_flat_yaw_rotation() -> None:
    baseline = tracker(
        "left",
        -0.2,
        0.0,
        0.0,
        orientation=orientation_from_yaw_pitch(45.0, 20.0),
    )
    yawed_flat = tracker(
        "left",
        -0.2,
        0.0,
        0.0,
        orientation=orientation_from_yaw_pitch(135.0, 20.0),
    )

    tilt = tracker_tilt_deg(
        yawed_flat,
        baseline_up=(
            baseline.orientation[0][1],
            baseline.orientation[1][1],
            baseline.orientation[2][1],
        ),
        baseline_yaw_deg=45.0,
    )

    assert tilt == pytest.approx(0.0, abs=0.001)


def test_lifted_foot_motion_applies_no_force() -> None:
    estimator = calibrated_estimator()
    warm_contact(estimator, default_feet())

    lifted_push = [
        tracker("left", -0.2, 0.2, -0.2, 90.0),
        tracker("right", 0.2, 0.2, 0.0),
    ]
    estimate = estimator.update(0.2, hmd(), lifted_push)
    assert abs(estimate.velocity_forward_m_s) < 0.001


def test_backward_sideways_push_accelerates_forward() -> None:
    estimator = calibrated_estimator()
    warm_contact(estimator, default_feet())

    pushing = [
        tracker("left", -0.2, 0.0, -0.1, 90.0),
        tracker("right", 0.2, 0.2, 0.0),
    ]
    estimate = estimator.update(0.2, hmd(), pushing)
    assert estimate.velocity_forward_m_s > 0.1
    assert estimate.vertical > 0.0
    assert estimate.feet["left"].force_forward_m_s2 > 0.0


def test_aligned_skates_coast_forward_without_sideways_drift() -> None:
    estimator = calibrated_estimator(config=config_for_tests())
    warm_contact(estimator, default_feet())
    estimator._state.velocity_forward_m_s = 1.0

    estimate = estimator.update(0.2, hmd(), default_feet())

    assert estimate.velocity_forward_m_s > 0.95
    assert abs(estimate.velocity_right_m_s) < 0.001
    assert abs(estimate.yaw_rate_deg_s) < 0.001
    assert estimate.vertical > 0.0
    assert abs(estimate.horizontal) < 0.001


def test_idealized_push_off_stays_in_calibrated_forward_frame() -> None:
    estimator = calibrated_estimator(config=config_for_tests())
    warm_contact(estimator, default_feet())

    pushing = [
        tracker("left", -0.2, 0.0, -0.2, 90.0),
        tracker("right", 0.2, 0.2, 0.0),
    ]
    estimate = estimator.update(0.2, hmd(), pushing)

    assert estimate.velocity_forward_m_s > 0.5
    assert abs(estimate.velocity_right_m_s) < 0.001
    assert estimate.vertical > 0.0
    assert abs(estimate.horizontal) < 0.001


def test_yawed_skates_with_right_shifted_com_create_turning_force_and_torque() -> None:
    config = SkatingConfig(
        coast_drag_per_s=0.0,
        longitudinal_drag_per_s=0.1,
        lateral_drag_per_s=5.0,
        angular_drag_per_s=0.0,
        torque_gain_per_s=5.0,
        dropout_grace_s=0.2,
        dropout_fall_s=0.5,
        push_yaw_gain=1.0,
        passive_brake_min_scale=1.0,
        landing_brake_min_scale=1.0,
    )
    estimator = calibrated_estimator(config=config)
    warm_contact(estimator, default_feet())
    estimator._state.velocity_forward_m_s = 1.0

    turning_feet = [
        tracker("left", -0.2, 0.0, 0.0, 20.0),
        tracker("right", 0.2, 0.0, 0.0, 20.0),
    ]
    estimate = estimator.update(0.2, hmd_at(0.3, 0.0), turning_feet)

    assert estimate.velocity_right_m_s > 0.1
    assert estimate.velocity_forward_m_s < 1.0
    assert estimate.yaw_rate_deg_s < 0.0
    assert estimate.body_yaw_deg < 0.0
    assert sum(foot.torque for foot in estimate.feet.values()) < 0.0


def test_skating_estimator_is_invariant_to_rigid_world_yaw_and_translation() -> None:
    config = SkatingConfig(
        coast_drag_per_s=0.0,
        longitudinal_drag_per_s=0.1,
        lateral_drag_per_s=5.0,
        angular_drag_per_s=0.0,
        torque_gain_per_s=5.0,
        dropout_grace_s=0.2,
        dropout_fall_s=0.5,
        push_yaw_gain=1.0,
        passive_brake_min_scale=1.0,
        landing_brake_min_scale=1.0,
    )
    heading_yaw_deg = 37.0
    x_offset_m = 1.4
    z_offset_m = -0.8

    base_feet = default_feet()
    transformed_feet = [
        transformed_tracker(
            "left",
            -0.2,
            0.0,
            0.0,
            heading_yaw_deg,
            0.0,
            1,
            x_offset_m=x_offset_m,
            z_offset_m=z_offset_m,
        ),
        transformed_tracker(
            "right",
            0.2,
            0.0,
            0.0,
            heading_yaw_deg,
            0.0,
            2,
            x_offset_m=x_offset_m,
            z_offset_m=z_offset_m,
        ),
    ]
    transformed_center = transformed_xz(
        0.0,
        0.0,
        heading_yaw_deg,
        x_offset_m=x_offset_m,
        z_offset_m=z_offset_m,
    )
    transformed_calibration = build_skating_calibration(
        transformed_center[0],
        transformed_center[1],
        heading_yaw_deg,
        transformed_hmd(
            0.0,
            0.0,
            heading_yaw_deg,
            x_offset_m=x_offset_m,
            z_offset_m=z_offset_m,
        ),
        transformed_feet,
        2,
    )
    assert transformed_calibration is not None

    base = calibrated_estimator(config=config, feet=base_feet)
    transformed = SkatingEstimator(TrackerConfig(required_feet_count=2), config)
    transformed.apply_calibration(transformed_calibration)
    warm_contact(base, base_feet)
    transformed.update(
        0.0,
        transformed_hmd(
            0.0,
            0.0,
            heading_yaw_deg,
            x_offset_m=x_offset_m,
            z_offset_m=z_offset_m,
        ),
        transformed_feet,
    )
    transformed.update(
        0.1,
        transformed_hmd(
            0.0,
            0.0,
            heading_yaw_deg,
            x_offset_m=x_offset_m,
            z_offset_m=z_offset_m,
        ),
        transformed_feet,
    )
    base._state.velocity_forward_m_s = 1.0
    transformed._state.velocity_forward_m_s = 1.0

    base_turning_feet = [
        tracker("left", -0.2, 0.0, 0.0, 25.0),
        tracker("right", 0.2, 0.0, 0.0, 25.0),
    ]
    transformed_turning_feet = [
        transformed_tracker(
            "left",
            -0.2,
            0.0,
            0.0,
            heading_yaw_deg,
            25.0,
            1,
            x_offset_m=x_offset_m,
            z_offset_m=z_offset_m,
        ),
        transformed_tracker(
            "right",
            0.2,
            0.0,
            0.0,
            heading_yaw_deg,
            25.0,
            2,
            x_offset_m=x_offset_m,
            z_offset_m=z_offset_m,
        ),
    ]

    base_estimate = base.update(0.2, hmd_at(0.3, 0.0), base_turning_feet)
    transformed_estimate = transformed.update(
        0.2,
        transformed_hmd(
            0.3,
            0.0,
            heading_yaw_deg,
            x_offset_m=x_offset_m,
            z_offset_m=z_offset_m,
        ),
        transformed_turning_feet,
    )

    assert transformed_estimate.velocity_right_m_s == pytest.approx(
        base_estimate.velocity_right_m_s
    )
    assert transformed_estimate.velocity_forward_m_s == pytest.approx(
        base_estimate.velocity_forward_m_s
    )
    assert transformed_estimate.yaw_rate_deg_s == pytest.approx(
        base_estimate.yaw_rate_deg_s
    )
    assert transformed_estimate.body_yaw_deg == pytest.approx(
        base_estimate.body_yaw_deg
    )
    assert transformed_estimate.horizontal == pytest.approx(base_estimate.horizontal)
    assert transformed_estimate.vertical == pytest.approx(base_estimate.vertical)
    for serial in ("left", "right"):
        assert transformed_estimate.feet[serial].skate_yaw_deg == pytest.approx(
            base_estimate.feet[serial].skate_yaw_deg
        )
        assert transformed_estimate.feet[serial].force_right_m_s2 == pytest.approx(
            base_estimate.feet[serial].force_right_m_s2
        )
        assert transformed_estimate.feet[serial].force_forward_m_s2 == pytest.approx(
            base_estimate.feet[serial].force_forward_m_s2
        )
        assert transformed_estimate.feet[serial].torque == pytest.approx(
            base_estimate.feet[serial].torque
        )


def test_hitched_tracker_frame_does_not_create_larger_push_than_regular_frames() -> None:
    config = config_for_tests()
    regular = calibrated_estimator(config=config)
    hitched = calibrated_estimator(config=config)
    warm_contact(regular, default_feet())
    warm_contact(hitched, default_feet())

    for index, foot_forward_m in enumerate((-0.04, -0.08, -0.12, -0.16, -0.2), start=1):
        regular_estimate = regular.update(
            0.1 + index * 0.05,
            hmd(),
            [
                tracker("left", -0.2, 0.0, foot_forward_m, 90.0),
                tracker("right", 0.2, 0.2, 0.0),
            ],
        )
    hitched_estimate = hitched.update(
        0.35,
        hmd(),
        [
            tracker("left", -0.2, 0.0, -0.2, 90.0),
            tracker("right", 0.2, 0.2, 0.0),
        ],
    )

    assert (
        hitched_estimate.velocity_forward_m_s
        <= regular_estimate.velocity_forward_m_s * 1.1
    )


def test_push_after_physical_turn_uses_fixed_tracking_space() -> None:
    estimator = calibrated_estimator()
    turned_feet = [
        heading_local_tracker("left", -0.2, 0.0, 0.0, 90.0, 0.0, 1),
        heading_local_tracker("right", 0.2, 0.0, 0.0, 90.0, 0.0, 2),
    ]
    estimator.update(0.0, hmd(90.0), turned_feet)
    estimator.update(0.1, hmd(90.0), turned_feet)

    pushing = [
        heading_local_tracker("left", -0.2, 0.0, -0.1, 90.0, 90.0, 1),
        heading_local_tracker("right", 0.2, 0.2, 0.0, 90.0, 0.0, 2),
    ]
    estimate = estimator.update(0.2, hmd(90.0), pushing)

    assert estimate.velocity_right_m_s < -0.1
    assert estimate.vertical > 0.0
    assert abs(estimate.horizontal) < 0.05


def test_looking_down_keeps_last_stable_hmd_yaw_for_output_axes() -> None:
    estimator = calibrated_estimator()
    warm_contact(estimator, default_feet())

    estimator.update(0.2, hmd(90.0), default_feet())
    estimator._state.velocity_forward_m_s = 1.0
    stable = estimator.update(0.2, hmd(90.0), default_feet())
    looking_down = HmdPose(
        position=(0.0, 1.7, 0.0),
        direction=(0.01, -0.999, 0.01),
    )
    estimate = estimator.update(0.2, looking_down, default_feet())

    assert estimate.horizontal == pytest.approx(stable.horizontal, abs=0.001)
    assert estimate.vertical == pytest.approx(stable.vertical, abs=0.001)


def test_steamvr_tracker_velocity_can_drive_push_impulse() -> None:
    estimator = calibrated_estimator(
        config=SkatingConfig(
            tracker_velocity_blend=1.0,
            coast_drag_per_s=0.0,
            longitudinal_drag_per_s=0.1,
            lateral_drag_per_s=5.0,
            angular_drag_per_s=0.0,
            torque_gain_per_s=5.0,
            dropout_grace_s=0.2,
            dropout_fall_s=0.5,
        )
    )
    warm_contact(estimator, default_feet())

    pushing = [
        tracker(
            "left",
            -0.2,
            0.0,
            0.0,
            90.0,
            velocity_m_s=(0.0, 0.0, 1.0),
        ),
        tracker("right", 0.2, 0.2, 0.0),
    ]
    estimate = estimator.update(0.2, hmd(), pushing)

    assert estimate.velocity_forward_m_s > 0.1
    assert estimate.vertical > 0.0


def test_derived_tracker_velocity_is_clamped_for_tracking_spikes() -> None:
    estimator = calibrated_estimator(
        config=SkatingConfig(
            coast_drag_per_s=0.0,
            longitudinal_drag_per_s=0.1,
            lateral_drag_per_s=5.0,
            angular_drag_per_s=0.0,
            torque_gain_per_s=5.0,
            dropout_grace_s=0.2,
            dropout_fall_s=0.5,
            max_foot_speed_m_s=1.0,
        )
    )
    warm_contact(estimator, default_feet())

    tracking_snap = [
        tracker("left", -0.2, 0.0, -2.0, 90.0),
        tracker("right", 0.2, 0.2, 0.0),
    ]
    estimate = estimator.update(0.2, hmd(), tracking_snap)

    assert 0.1 < estimate.velocity_forward_m_s < 1.0


def test_push_yaw_gain_amplifies_underreported_sideways_push() -> None:
    low_gain = calibrated_estimator(config=config_for_tests())
    high_gain = calibrated_estimator(
        config=SkatingConfig(
            coast_drag_per_s=0.0,
            longitudinal_drag_per_s=0.1,
            lateral_drag_per_s=5.0,
            angular_drag_per_s=0.0,
            torque_gain_per_s=5.0,
            dropout_grace_s=0.2,
            dropout_fall_s=0.5,
            push_yaw_gain=3.0,
        )
    )
    warm_contact(low_gain, default_feet())
    warm_contact(high_gain, default_feet())

    pushing = [
        tracker("left", -0.2, 0.0, -0.1, 20.0),
        tracker("right", 0.2, 0.2, 0.0),
    ]

    low_estimate = low_gain.update(0.2, hmd(), pushing)
    high_estimate = high_gain.update(0.2, hmd(), pushing)

    assert high_estimate.velocity_forward_m_s > low_estimate.velocity_forward_m_s


def test_stationary_sideways_skate_brakes_forward_velocity() -> None:
    estimator = calibrated_estimator()
    warm_contact(estimator, default_feet())
    estimator._state.velocity_forward_m_s = 1.0

    braking = [
        tracker("left", -0.2, 0.0, 0.0, 90.0),
        tracker("right", 0.2, 0.2, 0.0),
    ]
    estimate = estimator.update(0.2, hmd(), braking)
    assert estimate.velocity_forward_m_s < 1.0


def test_small_passive_yaw_error_brakes_less_than_sideways_skate() -> None:
    config = config_for_tests()
    aligned = calibrated_estimator(config=config)
    sideways = calibrated_estimator(config=config)
    warm_contact(aligned, default_feet())
    warm_contact(sideways, default_feet())
    aligned._state.velocity_forward_m_s = 1.0
    sideways._state.velocity_forward_m_s = 1.0

    aligned_estimate = aligned.update(
        0.2,
        hmd(),
        [
            tracker("left", -0.2, 0.0, 0.0, 10.0),
            tracker("right", 0.2, 0.2, 0.0),
        ],
    )
    sideways_estimate = sideways.update(
        0.2,
        hmd(),
        [
            tracker("left", -0.2, 0.0, 0.0, 70.0),
            tracker("right", 0.2, 0.2, 0.0),
        ],
    )

    assert aligned_estimate.velocity_forward_m_s > sideways_estimate.velocity_forward_m_s


def test_landing_grace_temporarily_softens_moderate_braking() -> None:
    config = SkatingConfig(
        coast_drag_per_s=0.0,
        longitudinal_drag_per_s=0.1,
        lateral_drag_per_s=5.0,
        angular_drag_per_s=0.0,
        torque_gain_per_s=5.0,
        dropout_grace_s=0.2,
        dropout_fall_s=0.5,
        push_yaw_gain=1.0,
        passive_brake_deadzone_deg=0.0,
        passive_brake_full_angle_deg=90.0,
        passive_brake_min_scale=1.0,
        landing_grace_s=0.5,
        landing_brake_min_scale=0.1,
    )

    early = _estimate_after_landing_at(config, 0.4)
    settled = _estimate_after_landing_at(config, 0.9)

    assert early.velocity_forward_m_s > settled.velocity_forward_m_s


def _estimate_after_landing_at(config: SkatingConfig, estimate_time_s: float):
    estimator = calibrated_estimator(config=config)
    warm_contact(estimator, default_feet())
    lifted = [
        tracker("left", -0.2, 0.2, 0.0, 45.0),
        tracker("right", 0.2, 0.2, 0.0),
    ]
    landed = [
        tracker("left", -0.2, 0.0, 0.0, 45.0),
        tracker("right", 0.2, 0.2, 0.0),
    ]
    estimator.update(0.2, hmd(), lifted)
    estimator.update(0.3, hmd(), landed)
    estimator._state.velocity_forward_m_s = 1.0
    return estimator.update(estimate_time_s, hmd(), landed)


def test_forward_sideways_push_can_drive_reverse() -> None:
    estimator = calibrated_estimator()
    warm_contact(estimator, default_feet())

    pushing = [
        tracker("left", -0.2, 0.0, 0.1, 90.0),
        tracker("right", 0.2, 0.2, 0.0),
    ]
    estimate = estimator.update(0.2, hmd(), pushing)
    assert estimate.velocity_forward_m_s < -0.1
    assert estimate.vertical < 0.0


def test_front_foot_lateral_force_turns_body_right() -> None:
    feet = [
        tracker("left", 0.0, 0.0, 0.5, 0.0, 1),
        tracker("right", 0.3, 0.2, 0.0, 0.0, 2),
    ]
    estimator = calibrated_estimator(feet=feet)
    warm_contact(estimator, feet)

    turning = [
        tracker("left", -0.1, 0.0, 0.5, 0.0, 1),
        tracker("right", 0.3, 0.2, 0.0, 0.0, 2),
    ]
    estimate = estimator.update(0.2, hmd(), turning)
    assert estimate.yaw_rate_deg_s > 0.0
    assert estimate.body_yaw_deg > 0.0


def test_head_yaw_compensation_rotates_velocity_to_vrchat_axes() -> None:
    horizontal, vertical = map_local_velocity_to_axes(
        velocity_right_m_s=0.0,
        velocity_forward_m_s=1.0,
        hmd_yaw_deg=90.0,
        calibrated_yaw_deg=0.0,
        full_speed_m_s=1.0,
    )

    assert horizontal == pytest.approx(1.0)
    assert abs(vertical) < 0.001


def test_output_frame_can_differ_from_physics_frame_for_axis_mapping() -> None:
    estimator = calibrated_estimator()
    warm_contact(estimator, default_feet())
    estimator._state.velocity_forward_m_s = 1.0

    estimate = estimator.update(
        0.2,
        hmd(0.0),
        default_feet(),
        output_hmd_pose=hmd(90.0),
        output_calibrated_yaw_deg=90.0,
    )

    assert estimate.vertical > 0.0
    assert abs(estimate.horizontal) < 0.001


def test_dropout_damps_existing_velocity_after_grace() -> None:
    estimator = calibrated_estimator()
    warm_contact(estimator, default_feet())
    estimator._state.velocity_forward_m_s = 1.0

    estimator.update(0.2, hmd(), [])
    estimate = estimator.update(0.5, hmd(), [])

    assert estimate.trackers_ready is False
    assert estimate.velocity_forward_m_s < 0.9
