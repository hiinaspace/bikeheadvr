from __future__ import annotations

import math
from dataclasses import dataclass, field

from .config import SkatingConfig, TrackerConfig
from .vr_runtime import DevicePose, HmdPose, TrackerPose


@dataclass(frozen=True)
class SkatingFootCalibration:
    serial: str
    side: str
    ground_y_m: float
    yaw_offset_deg: float
    baseline_right_m: float
    baseline_forward_m: float
    baseline_up: tuple[float, float, float] = (0.0, 0.0, 0.0)
    skate_forward_local: tuple[float, float, float] = (0.0, 0.0, 0.0)


@dataclass(frozen=True)
class SkatingCalibrationModel:
    center_x_m: float
    center_z_m: float
    yaw_deg: float
    standing_hmd_y_m: float
    feet: dict[str, SkatingFootCalibration]


@dataclass(frozen=True)
class SkatingFootEstimate:
    serial: str
    side: str
    grounded: bool
    contact_load: float
    skate_yaw_deg: float
    balance_load: float = 1.0
    force_load: float = 0.0
    recovery_scale: float = 1.0
    glide_preserve_scale: float = 1.0
    tilt_deg: float = 0.0
    force_right_m_s2: float = 0.0
    force_forward_m_s2: float = 0.0
    torque: float = 0.0


@dataclass(frozen=True)
class SkatingEstimate:
    horizontal: float = 0.0
    vertical: float = 0.0
    velocity_right_m_s: float = 0.0
    velocity_forward_m_s: float = 0.0
    speed_m_s: float = 0.0
    body_yaw_deg: float = 0.0
    yaw_rate_deg_s: float = 0.0
    crouch_m: float = 0.0
    trackers_ready: bool = False
    trackers_visible: int = 0
    grounded_feet: int = 0
    feet: dict[str, SkatingFootEstimate] = field(default_factory=dict)


@dataclass
class _FootState:
    grounded: bool = False
    last_world_x_m: float | None = None
    last_world_z_m: float | None = None
    last_time_s: float | None = None
    last_contact_load: float = 0.0
    landing_started_at: float | None = None


@dataclass
class _SkatingSimulationState:
    velocity_right_m_s: float = 0.0
    velocity_forward_m_s: float = 0.0
    body_yaw_deg: float = 0.0
    yaw_rate_deg_s: float = 0.0
    last_update_at: float | None = None
    last_hmd_yaw_deg: float | None = None
    dropout_started_at: float | None = None
    feet: dict[str, _FootState] = field(default_factory=dict)
    foot_debug: dict[str, SkatingFootEstimate] = field(default_factory=dict)


