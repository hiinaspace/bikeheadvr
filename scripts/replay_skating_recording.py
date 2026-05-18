from __future__ import annotations

import argparse
import csv
from dataclasses import replace
from pathlib import Path

from bikeheadvr.config import SkatingConfig
from bikeheadvr.skating_estimation import SkatingEstimate
from bikeheadvr.skating_recording import (
    SkatingReplaySample,
    load_skating_config_from_recording,
    replay_skating_recording,
)
from bikeheadvr.vr_runtime import DevicePose, HmdPose, TrackerPose


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Replay a bikeheadvr skating pose recording offline."
    )
    parser.add_argument("recording", type=Path)
    parser.add_argument("--csv-out", type=Path)
    parser.add_argument("--lateral-drag-per-s", type=float)
    parser.add_argument("--longitudinal-drag-per-s", type=float)
    parser.add_argument("--coast-drag-per-s", type=float)
    parser.add_argument("--contact-enter-m", type=float)
    parser.add_argument("--contact-full-load-m", type=float)
    parser.add_argument("--contact-leave-m", type=float)
    parser.add_argument("--contact-tilt-full-load-deg", type=float)
    parser.add_argument("--contact-tilt-zero-load-deg", type=float)
    parser.add_argument("--tracker-velocity-blend", type=float)
    parser.add_argument("--max-foot-speed-m-s", type=float)
    parser.add_argument("--push-yaw-gain", type=float)
    parser.add_argument("--passive-brake-speed-m-s", type=float)
    parser.add_argument("--passive-brake-deadzone-deg", type=float)
    parser.add_argument("--passive-brake-full-angle-deg", type=float)
    parser.add_argument("--passive-brake-min-scale", type=float)
    parser.add_argument("--landing-grace-s", type=float)
    parser.add_argument("--landing-brake-min-scale", type=float)
    parser.add_argument("--full-speed-m-s", type=float)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = _config_with_overrides(args)
    result = replay_skating_recording(args.recording, config=config)

    print(f"frames: {result.frame_count}")
    print(f"max replay vertical: {result.max_vertical:.3f}")
    print(f"max replay speed: {result.max_speed_m_s:.3f} m/s")
    recorded_max_speed = _recorded_max_speed(result.samples)
    if recorded_max_speed is not None:
        print(f"max recorded speed: {recorded_max_speed:.3f} m/s")

    if args.csv_out is not None:
        _write_csv(args.csv_out, result.samples)
        print(f"csv: {args.csv_out}")

    return 0


def _config_with_overrides(args: argparse.Namespace) -> SkatingConfig | None:
    overrides = {
        "lateral_drag_per_s": args.lateral_drag_per_s,
        "longitudinal_drag_per_s": args.longitudinal_drag_per_s,
        "coast_drag_per_s": args.coast_drag_per_s,
        "contact_enter_m": args.contact_enter_m,
        "contact_full_load_m": args.contact_full_load_m,
        "contact_leave_m": args.contact_leave_m,
        "contact_tilt_full_load_deg": args.contact_tilt_full_load_deg,
        "contact_tilt_zero_load_deg": args.contact_tilt_zero_load_deg,
        "tracker_velocity_blend": args.tracker_velocity_blend,
        "max_foot_speed_m_s": args.max_foot_speed_m_s,
        "push_yaw_gain": args.push_yaw_gain,
        "passive_brake_speed_m_s": args.passive_brake_speed_m_s,
        "passive_brake_deadzone_deg": args.passive_brake_deadzone_deg,
        "passive_brake_full_angle_deg": args.passive_brake_full_angle_deg,
        "passive_brake_min_scale": args.passive_brake_min_scale,
        "landing_grace_s": args.landing_grace_s,
        "landing_brake_min_scale": args.landing_brake_min_scale,
        "full_speed_m_s": args.full_speed_m_s,
    }
    active_overrides = {
        key: value for key, value in overrides.items() if value is not None
    }
    if not active_overrides:
        return None
    base = load_skating_config_from_recording(args.recording) or SkatingConfig()
    return replace(base, **active_overrides)


