from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import SkatingConfig, TrackerConfig
from .skating_estimation import (
    SkatingCalibrationModel,
    SkatingEstimate,
    SkatingEstimator,
)
from .vr_runtime import DevicePose, HmdPose, TrackerPose


@dataclass(frozen=True)
class SkatingReplaySample:
    relative_s: float
    segment_id: int | None
    segment_relative_s: float | None
    hmd_pose: HmdPose
    trackers: list[TrackerPose]
    devices: list[DevicePose]
    estimate: SkatingEstimate
    recorded_estimate: SkatingEstimate | None


@dataclass(frozen=True)
class SkatingReplayResult:
    samples: list[SkatingReplaySample]

    @property
    def max_vertical(self) -> float:
        if not self.samples:
            return 0.0
        return max(abs(sample.estimate.vertical) for sample in self.samples)

    @property
    def max_speed_m_s(self) -> float:
        if not self.samples:
            return 0.0
        return max(sample.estimate.speed_m_s for sample in self.samples)

    @property
    def frame_count(self) -> int:
        return len(self.samples)


class SkatingRecordingWriter:
    def __init__(self, path: Path, config: SkatingConfig) -> None:
        self._path = resolve_skating_recording_path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._file = self._path.open("w", encoding="utf-8")
        self._next_segment_id = 1
        self._active_segment_id: int | None = None
        self._segment_started_at_s: float | None = None
        self._write(
            {
                "type": "meta",
                "format": "bikeheadvr.skating_recording.v1",
                "skating_config": _skating_config_to_dict(config),
            }
        )

    @property
    def path(self) -> Path:
        return self._path

    def start_segment(
        self,
        relative_s: float,
        monotonic_s: float,
        calibration: SkatingCalibrationModel,
    ) -> int:
        segment_id = self._next_segment_id
        self._next_segment_id += 1
        self._active_segment_id = segment_id
        self._segment_started_at_s = relative_s
        self._write(
            {
                "type": "calibration",
                "segment_id": segment_id,
                "relative_s": relative_s,
                "monotonic_s": monotonic_s,
                "calibration": skating_calibration_to_dict(calibration),
            }
        )
        return segment_id

    def end_segment(
        self,
        relative_s: float,
        monotonic_s: float,
        reason: str,
    ) -> None:
        if self._active_segment_id is None:
            return
        self._write(
            {
                "type": "segment_end",
                "segment_id": self._active_segment_id,
                "relative_s": relative_s,
                "monotonic_s": monotonic_s,
                "reason": reason,
            }
        )
        self._active_segment_id = None
        self._segment_started_at_s = None

    def write_frame(
        self,
        relative_s: float,
        monotonic_s: float,
        hmd_pose: HmdPose | None,
        trackers: list[TrackerPose],
        selected_trackers: list[TrackerPose],
        calibration: SkatingCalibrationModel | None,
        estimate: SkatingEstimate,
        controls_visible: bool,
        calibration_active: bool,
        devices: list[DevicePose] | None = None,
        record_only: bool = False,
    ) -> None:
        segment_relative_s = (
            None
            if self._segment_started_at_s is None
            else relative_s - self._segment_started_at_s
        )
        self._write(
            {
                "type": "frame",
                "segment_id": self._active_segment_id,
                "relative_s": relative_s,
                "segment_relative_s": segment_relative_s,
                "monotonic_s": monotonic_s,
                "controls_visible": controls_visible,
                "calibration_active": calibration_active,
                "record_only": record_only,
                "hmd": None if hmd_pose is None else hmd_pose_to_dict(hmd_pose),
                "trackers": [tracker_pose_to_dict(tracker) for tracker in trackers],
                "devices": [
                    device_pose_to_dict(device) for device in (devices or [])
                ],
                "selected_tracker_serials": [
                    tracker.serial for tracker in selected_trackers
                ],
                "calibration": (
                    None
                    if calibration is None
                    else skating_calibration_to_dict(calibration)
                ),
                "estimate": skating_estimate_to_dict(estimate),
            }
        )

    def close(self) -> None:
        self._file.close()

    def _write(self, payload: dict[str, Any]) -> None:
        self._file.write(json.dumps(payload, separators=(",", ":")) + "\n")
        self._file.flush()