class SkatingEstimator:
    def __init__(self, tracker_config: TrackerConfig, config: SkatingConfig) -> None:
        self._tracker_config = tracker_config
        self._config = config
        self._model: SkatingCalibrationModel | None = None
        self._state = _SkatingSimulationState()

    @property
    def calibration(self) -> SkatingCalibrationModel | None:
        return self._model

    def reset(self) -> None:
        self._state = _SkatingSimulationState()

    def clear_calibration(self) -> None:
        self._model = None
        self.reset()

    def apply_calibration(self, model: SkatingCalibrationModel) -> None:
        self._model = model
        self.reset()
        for serial in model.feet:
            self._state.feet[serial] = _FootState()

    def update(
        self,
        now: float,
        hmd_pose: HmdPose | None,
        trackers: list[TrackerPose],
        *,
        output_hmd_pose: HmdPose | None = None,
        output_calibrated_yaw_deg: float | None = None,
        body_position: tuple[float, float, float] | None = None,
    ) -> SkatingEstimate:
        model = self._model
        delta_s = (
            0.0
            if self._state.last_update_at is None
            else max(0.0, min(0.1, now - self._state.last_update_at))
        )
        self._state.last_update_at = now

        if model is None or hmd_pose is None:
            self._damp_motion(delta_s, force=True)
            return self._estimate(
                hmd_pose=hmd_pose,
                output_hmd_pose=output_hmd_pose,
                output_calibrated_yaw_deg=output_calibrated_yaw_deg,
                trackers_ready=False,
                trackers_visible=len(trackers),
                grounded_feet=0,
            )

        known_trackers = [tracker for tracker in trackers if tracker.serial in model.feet]
        if len(known_trackers) < self._tracker_config.required_feet_count:
            return self._handle_dropout(
                now,
                delta_s,
                hmd_pose,
                len(known_trackers),
                output_hmd_pose=output_hmd_pose,
                output_calibrated_yaw_deg=output_calibrated_yaw_deg,
            )

        self._state.dropout_started_at = None
        body_world_position = body_position or hmd_pose.position
        body_right_m, body_forward_m = to_calibrated_local(
            body_world_position[0],
            body_world_position[2],
            model.center_x_m,
            model.center_z_m,
            model.yaw_deg,
        )
        foot_local_positions = {
            tracker.serial: to_calibrated_local(
                tracker.position[0],
                tracker.position[2],
                model.center_x_m,
                model.center_z_m,
                model.yaw_deg,
            )
            for tracker in known_trackers
        }
        balance_loads = _balance_loads(
            body_right_m,
            body_forward_m,
            foot_local_positions,
            self._config,
        )
        accel_right_m_s2 = 0.0
        accel_forward_m_s2 = 0.0
        torque = 0.0
        grounded_feet = 0

        for tracker in known_trackers:
            foot_model = model.feet[tracker.serial]
            foot_state = self._state.feet.setdefault(tracker.serial, _FootState())
            foot_right_m, foot_forward_m = foot_local_positions[tracker.serial]
            foot_velocity_right_m_s, foot_velocity_forward_m_s = _foot_velocity(
                foot_state,
                tracker.position[0],
                tracker.position[2],
                model.yaw_deg,
                now,
            )
            foot_velocity_right_m_s, foot_velocity_forward_m_s = (
                _blend_tracker_velocity(
                    foot_velocity_right_m_s,
                    foot_velocity_forward_m_s,
                    tracker,
                    model.yaw_deg,
                    self._config,
                )
            )
            foot_state.last_world_x_m = tracker.position[0]
            foot_state.last_world_z_m = tracker.position[2]
            foot_state.last_time_s = now
            was_grounded = foot_state.grounded
            foot_state.grounded = _contact_state(
                foot_state.grounded,
                tracker.position[1],
                foot_model.ground_y_m,
                self._config,
            )
            live_skate_yaw_deg = skate_world_yaw_deg(tracker, foot_model)
            skate_yaw_deg = _wrap_skate_axis_deg(
                live_skate_yaw_deg - model.yaw_deg
            )
            tilt_deg = tracker_tilt_deg(
                tracker,
                foot_model.baseline_up,
                model.yaw_deg,
                current_yaw_deg=live_skate_yaw_deg,
            )
            if foot_state.grounded:
                grounded_feet += 1
            contact_load = _contact_load(
                foot_state.grounded,
                tracker.position[1],
                foot_model.ground_y_m,
                tilt_deg,
                self._config,
            )
            balance_load = (
                balance_loads.get(tracker.serial, 1.0)
                if foot_state.grounded
                else 0.0
            )
            force_load = contact_load * balance_load
            _update_landing_state(foot_state, now, contact_load)
            force_right = 0.0
            force_forward = 0.0
            foot_torque = 0.0
            recovery_scale = 1.0
            glide_preserve_scale = 1.0
            if (
                foot_state.grounded
                and was_grounded
                and force_load > 0.0
                and delta_s > 0.0
            ):
                force_right, force_forward = _skate_force(
                    _force_skate_yaw_deg(skate_yaw_deg, self._config),
                    self._state.velocity_right_m_s,
                    self._state.velocity_forward_m_s,
                    self._state.yaw_rate_deg_s,
                    foot_velocity_right_m_s,
                    foot_velocity_forward_m_s,
                    foot_right_m - body_right_m,
                    foot_forward_m - body_forward_m,
                    self._config,
                )
                force_right *= force_load
                force_forward *= force_load
                brake_scale = _passive_brake_scale(
                    now,
                    foot_state,
                    _force_skate_yaw_deg(skate_yaw_deg, self._config),
                    self._state.velocity_right_m_s,
                    self._state.velocity_forward_m_s,
                    force_right,
                    force_forward,
                    self._config,
                )
                force_right *= brake_scale
                force_forward *= brake_scale
                recovery_scale = _recovery_brake_scale(
                    _force_skate_yaw_deg(skate_yaw_deg, self._config),
                    self._state.velocity_forward_m_s,
                    foot_velocity_forward_m_s,
                    force_forward,
                    self._config,
                )
                force_right *= recovery_scale
                force_forward *= recovery_scale
                glide_preserve_scale = _forward_glide_preserve_scale(
                    _force_skate_yaw_deg(skate_yaw_deg, self._config),
                    self._state.velocity_forward_m_s,
                    force_forward,
                    self._config,
                )
                force_forward *= glide_preserve_scale
                foot_torque = (
                    (foot_forward_m - body_forward_m) * force_right
                    - (foot_right_m - body_right_m) * force_forward
                )
                accel_right_m_s2 += force_right
                accel_forward_m_s2 += force_forward
                torque += foot_torque
            self._state.foot_debug[tracker.serial] = SkatingFootEstimate(
                serial=tracker.serial,
                side=foot_model.side,
                grounded=foot_state.grounded,
                contact_load=contact_load,
                balance_load=balance_load,
                force_load=force_load,
                recovery_scale=recovery_scale,
                glide_preserve_scale=glide_preserve_scale,
                skate_yaw_deg=skate_yaw_deg,
                tilt_deg=tilt_deg,
                force_right_m_s2=force_right,
                force_forward_m_s2=force_forward,
                torque=foot_torque,
            )

        self._state.velocity_right_m_s += accel_right_m_s2 * delta_s
        self._state.velocity_forward_m_s += accel_forward_m_s2 * delta_s
        self._state.yaw_rate_deg_s += (
            self._config.torque_gain_per_s * torque
            - self._config.angular_drag_per_s * self._state.yaw_rate_deg_s
        ) * delta_s
        self._state.yaw_rate_deg_s = _clamp(
            self._state.yaw_rate_deg_s,
            -self._config.max_yaw_rate_deg_s,
            self._config.max_yaw_rate_deg_s,
        )
        self._state.body_yaw_deg = _wrap_angle_deg(
            self._state.body_yaw_deg + self._state.yaw_rate_deg_s * delta_s
        )
        self._damp_motion(delta_s, force=False)
        self._clamp_speed()

        return self._estimate(
            hmd_pose=hmd_pose,
            output_hmd_pose=output_hmd_pose,
            output_calibrated_yaw_deg=output_calibrated_yaw_deg,
            trackers_ready=True,
            trackers_visible=len(known_trackers),
            grounded_feet=grounded_feet,
        )

    def _handle_dropout(
        self,
        now: float,
        delta_s: float,
        hmd_pose: HmdPose,
        visible_count: int,
        *,
        output_hmd_pose: HmdPose | None,
        output_calibrated_yaw_deg: float | None,
    ) -> SkatingEstimate:
        if self._state.dropout_started_at is None:
            self._state.dropout_started_at = now
        force = (
            now - self._state.dropout_started_at
        ) >= self._config.dropout_grace_s
        self._damp_motion(delta_s, force=force)
        return self._estimate(
            hmd_pose=hmd_pose,
            output_hmd_pose=output_hmd_pose,
            output_calibrated_yaw_deg=output_calibrated_yaw_deg,
            trackers_ready=False,
            trackers_visible=visible_count,
            grounded_feet=0,
        )

    def _estimate(
        self,
        hmd_pose: HmdPose | None,
        output_hmd_pose: HmdPose | None,
        output_calibrated_yaw_deg: float | None,
        trackers_ready: bool,
        trackers_visible: int,
        grounded_feet: int,
    ) -> SkatingEstimate:
        model = self._model
        axis_hmd_pose = output_hmd_pose or hmd_pose
        if model is None or axis_hmd_pose is None:
            horizontal = 0.0
            vertical = 0.0
        else:
            hmd_yaw_deg = self._stable_hmd_yaw_deg(axis_hmd_pose)
            horizontal, vertical = map_local_velocity_to_axes(
                self._state.velocity_right_m_s,
                self._state.velocity_forward_m_s,
                hmd_yaw_deg,
                (
                    model.yaw_deg
                    if output_calibrated_yaw_deg is None
                    else output_calibrated_yaw_deg
                ),
                self._config.full_speed_m_s,
            )
        if model is None or hmd_pose is None:
            crouch_m = 0.0
        else:
            crouch_m = max(0.0, model.standing_hmd_y_m - hmd_pose.position[1])

        speed_m_s = math.hypot(
            self._state.velocity_right_m_s,
            self._state.velocity_forward_m_s,
        )
        return SkatingEstimate(
            horizontal=horizontal,
            vertical=vertical,
            velocity_right_m_s=self._state.velocity_right_m_s,
            velocity_forward_m_s=self._state.velocity_forward_m_s,
            speed_m_s=speed_m_s,
            body_yaw_deg=self._state.body_yaw_deg,
            yaw_rate_deg_s=self._state.yaw_rate_deg_s,
            crouch_m=crouch_m,
            trackers_ready=trackers_ready,
            trackers_visible=trackers_visible,
            grounded_feet=grounded_feet,
            feet=dict(self._state.foot_debug),
        )

    def _stable_hmd_yaw_deg(self, hmd_pose: HmdPose) -> float:
        horizontal_magnitude = math.hypot(
            hmd_pose.direction[0],
            hmd_pose.direction[2],
        )
        if (
            horizontal_magnitude < 0.2
            and self._state.last_hmd_yaw_deg is not None
        ):
            return self._state.last_hmd_yaw_deg
        yaw_deg = _yaw_from_direction(hmd_pose.direction)
        self._state.last_hmd_yaw_deg = yaw_deg
        return yaw_deg

    def _damp_motion(self, delta_s: float, force: bool) -> None:
        if delta_s <= 0.0:
            return
        drag_per_s = self._config.coast_drag_per_s
        if force:
            drag_per_s += 1.0 / max(0.001, self._config.dropout_fall_s)
        factor = max(0.0, 1.0 - drag_per_s * delta_s)
        self._state.velocity_right_m_s *= factor
        self._state.velocity_forward_m_s *= factor
        yaw_factor = max(0.0, 1.0 - self._config.angular_drag_per_s * delta_s)
        self._state.yaw_rate_deg_s *= yaw_factor

    def _clamp_speed(self) -> None:
        speed_m_s = math.hypot(
            self._state.velocity_right_m_s,
            self._state.velocity_forward_m_s,
        )
        if speed_m_s <= self._config.max_speed_m_s or speed_m_s <= 0.0:
            return
        scale = self._config.max_speed_m_s / speed_m_s
        self._state.velocity_right_m_s *= scale
        self._state.velocity_forward_m_s *= scale