def _recorded_max_speed(samples: list[SkatingReplaySample]) -> float | None:
    speeds = [
        sample.recorded_estimate.speed_m_s
        for sample in samples
        if sample.recorded_estimate is not None
    ]
    if not speeds:
        return None
    return max(speeds)


def _write_csv(path: Path, samples: list[SkatingReplaySample]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "relative_s",
        "hmd_x_m",
        "hmd_y_m",
        "hmd_z_m",
        "hmd_vx_m_s",
        "hmd_vy_m_s",
        "hmd_vz_m_s",
        "hmd_ax_m_s2",
        "hmd_ay_m_s2",
        "hmd_az_m_s2",
        "hmd_avx_rad_s",
        "hmd_avy_rad_s",
        "hmd_avz_rad_s",
        "device_count",
        "generic_tracker_count",
        "controller_count",
        "hip_candidate_serial",
        "hip_candidate_x_m",
        "hip_candidate_y_m",
        "hip_candidate_z_m",
        "hip_candidate_vx_m_s",
        "hip_candidate_vy_m_s",
        "hip_candidate_vz_m_s",
        "horizontal",
        "vertical",
        "speed_m_s",
        "velocity_right_m_s",
        "velocity_forward_m_s",
        "body_yaw_deg",
        "yaw_rate_deg_s",
        "grounded_feet",
        "left_x_m",
        "left_y_m",
        "left_z_m",
        "left_vx_m_s",
        "left_vy_m_s",
        "left_vz_m_s",
        "left_ax_m_s2",
        "left_ay_m_s2",
        "left_az_m_s2",
        "left_avx_rad_s",
        "left_avy_rad_s",
        "left_avz_rad_s",
        "left_grounded",
        "left_contact_load",
        "left_skate_yaw_deg",
        "left_tilt_deg",
        "left_force_right_m_s2",
        "left_force_forward_m_s2",
        "left_torque",
        "right_x_m",
        "right_y_m",
        "right_z_m",
        "right_vx_m_s",
        "right_vy_m_s",
        "right_vz_m_s",
        "right_ax_m_s2",
        "right_ay_m_s2",
        "right_az_m_s2",
        "right_avx_rad_s",
        "right_avy_rad_s",
        "right_avz_rad_s",
        "right_grounded",
        "right_contact_load",
        "right_skate_yaw_deg",
        "right_tilt_deg",
        "right_force_right_m_s2",
        "right_force_forward_m_s2",
        "right_torque",
        "recorded_horizontal",
        "recorded_vertical",
        "recorded_speed_m_s",
        "recorded_grounded_feet",
    ]
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        previous: dict[str, tuple[float, tuple[float, float, float]]] = {}
        for sample in samples:
            estimate = sample.estimate
            recorded = sample.recorded_estimate
            left = _foot_by_side(estimate, "left")
            right = _foot_by_side(estimate, "right")
            left_pose = _tracker_by_side(sample, "left")
            right_pose = _tracker_by_side(sample, "right")
            hip_candidate = _hip_candidate(sample)
            hmd_accel = _acceleration(
                previous,
                "hmd",
                sample.relative_s,
                sample.hmd_pose.velocity_m_s,
            )
            left_accel = (
                None
                if left_pose is None
                else _acceleration(
                    previous,
                    "left",
                    sample.relative_s,
                    left_pose.velocity_m_s,
                )
            )
            right_accel = (
                None
                if right_pose is None
                else _acceleration(
                    previous,
                    "right",
                    sample.relative_s,
                    right_pose.velocity_m_s,
                )
            )
            writer.writerow(
                {
                    "relative_s": _fmt(sample.relative_s),
                    **_hmd_columns("hmd", sample.hmd_pose, hmd_accel),
                    "device_count": len(sample.devices),
                    "generic_tracker_count": _device_class_count(
                        sample,
                        "GenericTracker",
                    ),
                    "controller_count": _device_class_count(sample, "Controller"),
                    **_device_columns("hip_candidate", hip_candidate),
                    "horizontal": _fmt(estimate.horizontal),
                    "vertical": _fmt(estimate.vertical),
                    "speed_m_s": _fmt(estimate.speed_m_s),
                    "velocity_right_m_s": _fmt(estimate.velocity_right_m_s),
                    "velocity_forward_m_s": _fmt(estimate.velocity_forward_m_s),
                    "body_yaw_deg": _fmt(estimate.body_yaw_deg),
                    "yaw_rate_deg_s": _fmt(estimate.yaw_rate_deg_s),
                    "grounded_feet": estimate.grounded_feet,
                    **_tracker_columns("left", left_pose, left_accel),
                    "left_grounded": "" if left is None else int(left.grounded),
                    "left_contact_load": "" if left is None else _fmt(left.contact_load),
                    "left_skate_yaw_deg": "" if left is None else _fmt(left.skate_yaw_deg),
                    "left_tilt_deg": "" if left is None else _fmt(left.tilt_deg),
                    "left_force_right_m_s2": (
                        "" if left is None else _fmt(left.force_right_m_s2)
                    ),
                    "left_force_forward_m_s2": (
                        "" if left is None else _fmt(left.force_forward_m_s2)
                    ),
                    "left_torque": "" if left is None else _fmt(left.torque),
                    **_tracker_columns("right", right_pose, right_accel),
                    "right_grounded": "" if right is None else int(right.grounded),
                    "right_contact_load": "" if right is None else _fmt(right.contact_load),
                    "right_skate_yaw_deg": "" if right is None else _fmt(right.skate_yaw_deg),
                    "right_tilt_deg": "" if right is None else _fmt(right.tilt_deg),
                    "right_force_right_m_s2": (
                        "" if right is None else _fmt(right.force_right_m_s2)
                    ),
                    "right_force_forward_m_s2": (
                        "" if right is None else _fmt(right.force_forward_m_s2)
                    ),
                    "right_torque": "" if right is None else _fmt(right.torque),
                    "recorded_horizontal": (
                        "" if recorded is None else _fmt(recorded.horizontal)
                    ),
                    "recorded_vertical": (
                        "" if recorded is None else _fmt(recorded.vertical)
                    ),
                    "recorded_speed_m_s": (
                        "" if recorded is None else _fmt(recorded.speed_m_s)
                    ),
                    "recorded_grounded_feet": (
                        "" if recorded is None else recorded.grounded_feet
                    ),
                }
            )


