from __future__ import annotations

import math
from dataclasses import dataclass, field

from .config import PedalEstimationConfig, TrackerConfig
from .vr_runtime import TrackerPose


@dataclass(frozen=True)
class BikeRelativeTrackerPose:
    device_index: int
    serial: str
    x_m: float
    y_m: float
    z_m: float


@dataclass(frozen=True)
class PedalCalibrationModel:
    center_y_m: float
    center_z_m: float
    orbit_radius_m: float


@dataclass(frozen=True)
class PedalCalibrationStatus:
    active: bool
    title_text: str | None = None
    subtitle_text: str | None = None
    completed_models: dict[str, PedalCalibrationModel] | None = None


@dataclass(frozen=True)
class PedalEstimate:
    magnitude: float
    cadence_hz: float
    trackers_ready: bool
    trackers_visible: int


@dataclass
class _TrackerPhaseState:
    center_y_m: float | None = None
    center_z_m: float | None = None
    last_phase_rad: float | None = None
    last_time_s: float | None = None


@dataclass
class _PedalCalibrationState:
    active: bool = False
    started_at: float | None = None
    samples_by_serial: dict[str, list[tuple[float, float]]] = field(
        default_factory=dict
    )


class PedalCalibrationController:
    def __init__(self, config: PedalEstimationConfig) -> None:
        self._config = config
        self._state = _PedalCalibrationState()

    def start(self, now: float) -> None:
        self._state = _PedalCalibrationState(active=True, started_at=now)

    def cancel(self) -> None:
        self._state = _PedalCalibrationState()

    def update(
        self,
        now: float,
        trackers: list[BikeRelativeTrackerPose],
    ) -> PedalCalibrationStatus:
        state = self._state
        if not state.active or state.started_at is None:
            return PedalCalibrationStatus(active=False)

        for tracker in trackers:
            state.samples_by_serial.setdefault(tracker.serial, []).append(
                (tracker.y_m, tracker.z_m)
            )

        elapsed_s = now - state.started_at
        remaining_s = max(0.0, self._config.calibration_duration_s - elapsed_s)
        if elapsed_s >= self._config.calibration_duration_s:
            models = _build_models(state.samples_by_serial, self._config)
            self._state = _PedalCalibrationState()
            return PedalCalibrationStatus(active=False, completed_models=models)

        seconds = max(1, int(math.ceil(remaining_s)))
        return PedalCalibrationStatus(
            active=True,
            title_text="PEDAL CAL",
            subtitle_text=f"PEDAL {seconds}",
        )


class PedalEstimator:
    def __init__(
        self,
        tracker_config: TrackerConfig,
        config: PedalEstimationConfig,
    ) -> None:
        self._tracker_config = tracker_config
        self._config = config
        self._models: dict[str, PedalCalibrationModel] = {}
        self._states: dict[str, _TrackerPhaseState] = {}
        self._dropout_started_at: float | None = None
        self._magnitude = 0.0
        self._last_update_at: float | None = None

    def reset(self) -> None:
        self._states.clear()
        self._dropout_started_at = None
        self._magnitude = 0.0
        self._last_update_at = None

    def apply_calibration(self, models: dict[str, PedalCalibrationModel]) -> None:
        self._models = dict(models)
        for serial, model in models.items():
            state = self._states.setdefault(serial, _TrackerPhaseState())
            state.center_y_m = model.center_y_m
            state.center_z_m = model.center_z_m
            state.last_phase_rad = None
            state.last_time_s = None

    def update(
        self,
        now: float,
        trackers: list[BikeRelativeTrackerPose],
    ) -> PedalEstimate:
        delta_s = (
            0.0
            if self._last_update_at is None
            else max(0.0, now - self._last_update_at)
        )
        self._last_update_at = now
        if len(trackers) < self._tracker_config.required_feet_count:
            return self._handle_dropout(now, delta_s, len(trackers))

        self._dropout_started_at = None
        cadences_hz: list[float] = []
        for tracker in trackers:
            cadence_hz = self._update_tracker_phase(now, tracker)
            if cadence_hz is not None:
                cadences_hz.append(cadence_hz)

        if len(cadences_hz) < self._tracker_config.required_feet_count:
            return self._handle_dropout(now, delta_s, len(trackers))

        cadence_hz = sum(cadences_hz) / len(cadences_hz)
        target_magnitude = _map_cadence_to_magnitude(cadence_hz, self._config)
        self._magnitude = _approach(
            self._magnitude,
            target_magnitude,
            self._config.magnitude_rise_s,
            self._config.magnitude_fall_s,
            delta_s,
            False,
        )
        return PedalEstimate(
            magnitude=self._magnitude,
            cadence_hz=cadence_hz,
            trackers_ready=True,
            trackers_visible=len(trackers),
        )

    def _handle_dropout(
        self,
        now: float,
        delta_s: float,
        visible_count: int,
    ) -> PedalEstimate:
        if self._dropout_started_at is None:
            self._dropout_started_at = now
        after_grace = (
            now - self._dropout_started_at
        ) >= self._tracker_config.dropout_grace_s
        target_magnitude = 0.0 if after_grace else self._magnitude
        self._magnitude = _approach(
            self._magnitude,
            target_magnitude,
            self._config.magnitude_rise_s,
            self._config.magnitude_fall_s,
            delta_s,
            True,
        )
        return PedalEstimate(
            magnitude=self._magnitude,
            cadence_hz=0.0,
            trackers_ready=False,
            trackers_visible=visible_count,
        )

    def _update_tracker_phase(
        self,
        now: float,
        tracker: BikeRelativeTrackerPose,
    ) -> float | None:
        state = self._states.setdefault(tracker.serial, _TrackerPhaseState())
        model = self._models.get(tracker.serial)
        dt = None if state.last_time_s is None else max(0.0, now - state.last_time_s)
        if model is not None:
            center_y_m = model.center_y_m
            center_z_m = model.center_z_m
            min_radius_m = max(
                self._config.min_orbit_radius_m, model.orbit_radius_m * 0.4
            )
        else:
            alpha = 1.0
            if dt is not None:
                alpha = min(1.0, dt / max(0.001, self._config.center_follow_s))
            center_y_m = _blend(state.center_y_m, tracker.y_m, alpha)
            center_z_m = _blend(state.center_z_m, tracker.z_m, alpha)
            state.center_y_m = center_y_m
            state.center_z_m = center_z_m
            min_radius_m = self._config.min_orbit_radius_m

        delta_y_m = tracker.y_m - center_y_m
        delta_z_m = tracker.z_m - center_z_m
        orbit_radius_m = math.hypot(delta_y_m, delta_z_m)
        phase_rad = math.atan2(delta_y_m, delta_z_m)

        cadence_hz: float | None = None
        if (
            dt is not None
            and dt > 0.0
            and orbit_radius_m >= min_radius_m
            and state.last_phase_rad is not None
        ):
            delta_phase_rad = _wrap_angle_rad(phase_rad - state.last_phase_rad)
            cadence_hz = abs(delta_phase_rad) / (2.0 * math.pi * dt)

        state.last_phase_rad = phase_rad
        state.last_time_s = now
        return cadence_hz