def build_skating_calibration(
    center_x_m: float,
    center_z_m: float,
    yaw_deg: float,
    hmd_pose: HmdPose,
    trackers: list[TrackerPose],
    required_feet_count: int,
) -> SkatingCalibrationModel | None:
    if len(trackers) < required_feet_count:
        return None
    selected = sorted(trackers, key=lambda tracker: tracker.position[1])[
        :required_feet_count
    ]
    feet: dict[str, SkatingFootCalibration] = {}
    by_lateral = sorted(
        selected,
        key=lambda tracker: to_calibrated_local(
            tracker.position[0],
            tracker.position[2],
            center_x_m,
            center_z_m,
            yaw_deg,
        )[0],
    )
    for index, tracker in enumerate(by_lateral):
        right_m, forward_m = to_calibrated_local(
            tracker.position[0],
            tracker.position[2],
            center_x_m,
            center_z_m,
            yaw_deg,
        )
        side = "left" if index == 0 else "right"
        yaw_offset_deg = _wrap_angle_deg(tracker_yaw_deg(tracker) - yaw_deg)
        feet[tracker.serial] = SkatingFootCalibration(
            serial=tracker.serial,
            side=side,
            ground_y_m=tracker.position[1],
            yaw_offset_deg=yaw_offset_deg,
            baseline_right_m=right_m,
            baseline_forward_m=forward_m,
            baseline_up=tracker_up(tracker),
            skate_forward_local=_local_vector_from_world(
                tracker.orientation,
                _forward_vector_from_yaw(yaw_deg),
            ),
        )
    return SkatingCalibrationModel(
        center_x_m=center_x_m,
        center_z_m=center_z_m,
        yaw_deg=yaw_deg,
        standing_hmd_y_m=hmd_pose.position[1],
        feet=feet,
    )