def _foot_by_side(estimate: SkatingEstimate, side: str):
    for foot in estimate.feet.values():
        if foot.side == side:
            return foot
    return None


def _tracker_by_side(
    sample: SkatingReplaySample,
    side: str,
) -> TrackerPose | None:
    for serial, foot in sample.estimate.feet.items():
        if foot.side != side:
            continue
        for tracker in sample.trackers:
            if tracker.serial == serial:
                return tracker
    return None


def _hip_candidate(sample: SkatingReplaySample) -> DevicePose | None:
    selected_serials = {tracker.serial for tracker in sample.trackers}
    trackers = [
        device
        for device in sample.devices
        if device.device_class_name == "GenericTracker"
        and device.serial not in selected_serials
    ]
    if not trackers:
        trackers = [
            device
            for device in sample.devices
            if device.device_class_name == "GenericTracker"
        ]
    if not trackers:
        return None
    return min(trackers, key=lambda device: abs(device.position[1] - 0.9))


def _device_class_count(sample: SkatingReplaySample, device_class_name: str) -> int:
    return sum(
        1
        for device in sample.devices
        if device.device_class_name == device_class_name
    )


def _hmd_columns(
    prefix: str,
    pose: HmdPose,
    accel: tuple[float, float, float] | None,
) -> dict[str, str]:
    return {
        f"{prefix}_x_m": _fmt(pose.position[0]),
        f"{prefix}_y_m": _fmt(pose.position[1]),
        f"{prefix}_z_m": _fmt(pose.position[2]),
        f"{prefix}_vx_m_s": _fmt(pose.velocity_m_s[0]),
        f"{prefix}_vy_m_s": _fmt(pose.velocity_m_s[1]),
        f"{prefix}_vz_m_s": _fmt(pose.velocity_m_s[2]),
        f"{prefix}_ax_m_s2": "" if accel is None else _fmt(accel[0]),
        f"{prefix}_ay_m_s2": "" if accel is None else _fmt(accel[1]),
        f"{prefix}_az_m_s2": "" if accel is None else _fmt(accel[2]),
        f"{prefix}_avx_rad_s": _fmt(pose.angular_velocity_rad_s[0]),
        f"{prefix}_avy_rad_s": _fmt(pose.angular_velocity_rad_s[1]),
        f"{prefix}_avz_rad_s": _fmt(pose.angular_velocity_rad_s[2]),
    }