def infer_foot_trackers(
    trackers: list[TrackerPose],
    required_count: int,
) -> list[TrackerPose]:
    if len(trackers) < required_count:
        return []
    return sorted(trackers, key=lambda tracker: tracker.position[1])[:required_count]


def to_bike_relative_trackers(
    trackers: list[TrackerPose],
    center_x_m: float,
    center_z_m: float,
    yaw_deg: float,
) -> list[BikeRelativeTrackerPose]:
    yaw_rad = math.radians(yaw_deg)
    cos_yaw = math.cos(yaw_rad)
    sin_yaw = math.sin(yaw_rad)
    relative_trackers: list[BikeRelativeTrackerPose] = []
    for tracker in trackers:
        delta_x_m = tracker.position[0] - center_x_m
        delta_z_m = tracker.position[2] - center_z_m
        local_x_m = delta_x_m * cos_yaw - delta_z_m * sin_yaw
        local_z_m = delta_x_m * sin_yaw + delta_z_m * cos_yaw
        relative_trackers.append(
            BikeRelativeTrackerPose(
                device_index=tracker.device_index,
                serial=tracker.serial,
                x_m=local_x_m,
                y_m=tracker.position[1],
                z_m=local_z_m,
            )
        )
    return relative_trackers


def _build_models(
    samples_by_serial: dict[str, list[tuple[float, float]]],
    config: PedalEstimationConfig,
) -> dict[str, PedalCalibrationModel]:
    models: dict[str, PedalCalibrationModel] = {}
    for serial, samples in samples_by_serial.items():
        if len(samples) < config.min_samples:
            continue
        center_y_m = sum(sample[0] for sample in samples) / len(samples)
        center_z_m = sum(sample[1] for sample in samples) / len(samples)
        radii_m = [
            math.hypot(sample[0] - center_y_m, sample[1] - center_z_m)
            for sample in samples
        ]
        orbit_radius_m = sum(radii_m) / len(radii_m)
        if orbit_radius_m < config.min_orbit_radius_m:
            continue
        models[serial] = PedalCalibrationModel(
            center_y_m=center_y_m,
            center_z_m=center_z_m,
            orbit_radius_m=orbit_radius_m,
        )
    return models


def _approach(
    current: float,
    target: float,
    rise_s: float,
    fall_s: float,
    delta_s: float,
    force_fall: bool,
) -> float:
    if current == target:
        return current
    if delta_s <= 0.0:
        return current
    if force_fall or target < current:
        time_constant_s = max(0.001, fall_s)
    else:
        time_constant_s = max(0.001, rise_s)
    step = min(1.0, delta_s / time_constant_s)
    return current + (target - current) * step


def _blend(current: float | None, new_value: float, alpha: float) -> float:
    if current is None:
        return new_value
    return current + (new_value - current) * alpha


def _map_cadence_to_magnitude(
    cadence_hz: float,
    config: PedalEstimationConfig,
) -> float:
    if cadence_hz <= config.deadband_hz:
        return 0.0
    span_hz = max(0.001, config.full_speed_hz - config.deadband_hz)
    return min(1.0, (cadence_hz - config.deadband_hz) / span_hz)


def _wrap_angle_rad(angle_rad: float) -> float:
    while angle_rad > math.pi:
        angle_rad -= 2.0 * math.pi
    while angle_rad < -math.pi:
        angle_rad += 2.0 * math.pi
    return angle_rad