def infer_skating_body_position(
    hmd_pose: HmdPose | None,
    devices: list[DevicePose],
    selected_trackers: list[TrackerPose],
) -> tuple[float, float, float] | None:
    if hmd_pose is None:
        return None
    foot_serials = {tracker.serial for tracker in selected_trackers}
    hip_candidates = [
        device
        for device in devices
        if device.device_class_name == "GenericTracker"
        and device.serial not in foot_serials
    ]
    if not hip_candidates:
        return hmd_pose.position
    hip = max(hip_candidates, key=lambda device: device.position[1])
    return hip.position


def to_calibrated_local(
    world_x_m: float,
    world_z_m: float,
    center_x_m: float,
    center_z_m: float,
    yaw_deg: float,
) -> tuple[float, float]:
    delta_x_m = world_x_m - center_x_m
    delta_z_m = world_z_m - center_z_m
    yaw_rad = math.radians(yaw_deg)
    cos_yaw = math.cos(yaw_rad)
    sin_yaw = math.sin(yaw_rad)
    right_m = delta_x_m * cos_yaw - delta_z_m * sin_yaw
    forward_m = -(delta_x_m * sin_yaw + delta_z_m * cos_yaw)
    return right_m, forward_m


def vector_to_calibrated_local(
    world_x: float,
    world_z: float,
    yaw_deg: float,
) -> tuple[float, float]:
    yaw_rad = math.radians(yaw_deg)
    cos_yaw = math.cos(yaw_rad)
    sin_yaw = math.sin(yaw_rad)
    right = world_x * cos_yaw - world_z * sin_yaw
    forward = -(world_x * sin_yaw + world_z * cos_yaw)
    return right, forward