def _device_columns(prefix: str, pose: DevicePose | None) -> dict[str, str]:
    if pose is None:
        return {
            f"{prefix}_serial": "",
            f"{prefix}_x_m": "",
            f"{prefix}_y_m": "",
            f"{prefix}_z_m": "",
            f"{prefix}_vx_m_s": "",
            f"{prefix}_vy_m_s": "",
            f"{prefix}_vz_m_s": "",
        }
    return {
        f"{prefix}_serial": pose.serial,
        f"{prefix}_x_m": _fmt(pose.position[0]),
        f"{prefix}_y_m": _fmt(pose.position[1]),
        f"{prefix}_z_m": _fmt(pose.position[2]),
        f"{prefix}_vx_m_s": _fmt(pose.velocity_m_s[0]),
        f"{prefix}_vy_m_s": _fmt(pose.velocity_m_s[1]),
        f"{prefix}_vz_m_s": _fmt(pose.velocity_m_s[2]),
    }


def _tracker_columns(
    prefix: str,
    pose: TrackerPose | None,
    accel: tuple[float, float, float] | None,
) -> dict[str, str]:
    if pose is None:
        return {
            f"{prefix}_x_m": "",
            f"{prefix}_y_m": "",
            f"{prefix}_z_m": "",
            f"{prefix}_vx_m_s": "",
            f"{prefix}_vy_m_s": "",
            f"{prefix}_vz_m_s": "",
            f"{prefix}_ax_m_s2": "",
            f"{prefix}_ay_m_s2": "",
            f"{prefix}_az_m_s2": "",
            f"{prefix}_avx_rad_s": "",
            f"{prefix}_avy_rad_s": "",
            f"{prefix}_avz_rad_s": "",
        }
    return {
        f"{prefix}_x_m": _fmt(pose.position[0]),
        f"{prefix}_y_m": _fmt(pose.position[1]),
        f"{prefix}_z_m": _fmt(pose.position[2]),
        f"{prefix}_vx_m_s": _fmt(pose.velocity_m_s[0]),
        f"{prefix}_vy_m_s": _fmt(pose.velocity_m_s[1]),
        f"{prefix}_vz_m_s": _fmt(pose.velocity_m_s[2]),
        f"{prefix}_ax_m_s2": "" if accel is None else _fmt(accel[0]),
        f"{prefix}_ay_m_s2": "" if accel is None else _fmt(accel[1]),
        f"{prefix}_az_m_s2": "" if accel is None else _fmt(accel[2]),
        f"{prefix}_avx_rad_s": _fmt(pose.angular_velocity_rad_s[0]),
        f"{prefix}_avy_rad_s": _fmt(pose.angular_velocity_rad_s[1]),
        f"{prefix}_avz_rad_s": _fmt(pose.angular_velocity_rad_s[2]),
    }


def _acceleration(
    previous: dict[str, tuple[float, tuple[float, float, float]]],
    key: str,
    now_s: float,
    velocity_m_s: tuple[float, float, float],
) -> tuple[float, float, float] | None:
    prior = previous.get(key)
    previous[key] = (now_s, velocity_m_s)
    if prior is None:
        return None
    prior_s, prior_velocity = prior
    delta_s = now_s - prior_s
    if delta_s <= 0.0:
        return None
    return (
        (velocity_m_s[0] - prior_velocity[0]) / delta_s,
        (velocity_m_s[1] - prior_velocity[1]) / delta_s,
        (velocity_m_s[2] - prior_velocity[2]) / delta_s,
    )


def _fmt(value: float) -> str:
    return f"{value:.6f}"


if __name__ == "__main__":
    raise SystemExit(main())
