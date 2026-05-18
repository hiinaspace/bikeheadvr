from __future__ import annotations

import math
import tempfile
from pathlib import Path

import pytest

from bikeheadvr.config import SkatingConfig, TrackerConfig
from bikeheadvr.skating_estimation import SkatingEstimator, build_skating_calibration
from bikeheadvr.skating_recording import (
    SkatingRecordingWriter,
    device_pose_from_dict,
    device_pose_to_dict,
    hmd_pose_from_dict,
    hmd_pose_to_dict,
    load_skating_config_from_recording,
    load_skating_records,
    replay_skating_recording,
    tracker_pose_from_dict,
    tracker_pose_to_dict,
)
from bikeheadvr.vr_runtime import DevicePose, HmdPose, TrackerPose


def hmd() -> HmdPose:
    return HmdPose(
        position=(0.0, 1.7, 0.0),
        direction=(0.0, 0.0, -1.0),
        velocity_m_s=(0.1, 0.0, -0.2),
        angular_velocity_rad_s=(0.0, 0.3, 0.0),
    )


def tracker(
    serial: str,
    right_m: float,
    y_m: float,
    forward_m: float,
    yaw_deg: float = 0.0,
    velocity_m_s: tuple[float, float, float] = (0.0, 0.0, 0.0),
) -> TrackerPose:
    return TrackerPose(
        device_index=1 if serial == "left" else 2,
        serial=serial,
        position=(right_m, y_m, -forward_m),
        orientation=orientation_from_yaw(yaw_deg),
        velocity_m_s=velocity_m_s,
        angular_velocity_rad_s=(0.0, math.radians(yaw_deg), 0.0),
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


def default_feet() -> list[TrackerPose]:
    return [
        tracker("left", -0.2, 0.0, 0.0),
        tracker("right", 0.2, 0.0, 0.0),
    ]


def device(
    serial: str,
    y_m: float,
    device_class: int = 3,
    device_class_name: str = "GenericTracker",
    controller_role: int = 0,
    controller_role_name: str = "Invalid",
) -> DevicePose:
    return DevicePose(
        device_index=10,
        serial=serial,
        device_class=device_class,
        device_class_name=device_class_name,
        controller_role=controller_role,
        controller_role_name=controller_role_name,
        position=(0.0, y_m, 0.0),
        orientation=orientation_from_yaw(0.0),
        velocity_m_s=(0.0, 0.0, 0.1),
        angular_velocity_rad_s=(0.0, 0.1, 0.0),
    )


def test_pose_serialization_preserves_velocity_fields() -> None:
    hmd_pose = hmd()
    tracker_pose = tracker(
        "left",
        -0.2,
        0.03,
        0.1,
        velocity_m_s=(1.0, 2.0, 3.0),
    )

    assert hmd_pose_from_dict(hmd_pose_to_dict(hmd_pose)).velocity_m_s == (
        0.1,
        0.0,
        -0.2,
    )
    assert hmd_pose_from_dict(
        hmd_pose_to_dict(hmd_pose)
    ).angular_velocity_rad_s == pytest.approx((0.0, 0.3, 0.0))
    assert tracker_pose_from_dict(
        tracker_pose_to_dict(tracker_pose)
    ).velocity_m_s == pytest.approx((1.0, 2.0, 3.0))
    device_pose = device("hip", 0.9)
    assert device_pose_from_dict(
        device_pose_to_dict(device_pose)
    ).angular_velocity_rad_s == pytest.approx((0.0, 0.1, 0.0))


def test_skating_recording_round_trips_and_replays() -> None:
    config = SkatingConfig(
        coast_drag_per_s=0.0,
        longitudinal_drag_per_s=0.1,
        lateral_drag_per_s=5.0,
        angular_drag_per_s=0.0,
        torque_gain_per_s=5.0,
    )
    feet = default_feet()
    model = build_skating_calibration(0.0, 0.0, 0.0, hmd(), feet, 2)
    assert model is not None
    estimator = SkatingEstimator(TrackerConfig(required_feet_count=2), config)
    estimator.apply_calibration(model)
    estimator.update(0.0, hmd(), feet)

    pushing_feet = [
        tracker("left", -0.2, 0.0, -0.1, 90.0, velocity_m_s=(0.0, 0.0, 1.0)),
        tracker("right", 0.2, 0.2, 0.0),
    ]
    estimate = estimator.update(0.1, hmd(), pushing_feet)
    with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp_dir:
        path = Path(temp_dir) / "skating.jsonl"
        writer = SkatingRecordingWriter(path, config)
        segment_id = writer.start_segment(0.0, 10.0, model)
        writer.write_frame(
            relative_s=0.0,
            monotonic_s=10.0,
            hmd_pose=hmd(),
            trackers=feet,
            selected_trackers=feet,
            calibration=model,
            estimate=estimator.update(0.0, hmd(), feet),
            controls_visible=True,
            calibration_active=False,
            devices=[
                device("hip", 0.9),
                device("left_controller", 1.1, 2, "Controller", 1, "LeftHand"),
            ],
        )
        writer.write_frame(
            relative_s=0.1,
            monotonic_s=10.1,
            hmd_pose=hmd(),
            trackers=pushing_feet,
            selected_trackers=pushing_feet,
            calibration=model,
            estimate=estimate,
            controls_visible=True,
            calibration_active=False,
        )
        writer.close()

        records = load_skating_records(path)
        assert records[0]["type"] == "meta"
        assert records[1]["type"] == "calibration"
        assert records[1]["segment_id"] == segment_id
        assert records[2]["segment_id"] == segment_id
        assert records[2]["segment_relative_s"] == 0.0
        assert records[2]["hmd"]["velocity_m_s"] == [0.1, 0.0, -0.2]
        assert records[2]["devices"][0]["serial"] == "hip"
        assert records[2]["devices"][1]["controller_role_name"] == "LeftHand"
        assert records[3]["segment_relative_s"] == 0.1
        assert records[3]["trackers"][0]["velocity_m_s"] == [0.0, 0.0, 1.0]
        assert load_skating_config_from_recording(path) == config

        replay = replay_skating_recording(path, config=config)

        assert replay.frame_count == 2
        assert replay.samples[0].segment_id == segment_id
        assert replay.samples[1].segment_relative_s == 0.1
        assert replay.samples[1].hmd_pose.velocity_m_s == pytest.approx(
            (0.1, 0.0, -0.2)
        )
        assert replay.samples[1].trackers[0].velocity_m_s == pytest.approx(
            (0.0, 0.0, 1.0)
        )
        assert replay.samples[0].devices[0].serial == "hip"
        assert replay.max_speed_m_s > 0.0


def test_skating_recording_suffixless_path_expands_to_timestamped_jsonl() -> None:
    with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp_dir:
        template = Path(temp_dir) / "skate-push-left"
        writer = SkatingRecordingWriter(template, SkatingConfig())
        try:
            assert writer.path.parent == template.parent
            assert writer.path.name.startswith("skate-push-left-")
            assert writer.path.suffix == ".jsonl"
            assert writer.path.exists()
        finally:
            writer.close()