def tracker_yaw_deg(tracker: TrackerPose) -> float:
    forward = (
        -tracker.orientation[0][2],
        -tracker.orientation[1][2],
        -tracker.orientation[2][2],
    )
    return _yaw_from_direction(forward)


def skate_world_yaw_deg(
    tracker: TrackerPose,
    calibration: SkatingFootCalibration,
) -> float:
    if _vector_magnitude(calibration.skate_forward_local) > 0.0:
        forward = _matvec3(tracker.orientation, calibration.skate_forward_local)
        if math.hypot(forward[0], forward[2]) >= 0.001:
            return _yaw_from_direction(forward)
    return tracker_yaw_deg(tracker) - calibration.yaw_offset_deg


def tracker_up(tracker: TrackerPose) -> tuple[float, float, float]:
    return _normalize(
        (
            tracker.orientation[0][1],
            tracker.orientation[1][1],
            tracker.orientation[2][1],
        )
    )


def tracker_tilt_deg(
    tracker: TrackerPose,
    baseline_up: tuple[float, float, float],
    baseline_yaw_deg: float = 0.0,
    *,
    current_yaw_deg: float | None = None,
) -> float:
    if _vector_magnitude(baseline_up) <= 0.0:
        return 0.0
    current_up = tracker_up(tracker)
    yaw_delta_deg = (
        tracker_yaw_deg(tracker)
        if current_yaw_deg is None
        else current_yaw_deg
    ) - baseline_yaw_deg
    baseline = _normalize(rotate_world_y(baseline_up, yaw_delta_deg))
    dot = _clamp(
        current_up[0] * baseline[0]
        + current_up[1] * baseline[1]
        + current_up[2] * baseline[2],
        -1.0,
        1.0,
    )
    return math.degrees(math.acos(dot))


def rotate_world_y(
    vector: tuple[float, float, float],
    yaw_deg: float,
) -> tuple[float, float, float]:
    yaw_rad = math.radians(yaw_deg)
    cos_yaw = math.cos(yaw_rad)
    sin_yaw = math.sin(yaw_rad)
    return (
        vector[0] * cos_yaw + vector[2] * sin_yaw,
        vector[1],
        -vector[0] * sin_yaw + vector[2] * cos_yaw,
    )


def _forward_vector_from_yaw(yaw_deg: float) -> tuple[float, float, float]:
    yaw_rad = math.radians(yaw_deg)
    return (-math.sin(yaw_rad), 0.0, -math.cos(yaw_rad))


def _local_vector_from_world(
    orientation: tuple[
        tuple[float, float, float],
        tuple[float, float, float],
        tuple[float, float, float],
    ],
    world_vector: tuple[float, float, float],
) -> tuple[float, float, float]:
    return _normalize(
        (
            sum(orientation[row][0] * world_vector[row] for row in range(3)),
            sum(orientation[row][1] * world_vector[row] for row in range(3)),
            sum(orientation[row][2] * world_vector[row] for row in range(3)),
        )
    )


def _matvec3(
    matrix: tuple[
        tuple[float, float, float],
        tuple[float, float, float],
        tuple[float, float, float],
    ],
    vector: tuple[float, float, float],
) -> tuple[float, float, float]:
    return (
        sum(matrix[0][idx] * vector[idx] for idx in range(3)),
        sum(matrix[1][idx] * vector[idx] for idx in range(3)),
        sum(matrix[2][idx] * vector[idx] for idx in range(3)),
    )


def map_local_velocity_to_axes(
    velocity_right_m_s: float,
    velocity_forward_m_s: float,
    hmd_yaw_deg: float,
    calibrated_yaw_deg: float,
    full_speed_m_s: float,
) -> tuple[float, float]:
    scale = 1.0 / max(0.001, full_speed_m_s)
    right = velocity_right_m_s * scale
    forward = velocity_forward_m_s * scale
    yaw_delta_rad = math.radians(hmd_yaw_deg - calibrated_yaw_deg)
    horizontal = right * math.cos(yaw_delta_rad) + forward * math.sin(yaw_delta_rad)
    vertical = forward * math.cos(yaw_delta_rad) - right * math.sin(yaw_delta_rad)
    magnitude = max(1.0, abs(horizontal), abs(vertical))
    return horizontal / magnitude, vertical / magnitude