def replay_skating_recording(
    path: Path,
    config: SkatingConfig | None = None,
    tracker_config: TrackerConfig | None = None,
) -> SkatingReplayResult:
    resolved_tracker_config = tracker_config or TrackerConfig()
    estimator = SkatingEstimator(
        resolved_tracker_config,
        config or _load_config_from_recording(path) or SkatingConfig(),
    )
    active_calibration_key: tuple[str, ...] | None = None
    samples: list[SkatingReplaySample] = []

    for record in load_skating_records(path):
        if record.get("type") != "frame":
            continue
        calibration_record = record.get("calibration")
        hmd_record = record.get("hmd")
        if not isinstance(calibration_record, dict) or not isinstance(hmd_record, dict):
            continue

        calibration = skating_calibration_from_dict(calibration_record)
        calibration_key = _calibration_key(calibration)
        if active_calibration_key != calibration_key:
            estimator.apply_calibration(calibration)
            active_calibration_key = calibration_key

        trackers = [
            tracker_pose_from_dict(tracker)
            for tracker in record.get("trackers", [])
            if isinstance(tracker, dict)
        ]
        devices = [
            device_pose_from_dict(device)
            for device in record.get("devices", [])
            if isinstance(device, dict)
        ]
        selected_serials = set(record.get("selected_tracker_serials", []))
        selected_trackers = [
            tracker for tracker in trackers if tracker.serial in selected_serials
        ]
        if len(selected_trackers) < resolved_tracker_config.required_feet_count:
            selected_trackers = trackers
        hmd_pose = hmd_pose_from_dict(hmd_record)
        estimate = estimator.update(
            float(record["relative_s"]),
            hmd_pose,
            selected_trackers,
        )
        recorded_estimate = (
            skating_estimate_from_dict(record["estimate"])
            if isinstance(record.get("estimate"), dict)
            else None
        )
        samples.append(
            SkatingReplaySample(
                relative_s=float(record["relative_s"]),
                segment_id=_optional_int(record.get("segment_id")),
                segment_relative_s=_optional_float(
                    record.get("segment_relative_s")
                ),
                hmd_pose=hmd_pose,
                trackers=selected_trackers,
                devices=devices,
                estimate=estimate,
                recorded_estimate=recorded_estimate,
            )
        )

    return SkatingReplayResult(samples=samples)