def _foot_velocity(
    foot_state: _FootState,
    world_x_m: float,
    world_z_m: float,
    heading_yaw_deg: float,
    now: float,
) -> tuple[float, float]:
    if (
        foot_state.last_world_x_m is None
        or foot_state.last_world_z_m is None
        or foot_state.last_time_s is None
    ):
        return 0.0, 0.0
    delta_s = max(0.0, now - foot_state.last_time_s)
    if delta_s <= 0.0:
        return 0.0, 0.0
    return vector_to_calibrated_local(
        (world_x_m - foot_state.last_world_x_m) / delta_s,
        (world_z_m - foot_state.last_world_z_m) / delta_s,
        heading_yaw_deg,
    )


def _blend_tracker_velocity(
    derived_right_m_s: float,
    derived_forward_m_s: float,
    tracker: TrackerPose,
    calibrated_yaw_deg: float,
    config: SkatingConfig,
) -> tuple[float, float]:
    tracker_speed_m_s = math.hypot(
        tracker.velocity_m_s[0],
        tracker.velocity_m_s[2],
    )
    if tracker_speed_m_s < 0.01:
        return _clamp_velocity(
            derived_right_m_s,
            derived_forward_m_s,
            config.max_foot_speed_m_s,
        )
    tracker_right_m_s, tracker_forward_m_s = vector_to_calibrated_local(
        tracker.velocity_m_s[0],
        tracker.velocity_m_s[2],
        calibrated_yaw_deg,
    )
    blend = _clamp(config.tracker_velocity_blend, 0.0, 1.0)
    return _clamp_velocity(
        derived_right_m_s * (1.0 - blend) + tracker_right_m_s * blend,
        derived_forward_m_s * (1.0 - blend) + tracker_forward_m_s * blend,
        config.max_foot_speed_m_s,
    )


def _clamp_velocity(
    right_m_s: float,
    forward_m_s: float,
    max_speed_m_s: float,
) -> tuple[float, float]:
    if max_speed_m_s <= 0.0:
        return right_m_s, forward_m_s
    speed_m_s = math.hypot(right_m_s, forward_m_s)
    if speed_m_s <= max_speed_m_s:
        return right_m_s, forward_m_s
    scale = max_speed_m_s / speed_m_s
    return right_m_s * scale, forward_m_s * scale


def _contact_state(
    currently_grounded: bool,
    foot_y_m: float,
    ground_y_m: float,
    config: SkatingConfig,
) -> bool:
    height_m = foot_y_m - ground_y_m
    if currently_grounded:
        return height_m <= config.contact_leave_m
    return height_m <= config.contact_enter_m


def _contact_load(
    grounded: bool,
    foot_y_m: float,
    ground_y_m: float,
    tilt_deg: float,
    config: SkatingConfig,
) -> float:
    if not grounded:
        return 0.0
    height_m = max(0.0, foot_y_m - ground_y_m)
    if height_m <= config.contact_full_load_m:
        height_load = 1.0
    else:
        fade_span_m = max(0.001, config.contact_leave_m - config.contact_full_load_m)
        progress = min(1.0, (height_m - config.contact_full_load_m) / fade_span_m)
        height_load = 1.0 - _smoothstep(progress)

    if tilt_deg <= config.contact_tilt_full_load_deg:
        tilt_load = 1.0
    elif tilt_deg >= config.contact_tilt_zero_load_deg:
        tilt_load = 0.0
    else:
        tilt_span_deg = max(
            0.001,
            config.contact_tilt_zero_load_deg - config.contact_tilt_full_load_deg,
        )
        progress = (tilt_deg - config.contact_tilt_full_load_deg) / tilt_span_deg
        tilt_load = 1.0 - _smoothstep(progress)
    return height_load * tilt_load


def _balance_loads(
    body_right_m: float,
    body_forward_m: float,
    foot_positions: dict[str, tuple[float, float]],
    config: SkatingConfig,
) -> dict[str, float]:
    if not config.balance_load_enabled or len(foot_positions) <= 1:
        return {serial: 1.0 for serial in foot_positions}
    radius_sq_m = max(0.001, config.balance_load_radius_m) ** 2
    weights: dict[str, float] = {}
    for serial, (foot_right_m, foot_forward_m) in foot_positions.items():
        distance_sq_m = (
            (foot_right_m - body_right_m) ** 2
            + (foot_forward_m - body_forward_m) ** 2
        )
        weights[serial] = 1.0 / (distance_sq_m + radius_sq_m)
    total_weight = sum(weights.values())
    if total_weight <= 0.0:
        return {serial: 1.0 for serial in foot_positions}
    foot_count = len(foot_positions)
    return {
        serial: _clamp(
            foot_count * weight / total_weight,
            config.balance_load_min,
            config.balance_load_max,
        )
        for serial, weight in weights.items()
    }


def _update_landing_state(
    foot_state: _FootState,
    now: float,
    contact_load: float,
) -> None:
    if contact_load <= 0.05:
        foot_state.landing_started_at = None
    elif foot_state.last_contact_load <= 0.15 < contact_load:
        foot_state.landing_started_at = now
    foot_state.last_contact_load = contact_load


def _skate_force(
    skate_yaw_deg: float,
    body_velocity_right_m_s: float,
    body_velocity_forward_m_s: float,
    yaw_rate_deg_s: float,
    foot_velocity_right_m_s: float,
    foot_velocity_forward_m_s: float,
    lever_right_m: float,
    lever_forward_m: float,
    config: SkatingConfig,
) -> tuple[float, float]:
    yaw_rate_rad_s = math.radians(yaw_rate_deg_s)
    contact_velocity_right_m_s = (
        body_velocity_right_m_s + yaw_rate_rad_s * lever_forward_m
    )
    contact_velocity_forward_m_s = (
        body_velocity_forward_m_s - yaw_rate_rad_s * lever_right_m
    )
    slip_right_m_s = contact_velocity_right_m_s + foot_velocity_right_m_s
    slip_forward_m_s = contact_velocity_forward_m_s + foot_velocity_forward_m_s
    yaw_rad = math.radians(skate_yaw_deg)
    skate_right = math.sin(yaw_rad)
    skate_forward = math.cos(yaw_rad)
    lateral_right = math.cos(yaw_rad)
    lateral_forward = -math.sin(yaw_rad)
    along = slip_right_m_s * skate_right + slip_forward_m_s * skate_forward
    lateral = slip_right_m_s * lateral_right + slip_forward_m_s * lateral_forward
    force_right = -(
        config.longitudinal_drag_per_s * along * skate_right
        + config.lateral_drag_per_s * lateral * lateral_right
    )
    force_forward = -(
        config.longitudinal_drag_per_s * along * skate_forward
        + config.lateral_drag_per_s * lateral * lateral_forward
    )
    return force_right, force_forward


def _passive_brake_scale(
    now: float,
    foot_state: _FootState,
    skate_yaw_deg: float,
    velocity_right_m_s: float,
    velocity_forward_m_s: float,
    force_right_m_s2: float,
    force_forward_m_s2: float,
    config: SkatingConfig,
) -> float:
    speed_m_s = math.hypot(velocity_right_m_s, velocity_forward_m_s)
    if speed_m_s < config.passive_brake_speed_m_s:
        return 1.0
    if force_right_m_s2 * velocity_right_m_s + force_forward_m_s2 * velocity_forward_m_s >= 0.0:
        return 1.0

    velocity_yaw_deg = math.degrees(math.atan2(velocity_right_m_s, velocity_forward_m_s))
    axis_diff_deg = abs(_wrap_skate_axis_deg(skate_yaw_deg - velocity_yaw_deg))
    scale = _axis_brake_scale(axis_diff_deg, config)

    if (
        foot_state.landing_started_at is not None
        and config.landing_grace_s > 0.0
        and axis_diff_deg < config.passive_brake_full_angle_deg
    ):
        age_s = max(0.0, now - foot_state.landing_started_at)
        if age_s < config.landing_grace_s:
            progress = _clamp(age_s / config.landing_grace_s, 0.0, 1.0)
            landing_scale = config.landing_brake_min_scale + (
                1.0 - config.landing_brake_min_scale
            ) * _smoothstep(progress)
            scale = min(scale, landing_scale)

    return _clamp(scale, 0.0, 1.0)


def _recovery_brake_scale(
    skate_yaw_deg: float,
    velocity_forward_m_s: float,
    foot_velocity_forward_m_s: float,
    force_forward_m_s2: float,
    config: SkatingConfig,
) -> float:
    if not config.recovery_relief_enabled:
        return 1.0
    if force_forward_m_s2 >= 0.0:
        return 1.0
    if velocity_forward_m_s < config.recovery_relief_body_forward_min_m_s:
        return 1.0
    intent_speed_m_s = foot_velocity_forward_m_s
    if intent_speed_m_s <= config.recovery_relief_foot_speed_m_s:
        return 1.0

    speed_span = max(
        0.001,
        config.recovery_relief_full_speed_m_s
        - config.recovery_relief_foot_speed_m_s,
    )
    speed_progress = _clamp(
        (intent_speed_m_s - config.recovery_relief_foot_speed_m_s)
        / speed_span,
        0.0,
        1.0,
    )

    abs_yaw_deg = abs(_wrap_skate_axis_deg(skate_yaw_deg))
    if abs_yaw_deg >= config.recovery_relief_yaw_none_deg:
        return 1.0
    if abs_yaw_deg <= config.recovery_relief_yaw_full_deg:
        yaw_progress = 1.0
    else:
        yaw_span = max(
            0.001,
            config.recovery_relief_yaw_none_deg
            - config.recovery_relief_yaw_full_deg,
        )
        yaw_progress = 1.0 - _smoothstep(
            (abs_yaw_deg - config.recovery_relief_yaw_full_deg) / yaw_span
        )

    relief = _smoothstep(speed_progress) * yaw_progress
    min_scale = _clamp(config.recovery_relief_min_scale, 0.0, 1.0)
    return 1.0 - relief * (1.0 - min_scale)