def load_skating_records(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if not stripped:
                continue
            value = json.loads(stripped)
            if isinstance(value, dict):
                records.append(value)
    return records


def resolve_skating_recording_path(path: Path) -> Path:
    if path.suffix.lower() == ".jsonl":
        return path
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    candidate = path.with_name(f"{path.name}-{timestamp}.jsonl")
    if not candidate.exists():
        return candidate
    for index in range(1, 100):
        candidate = path.with_name(f"{path.name}-{timestamp}-{index:02d}.jsonl")
        if not candidate.exists():
            return candidate
    raise FileExistsError(f"Could not find available recording path for {path}")


def load_skating_config_from_recording(path: Path) -> SkatingConfig | None:
    return _load_config_from_recording(path)


def hmd_pose_to_dict(pose: HmdPose) -> dict[str, Any]:
    return {
        "position": list(pose.position),
        "direction": list(pose.direction),
        "orientation": [list(row) for row in pose.orientation],
        "velocity_m_s": list(pose.velocity_m_s),
        "angular_velocity_rad_s": list(pose.angular_velocity_rad_s),
    }


def hmd_pose_from_dict(raw: dict[str, Any]) -> HmdPose:
    return HmdPose(
        position=_tuple3(raw["position"]),
        direction=_tuple3(raw["direction"]),
        orientation=_orientation(raw.get("orientation")),
        velocity_m_s=_tuple3(raw.get("velocity_m_s", (0.0, 0.0, 0.0))),
        angular_velocity_rad_s=_tuple3(
            raw.get("angular_velocity_rad_s", (0.0, 0.0, 0.0))
        ),
    )


def tracker_pose_to_dict(pose: TrackerPose) -> dict[str, Any]:
    return {
        "device_index": pose.device_index,
        "serial": pose.serial,
        "position": list(pose.position),
        "orientation": [list(row) for row in pose.orientation],
        "velocity_m_s": list(pose.velocity_m_s),
        "angular_velocity_rad_s": list(pose.angular_velocity_rad_s),
    }


def tracker_pose_from_dict(raw: dict[str, Any]) -> TrackerPose:
    return TrackerPose(
        device_index=int(raw["device_index"]),
        serial=str(raw["serial"]),
        position=_tuple3(raw["position"]),
        orientation=_orientation(raw["orientation"]),
        velocity_m_s=_tuple3(raw.get("velocity_m_s", (0.0, 0.0, 0.0))),
        angular_velocity_rad_s=_tuple3(
            raw.get("angular_velocity_rad_s", (0.0, 0.0, 0.0))
        ),
    )


def device_pose_to_dict(pose: DevicePose) -> dict[str, Any]:
    return {
        "device_index": pose.device_index,
        "serial": pose.serial,
        "device_class": pose.device_class,
        "device_class_name": pose.device_class_name,
        "controller_role": pose.controller_role,
        "controller_role_name": pose.controller_role_name,
        "position": list(pose.position),
        "orientation": [list(row) for row in pose.orientation],
        "velocity_m_s": list(pose.velocity_m_s),
        "angular_velocity_rad_s": list(pose.angular_velocity_rad_s),
    }


def device_pose_from_dict(raw: dict[str, Any]) -> DevicePose:
    return DevicePose(
        device_index=int(raw["device_index"]),
        serial=str(raw["serial"]),
        device_class=int(raw.get("device_class", 0)),
        device_class_name=str(raw.get("device_class_name", "")),
        controller_role=int(raw.get("controller_role", 0)),
        controller_role_name=str(raw.get("controller_role_name", "")),
        position=_tuple3(raw["position"]),
        orientation=_orientation(raw.get("orientation")),
        velocity_m_s=_tuple3(raw.get("velocity_m_s", (0.0, 0.0, 0.0))),
        angular_velocity_rad_s=_tuple3(
            raw.get("angular_velocity_rad_s", (0.0, 0.0, 0.0))
        ),
    )


def skating_calibration_to_dict(model: SkatingCalibrationModel) -> dict[str, Any]:
    return {
        "center_x_m": model.center_x_m,
        "center_z_m": model.center_z_m,
        "yaw_deg": model.yaw_deg,
        "standing_hmd_y_m": model.standing_hmd_y_m,
        "feet": {
            serial: {
                "serial": foot.serial,
                "side": foot.side,
                "ground_y_m": foot.ground_y_m,
                "yaw_offset_deg": foot.yaw_offset_deg,
                "baseline_right_m": foot.baseline_right_m,
                "baseline_forward_m": foot.baseline_forward_m,
                "baseline_up": list(foot.baseline_up),
            }
            for serial, foot in model.feet.items()
        },
    }


def skating_calibration_from_dict(raw: dict[str, Any]) -> SkatingCalibrationModel:
    from .skating_estimation import SkatingFootCalibration

    return SkatingCalibrationModel(
        center_x_m=float(raw["center_x_m"]),
        center_z_m=float(raw["center_z_m"]),
        yaw_deg=float(raw["yaw_deg"]),
        standing_hmd_y_m=float(raw["standing_hmd_y_m"]),
        feet={
            serial: SkatingFootCalibration(
                serial=str(foot["serial"]),
                side=str(foot["side"]),
                ground_y_m=float(foot["ground_y_m"]),
                yaw_offset_deg=float(foot["yaw_offset_deg"]),
                baseline_right_m=float(foot["baseline_right_m"]),
                baseline_forward_m=float(foot["baseline_forward_m"]),
                baseline_up=_tuple3(foot.get("baseline_up", (0.0, 0.0, 0.0))),
            )
            for serial, foot in raw["feet"].items()
        },
    )


def skating_estimate_to_dict(estimate: SkatingEstimate) -> dict[str, Any]:
    return {
        "horizontal": estimate.horizontal,
        "vertical": estimate.vertical,
        "velocity_right_m_s": estimate.velocity_right_m_s,
        "velocity_forward_m_s": estimate.velocity_forward_m_s,
        "speed_m_s": estimate.speed_m_s,
        "body_yaw_deg": estimate.body_yaw_deg,
        "yaw_rate_deg_s": estimate.yaw_rate_deg_s,
        "crouch_m": estimate.crouch_m,
        "trackers_ready": estimate.trackers_ready,
        "trackers_visible": estimate.trackers_visible,
        "grounded_feet": estimate.grounded_feet,
        "feet": {
            serial: {
                "serial": foot.serial,
                "side": foot.side,
                "grounded": foot.grounded,
                "contact_load": foot.contact_load,
                "skate_yaw_deg": foot.skate_yaw_deg,
                "tilt_deg": foot.tilt_deg,
                "force_right_m_s2": foot.force_right_m_s2,
                "force_forward_m_s2": foot.force_forward_m_s2,
                "torque": foot.torque,
            }
            for serial, foot in estimate.feet.items()
        },
    }


def skating_estimate_from_dict(raw: dict[str, Any]) -> SkatingEstimate:
    from .skating_estimation import SkatingFootEstimate

    return SkatingEstimate(
        horizontal=float(raw["horizontal"]),
        vertical=float(raw["vertical"]),
        velocity_right_m_s=float(raw["velocity_right_m_s"]),
        velocity_forward_m_s=float(raw["velocity_forward_m_s"]),
        speed_m_s=float(raw["speed_m_s"]),
        body_yaw_deg=float(raw["body_yaw_deg"]),
        yaw_rate_deg_s=float(raw["yaw_rate_deg_s"]),
        crouch_m=float(raw["crouch_m"]),
        trackers_ready=bool(raw["trackers_ready"]),
        trackers_visible=int(raw["trackers_visible"]),
        grounded_feet=int(raw["grounded_feet"]),
        feet={
            serial: SkatingFootEstimate(
                serial=str(foot["serial"]),
                side=str(foot["side"]),
                grounded=bool(foot["grounded"]),
                contact_load=float(foot["contact_load"]),
                skate_yaw_deg=float(foot["skate_yaw_deg"]),
                tilt_deg=float(foot.get("tilt_deg", 0.0)),
                force_right_m_s2=float(foot.get("force_right_m_s2", 0.0)),
                force_forward_m_s2=float(foot.get("force_forward_m_s2", 0.0)),
                torque=float(foot.get("torque", 0.0)),
            )
            for serial, foot in raw.get("feet", {}).items()
        },
    )


def _load_config_from_recording(path: Path) -> SkatingConfig | None:
    for record in load_skating_records(path):
        if record.get("type") == "meta" and isinstance(record.get("skating_config"), dict):
            return SkatingConfig(**record["skating_config"])
    return None


def _skating_config_to_dict(config: SkatingConfig) -> dict[str, Any]:
    return {
        field: getattr(config, field)
        for field in SkatingConfig.__dataclass_fields__
    }


def _tuple3(raw: Any) -> tuple[float, float, float]:
    return (float(raw[0]), float(raw[1]), float(raw[2]))


def _optional_float(raw: Any) -> float | None:
    return None if raw is None else float(raw)


def _optional_int(raw: Any) -> int | None:
    return None if raw is None else int(raw)


def _orientation(
    raw: Any,
) -> tuple[
    tuple[float, float, float],
    tuple[float, float, float],
    tuple[float, float, float],
]:
    if raw is None:
        return ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
    return (_tuple3(raw[0]), _tuple3(raw[1]), _tuple3(raw[2]))


def _calibration_key(model: SkatingCalibrationModel) -> tuple[str, ...]:
    parts = [
        f"center={model.center_x_m:.4f},{model.center_z_m:.4f}",
        f"yaw={model.yaw_deg:.4f}",
    ]
    for serial, foot in sorted(model.feet.items()):
        parts.append(
            (
                f"{serial}:"
                f"{foot.ground_y_m:.4f}:"
                f"{foot.yaw_offset_deg:.4f}:"
                f"{foot.baseline_right_m:.4f}:"
                f"{foot.baseline_forward_m:.4f}:"
                f"{foot.baseline_up[0]:.4f}:"
                f"{foot.baseline_up[1]:.4f}:"
                f"{foot.baseline_up[2]:.4f}"
            )
        )
    return tuple(parts)