def _forward_glide_preserve_scale(
    skate_yaw_deg: float,
    velocity_forward_m_s: float,
    force_forward_m_s2: float,
    config: SkatingConfig,
) -> float:
    if not config.forward_glide_preserve_enabled:
        return 1.0
    if force_forward_m_s2 >= 0.0:
        return 1.0
    if velocity_forward_m_s <= config.forward_glide_preserve_min_speed_m_s:
        return 1.0

    speed_span = max(
        0.001,
        config.forward_glide_preserve_full_speed_m_s
        - config.forward_glide_preserve_min_speed_m_s,
    )
    speed_progress = _clamp(
        (velocity_forward_m_s - config.forward_glide_preserve_min_speed_m_s)
        / speed_span,
        0.0,
        1.0,
    )

    abs_yaw_deg = abs(_wrap_skate_axis_deg(skate_yaw_deg))
    if abs_yaw_deg >= config.forward_glide_preserve_yaw_none_deg:
        return 1.0
    if abs_yaw_deg <= config.forward_glide_preserve_yaw_full_deg:
        yaw_progress = 1.0
    else:
        yaw_span = max(
            0.001,
            config.forward_glide_preserve_yaw_none_deg
            - config.forward_glide_preserve_yaw_full_deg,
        )
        yaw_progress = 1.0 - _smoothstep(
            (abs_yaw_deg - config.forward_glide_preserve_yaw_full_deg) / yaw_span
        )

    relief = _smoothstep(speed_progress) * yaw_progress
    min_scale = _clamp(config.forward_glide_preserve_min_scale, 0.0, 1.0)
    return 1.0 - relief * (1.0 - min_scale)


def _axis_brake_scale(axis_diff_deg: float, config: SkatingConfig) -> float:
    minimum = _clamp(config.passive_brake_min_scale, 0.0, 1.0)
    if axis_diff_deg <= config.passive_brake_deadzone_deg:
        return minimum
    span_deg = max(
        0.001,
        config.passive_brake_full_angle_deg - config.passive_brake_deadzone_deg,
    )
    progress = _clamp(
        (axis_diff_deg - config.passive_brake_deadzone_deg) / span_deg,
        0.0,
        1.0,
    )
    return minimum + (1.0 - minimum) * _smoothstep(progress)


def _force_skate_yaw_deg(skate_yaw_deg: float, config: SkatingConfig) -> float:
    yaw_gain = max(0.0, config.push_yaw_gain)
    return _clamp(skate_yaw_deg * yaw_gain, -90.0, 90.0)


def _yaw_from_direction(direction: tuple[float, float, float]) -> float:
    return math.degrees(math.atan2(-direction[0], -direction[2]))


def _wrap_angle_deg(angle_deg: float) -> float:
    while angle_deg > 180.0:
        angle_deg -= 360.0
    while angle_deg <= -180.0:
        angle_deg += 360.0
    return angle_deg


def _wrap_skate_axis_deg(angle_deg: float) -> float:
    wrapped = _wrap_angle_deg(angle_deg)
    if wrapped > 90.0:
        wrapped -= 180.0
    elif wrapped < -90.0:
        wrapped += 180.0
    return wrapped


def _smoothstep(value: float) -> float:
    return value * value * (3.0 - 2.0 * value)


def _normalize(vector: tuple[float, float, float]) -> tuple[float, float, float]:
    magnitude = _vector_magnitude(vector)
    if magnitude <= 0.0:
        return (0.0, 1.0, 0.0)
    return (
        vector[0] / magnitude,
        vector[1] / magnitude,
        vector[2] / magnitude,
    )


def _vector_magnitude(vector: tuple[float, float, float]) -> float:
    return math.sqrt(sum(component * component for component in vector))


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return min(maximum, max(minimum, value))
