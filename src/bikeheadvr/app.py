from __future__ import annotations

import argparse
import logging
import math
import signal
import sys
import threading
import time
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass, replace
from pathlib import Path

from .calibration import CalibrationController
from .config import AppConfig, ButtonConfig, OverlayPlacement
from .interaction import ButtonVisualState, DwellTracker
from .overlay_ui import (
    OverlayTexture,
    TextureVariant,
    build_button_texture,
    quantize_visual,
)
from .pedal_estimation import (
    BikeRelativeTrackerPose,
    PedalCalibrationController,
    PedalEstimate,
    PedalEstimator,
    infer_foot_trackers,
    to_bike_relative_trackers,
)
from .vr_runtime import (
    GazeRay,
    HmdPose,
    OverlayHandle,
    OverlayIntersection,
    RuntimeInitError,
    SteamVROverlayRuntime,
)
from .vrchat_osc import VRChatOscController

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class RuntimeOptions:
    duration: float = 0.0
    locomotion_mode: str = "manual"
    pedal_calibration: bool = False
    verbose: bool = False
    log_file: Path | None = None


@dataclass(frozen=True)
class RuntimeStatus:
    state: str
    message: str


StatusCallback = Callable[[RuntimeStatus], None]


@dataclass
class SceneButton:
    config: ButtonConfig
    overlay: OverlayHandle
    visual: ButtonVisualState = ButtonVisualState()
    texture_variant: TextureVariant | None = None
    title_text: str | None = None
    subtitle_text: str | None = None
    rendered_title_text: str | None = None
    rendered_subtitle_text: str | None = None


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="bikeheadvr development CLI")
    parser.add_argument("--duration", type=float, default=0.0)
    parser.add_argument(
        "--locomotion-mode",
        choices=("manual", "tracker"),
        default="manual",
    )
    parser.add_argument("--pedal-calibration", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    return parser.parse_args(argv)


def configure_logging(verbose: bool, log_file: Path | None = None) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")

    if not root_logger.handlers:
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(formatter)
        root_logger.addHandler(stream_handler)

    if log_file is None:
        return

    target = log_file.resolve()
    if any(
        isinstance(handler, logging.FileHandler)
        and Path(handler.baseFilename) == target
        for handler in root_logger.handlers
    ):
        return

    target.parent.mkdir(parents=True, exist_ok=True)
    file_handler = logging.FileHandler(target, encoding="utf-8")
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)


def build_runtime_config(options: RuntimeOptions) -> AppConfig:
    base_config = AppConfig()
    return replace(
        base_config,
        locomotion_mode=options.locomotion_mode,
        pedal_estimation=replace(
            base_config.pedal_estimation,
            startup_calibration_enabled=(
                options.pedal_calibration
                or base_config.pedal_estimation.startup_calibration_enabled
            ),
        ),
    )


def run_session(
    options: RuntimeOptions,
    stop_event: threading.Event | None = None,
    status_callback: StatusCallback | None = None,
) -> int:
    configure_logging(options.verbose, options.log_file)

    def publish(state: str, message: str) -> None:
        LOGGER.info("%s", message)
        if status_callback is not None:
            status_callback(RuntimeStatus(state=state, message=message))

    config = build_runtime_config(options)
    runtime = SteamVROverlayRuntime(tick_hz=config.tick_hz)
    osc = VRChatOscController(config.osc)
    calibration = CalibrationController(config.calibration)
    pedal_calibration = PedalCalibrationController(config.pedal_estimation)
    pedal_estimator = PedalEstimator(config.tracker, config.pedal_estimation)
    active_buttons = _active_buttons(config)
    dwell = DwellTracker([button.id for button in active_buttons], config.dwell)
    shutdown_requested = False
    frames_remaining = (
        None
        if options.duration <= 0
        else max(1, int(round(options.duration * config.tick_hz)))
    )
    scene_buttons: dict[str, SceneButton] = {}
    calibration_overlay: SceneButton | None = None
    texture_cache: dict[
        tuple[str, TextureVariant, str | None, str | None], OverlayTexture
    ] = {}
    current_hover_id: str | None = None
    controls_visible = False
    calibrated_center_x_m = 0.0
    calibrated_center_z_m = 0.0
    calibrated_yaw_deg = 0.0
    latched_drive_id: str | None = None
    drive_adjust_id: str | None = None
    drive_magnitude = 0.0
    last_frame_at: float | None = None
    no_pose_started_at: float | None = None
    tracker_estimate = PedalEstimate(
        magnitude=0.0,
        cadence_hz=0.0,
        trackers_ready=False,
        trackers_visible=0,
    )

    def request_stop(signum: int, _frame: object) -> None:
        nonlocal shutdown_requested
        LOGGER.info("Received signal %s, shutting down.", signum)
        shutdown_requested = True
        if stop_event is not None:
            stop_event.set()

    for signum in (signal.SIGINT, signal.SIGTERM):
        with suppress(ValueError):
            signal.signal(signum, request_stop)

    try:
        publish("starting", config.startup_banner)
        runtime.initialize()

        for button in active_buttons:
            overlay = runtime.create_overlay(button)
            scene_button = SceneButton(config=button, overlay=overlay)
            scene_buttons[button.id] = scene_button
            _apply_visual(
                runtime, config, texture_cache, scene_button, ButtonVisualState()
            )
            runtime.set_visible(overlay, button.always_visible)

        calibration_overlay_config = ButtonConfig(
            id="calibration_message",
            label=config.calibration_message.label,
            key=config.calibration_message.key,
            width_m=config.calibration_message.width_m,
            placement=config.calibration_message.placement,
            always_visible=False,
        )
        calibration_overlay = SceneButton(
            config=calibration_overlay_config,
            overlay=runtime.create_overlay(calibration_overlay_config),
            visual=ButtonVisualState(hovered=True),
            title_text="CALIBRATE",
            subtitle_text="LOOK FORWARD",
        )
        _apply_visual(
            runtime,
            config,
            texture_cache,
            calibration_overlay,
            calibration_overlay.visual,
        )
        runtime.update_overlay_placement_relative_to_hmd(
            calibration_overlay.overlay,
            config.calibration_message.placement,
        )
        runtime.set_visible(calibration_overlay.overlay, False)

        _apply_calibrated_placements(
            runtime,
            scene_buttons,
            calibrated_center_x_m,
            calibrated_center_z_m,
            calibrated_yaw_deg,
        )
        _apply_visibility(runtime, scene_buttons, controls_visible)

        publish(
            "running",
            (
                "Running in "
                f"{config.locomotion_mode} mode. Dwell on toggle to calibrate."
            ),
        )

        while not shutdown_requested:
            if stop_event is not None and stop_event.is_set():
                publish("stopping", "Stop requested.")
                break

            runtime.pump_overlay_events()
            now = time.monotonic()
            delta_s = 0.0 if last_frame_at is None else max(0.0, now - last_frame_at)
            last_frame_at = now
            hmd_pose = runtime.get_hmd_pose()
            tracker_poses = runtime.get_tracker_poses()
            gaze_ray = _to_gaze_ray(hmd_pose)
            if hmd_pose is None:
                if no_pose_started_at is None:
                    no_pose_started_at = now
                elif now - no_pose_started_at >= config.osc.no_pose_failsafe_s:
                    osc.force_zero()
            else:
                no_pose_started_at = None
                _apply_toggle_placement(runtime, scene_buttons["toggle"], hmd_pose)

            best_hit: tuple[str, OverlayIntersection] | None = None
            if gaze_ray is not None:
                for button_id, scene_button in scene_buttons.items():
                    if not _is_button_interactable(button_id, controls_visible):
                        continue
                    hit = runtime.compute_overlay_intersection(
                        scene_button.overlay, gaze_ray
                    )
                    if hit is None:
                        continue
                    if best_hit is None or hit.distance < best_hit[1].distance:
                        best_hit = (button_id, hit)

            update = dwell.update(now, best_hit[0] if best_hit is not None else None)
            new_hover_id = update.hover_id

            calibration_status = calibration.update(
                now,
                _yaw_from_pose(hmd_pose),
                _position_xz_from_pose(hmd_pose),
            )
            if calibration_status.completed_pose is not None:
                calibrated_center_x_m = calibration_status.completed_pose.x_m
                calibrated_center_z_m = calibration_status.completed_pose.z_m
                calibrated_yaw_deg = calibration_status.completed_pose.yaw_deg
                controls_visible = True
                pedal_estimator.reset()
                LOGGER.info(
                    "Calibration complete center=(%.2f, %.2f) yaw=%.1f deg",
                    calibrated_center_x_m,
                    calibrated_center_z_m,
                    calibrated_yaw_deg,
                )
                if (
                    _is_tracker_mode(config)
                    and config.pedal_estimation.startup_calibration_enabled
                ):
                    pedal_calibration.start(now)
                    publish("info", "Pedal calibration started.")
                _apply_calibrated_placements(
                    runtime,
                    scene_buttons,
                    calibrated_center_x_m,
                    calibrated_center_z_m,
                    calibrated_yaw_deg,
                )
                _apply_visibility(runtime, scene_buttons, controls_visible)

            selected_trackers = infer_foot_trackers(
                tracker_poses,
                config.tracker.required_feet_count,
            )
            bike_relative_trackers = to_bike_relative_trackers(
                selected_trackers,
                calibrated_center_x_m,
                calibrated_center_z_m,
                calibrated_yaw_deg,
            )
            pedal_calibration_status = pedal_calibration.update(
                now,
                bike_relative_trackers,
            )
            if pedal_calibration_status.completed_models is not None:
                pedal_estimator.apply_calibration(
                    pedal_calibration_status.completed_models
                )
                publish(
                    "info",
                    "Pedal calibration completed "
                    f"for {len(pedal_calibration_status.completed_models)} trackers.",
                )

            overlay_title_text, overlay_subtitle_text, overlay_visible = (
                _overlay_message(
                    calibration_status.title_text,
                    calibration_status.subtitle_text,
                    calibration_status.active,
                    pedal_calibration_status.title_text,
                    pedal_calibration_status.subtitle_text,
                    pedal_calibration_status.active,
                )
            )
            if calibration_overlay is not None and (
                calibration_overlay.title_text != overlay_title_text
                or calibration_overlay.subtitle_text != overlay_subtitle_text
            ):
                calibration_overlay.title_text = overlay_title_text
                calibration_overlay.subtitle_text = overlay_subtitle_text
                _apply_visual(
                    runtime,
                    config,
                    texture_cache,
                    calibration_overlay,
                    calibration_overlay.visual,
                )
            if calibration_overlay is not None:
                runtime.set_visible(calibration_overlay.overlay, overlay_visible)

            for button_id, scene_button in scene_buttons.items():
                visual = update.visuals[button_id]
                if visual == scene_button.visual:
                    continue
                scene_button.visual = visual
                _apply_visual(runtime, config, texture_cache, scene_button, visual)

            if new_hover_id != current_hover_id:
                current_hover_id = new_hover_id
                if best_hit is None:
                    LOGGER.info("Hover cleared")
                else:
                    uv = best_hit[1].uv
                    LOGGER.info(
                        "Hover %s uv=(%.3f, %.3f) distance=%.3f m",
                        best_hit[0],
                        uv[0],
                        uv[1],
                        best_hit[1].distance,
                    )

            if update.committed_id is not None:
                LOGGER.info("Committed %s", update.committed_id)
                (
                    controls_visible,
                    latched_drive_id,
                    drive_adjust_id,
                    drive_magnitude,
                ) = _apply_commit(
                    update.committed_id,
                    now,
                    osc,
                    calibration,
                    pedal_calibration,
                    pedal_estimator,
                    controls_visible,
                    latched_drive_id,
                    drive_adjust_id,
                    drive_magnitude,
                    config,
                )
                _apply_visibility(runtime, scene_buttons, controls_visible)

            if _is_tracker_mode(config):
                tracker_estimate = _update_tracker_drive(
                    pedal_estimator,
                    now,
                    bike_relative_trackers,
                    controls_visible,
                    pedal_calibration_status.active or calibration_status.active,
                )
            else:
                latched_drive_id, drive_adjust_id, drive_magnitude = (
                    _apply_drive_adjustment(
                        latched_drive_id,
                        drive_adjust_id,
                        drive_magnitude,
                        new_hover_id,
                        delta_s,
                        config,
                    )
                )
            _apply_lean_turn(
                osc,
                controls_visible,
                hmd_pose,
                calibrated_center_x_m,
                calibrated_center_z_m,
                calibrated_yaw_deg,
                config,
            )
            if _is_tracker_mode(config):
                _apply_drive_compensation(
                    osc,
                    "forward",
                    tracker_estimate.magnitude,
                    controls_visible,
                    hmd_pose,
                    calibrated_yaw_deg,
                    config,
                )
            else:
                _apply_drive_compensation(
                    osc,
                    latched_drive_id,
                    drive_magnitude,
                    controls_visible,
                    hmd_pose,
                    calibrated_yaw_deg,
                    config,
                )

            osc.sync()

            runtime.wait_frame()
            if frames_remaining is not None:
                frames_remaining -= 1
                if frames_remaining <= 0:
                    publish("stopping", "Requested duration elapsed, shutting down.")
                    break
    except RuntimeInitError as exc:
        message = str(exc)
        LOGGER.error("%s", message)
        if status_callback is not None:
            status_callback(RuntimeStatus(state="error", message=message))
        return 1
    except KeyboardInterrupt:
        publish("stopping", "Interrupted, shutting down.")
    finally:
        osc.force_zero()
        runtime.shutdown()
        if status_callback is not None:
            status_callback(RuntimeStatus(state="stopped", message="Stopped."))

    return 0


def cli_main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    options = RuntimeOptions(
        duration=args.duration,
        locomotion_mode=args.locomotion_mode,
        pedal_calibration=args.pedal_calibration,
        verbose=args.verbose,
    )
    return run_session(options)


def main(argv: list[str] | None = None) -> int:
    return cli_main(argv)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))


def _apply_visual(
    runtime: SteamVROverlayRuntime,
    config: AppConfig,
    texture_cache: dict[
        tuple[str, TextureVariant, str | None, str | None], OverlayTexture
    ],
    scene_button: SceneButton,
    visual: ButtonVisualState,
) -> None:
    variant = quantize_visual(visual, config.render)
    if (
        variant == scene_button.texture_variant
        and scene_button.title_text == scene_button.rendered_title_text
        and scene_button.subtitle_text == scene_button.rendered_subtitle_text
    ):
        return
    cache_key = (
        scene_button.config.id,
        variant,
        scene_button.title_text,
        scene_button.subtitle_text,
    )
    texture = texture_cache.get(cache_key)
    if texture is None:
        texture = build_button_texture(
            scene_button.config,
            variant,
            title_text=scene_button.title_text,
            subtitle_text=scene_button.subtitle_text,
        )
        texture_cache[cache_key] = texture
    runtime.request_texture_upload(scene_button.overlay, texture)
    scene_button.texture_variant = variant
    scene_button.rendered_title_text = scene_button.title_text
    scene_button.rendered_subtitle_text = scene_button.subtitle_text


def _apply_commit(
    committed_id: str,
    now: float,
    osc: VRChatOscController,
    calibration: CalibrationController,
    pedal_calibration: PedalCalibrationController,
    pedal_estimator: PedalEstimator,
    controls_visible: bool,
    latched_drive_id: str | None,
    drive_adjust_id: str | None,
    drive_magnitude: float,
    config: AppConfig,
) -> tuple[bool, str | None, str | None, float]:
    if committed_id == "toggle":
        if controls_visible:
            osc.force_zero()
            pedal_calibration.cancel()
            pedal_estimator.reset()
            LOGGER.info("Controls hidden")
            return False, None, None, 0.0
        calibration.start(now)
        pedal_calibration.cancel()
        pedal_estimator.reset()
        osc.clear_motion()
        LOGGER.info("Calibration started")
        return False, None, None, 0.0
    if _is_tracker_mode(config):
        return controls_visible, latched_drive_id, drive_adjust_id, drive_magnitude
    if committed_id == "forward":
        return controls_visible, "forward", "forward", drive_magnitude
    elif committed_id == "backward":
        return controls_visible, "backward", "backward", drive_magnitude
    elif committed_id == "stop":
        return controls_visible, latched_drive_id, "stop", drive_magnitude
    return controls_visible, latched_drive_id, drive_adjust_id, drive_magnitude


def _apply_visibility(
    runtime: SteamVROverlayRuntime,
    scene_buttons: dict[str, SceneButton],
    controls_visible: bool,
) -> None:
    for button_id, scene_button in scene_buttons.items():
        visible = button_id == "toggle" or controls_visible
        runtime.set_visible(scene_button.overlay, visible)


def _is_button_interactable(button_id: str, controls_visible: bool) -> bool:
    return controls_visible or button_id == "toggle"


def _apply_lean_turn(
    osc: VRChatOscController,
    controls_visible: bool,
    hmd_pose: HmdPose | None,
    calibrated_center_x_m: float,
    calibrated_center_z_m: float,
    calibrated_yaw_deg: float,
    config: AppConfig,
) -> None:
    if not controls_visible or hmd_pose is None:
        osc.clear_turn()
        return

    lateral_offset_m = _bike_relative_lateral_offset_m(
        hmd_pose,
        calibrated_center_x_m,
        calibrated_center_z_m,
        calibrated_yaw_deg,
    )
    turn_axis = _lean_turn_axis(lateral_offset_m, config)
    if turn_axis == 0.0:
        osc.clear_turn()
        return
    osc.set_turn_axis(turn_axis)


def _apply_drive_compensation(
    osc: VRChatOscController,
    latched_drive_id: str | None,
    drive_magnitude: float,
    controls_visible: bool,
    hmd_pose: HmdPose | None,
    calibrated_yaw_deg: float,
    config: AppConfig,
) -> None:
    if (
        not controls_visible
        or latched_drive_id is None
        or hmd_pose is None
        or drive_magnitude <= 0.0
    ):
        osc.clear_motion()
        return

    drive_scalar = 0.0
    if latched_drive_id == "forward":
        drive_scalar = config.osc.vertical_axis * drive_magnitude
    elif latched_drive_id == "backward":
        drive_scalar = config.osc.backward_axis * drive_magnitude

    yaw_delta_deg = _yaw_from_direction(hmd_pose.direction) - calibrated_yaw_deg
    yaw_delta_rad = math.radians(yaw_delta_deg)
    horizontal = drive_scalar * math.sin(yaw_delta_rad)
    vertical = drive_scalar * math.cos(yaw_delta_rad)
    osc.set_motion_axes(horizontal, vertical)


def _apply_calibrated_placements(
    runtime: SteamVROverlayRuntime,
    scene_buttons: dict[str, SceneButton],
    calibrated_center_x_m: float,
    calibrated_center_z_m: float,
    calibrated_yaw_deg: float,
) -> None:
    for button_id, scene_button in scene_buttons.items():
        if button_id == "toggle":
            continue
        runtime.update_overlay_placement(
            scene_button.overlay,
            _rotate_and_translate_placement(
                scene_button.config.placement,
                calibrated_center_x_m,
                calibrated_center_z_m,
                calibrated_yaw_deg,
            ),
        )


def _apply_toggle_placement(
    runtime: SteamVROverlayRuntime,
    toggle_button: SceneButton,
    hmd_pose: HmdPose,
) -> None:
    runtime.update_overlay_placement(
        toggle_button.overlay,
        OverlayPlacement(
            x_m=hmd_pose.position[0],
            y_m=toggle_button.config.placement.y_m,
            z_m=hmd_pose.position[2],
            yaw_deg=toggle_button.config.placement.yaw_deg,
            pitch_deg=toggle_button.config.placement.pitch_deg,
            roll_deg=toggle_button.config.placement.roll_deg,
        ),
    )


def _rotate_and_translate_placement(
    placement: OverlayPlacement,
    calibrated_center_x_m: float,
    calibrated_center_z_m: float,
    calibrated_yaw_deg: float,
) -> OverlayPlacement:
    yaw_rad = math.radians(calibrated_yaw_deg)
    cos_yaw = math.cos(yaw_rad)
    sin_yaw = math.sin(yaw_rad)
    rotated_x = placement.x_m * cos_yaw + placement.z_m * sin_yaw
    rotated_z = -placement.x_m * sin_yaw + placement.z_m * cos_yaw
    return OverlayPlacement(
        x_m=calibrated_center_x_m + rotated_x,
        y_m=placement.y_m,
        z_m=calibrated_center_z_m + rotated_z,
        yaw_deg=placement.yaw_deg + calibrated_yaw_deg,
        pitch_deg=placement.pitch_deg,
        roll_deg=placement.roll_deg,
    )


def _to_gaze_ray(hmd_pose: HmdPose | None) -> GazeRay | None:
    if hmd_pose is None:
        return None
    return GazeRay(source=hmd_pose.position, direction=hmd_pose.direction)


def _yaw_from_pose(hmd_pose: HmdPose | None) -> float | None:
    if hmd_pose is None:
        return None
    return _yaw_from_direction(hmd_pose.direction)


def _position_xz_from_pose(hmd_pose: HmdPose | None) -> tuple[float, float] | None:
    if hmd_pose is None:
        return None
    return (hmd_pose.position[0], hmd_pose.position[2])


def _yaw_from_direction(direction: tuple[float, float, float]) -> float:
    return math.degrees(math.atan2(-direction[0], -direction[2]))


def _apply_drive_adjustment(
    latched_drive_id: str | None,
    drive_adjust_id: str | None,
    drive_magnitude: float,
    hover_id: str | None,
    delta_s: float,
    config: AppConfig,
) -> tuple[str | None, str | None, float]:
    if drive_adjust_id is not None and hover_id != drive_adjust_id:
        drive_adjust_id = None

    if drive_adjust_id == "forward" and latched_drive_id == "forward":
        drive_magnitude = min(
            1.0,
            drive_magnitude
            + delta_s / max(0.001, config.drive_ramp.accelerate_to_full_s),
        )
    elif drive_adjust_id == "backward" and latched_drive_id == "backward":
        drive_magnitude = min(
            1.0,
            drive_magnitude
            + delta_s / max(0.001, config.drive_ramp.accelerate_to_full_s),
        )
    elif drive_adjust_id == "stop":
        drive_magnitude = max(
            0.0,
            drive_magnitude - delta_s / max(0.001, config.drive_ramp.brake_to_zero_s),
        )
        if drive_magnitude <= 0.0:
            return None, None, 0.0

    return latched_drive_id, drive_adjust_id, drive_magnitude


def _active_buttons(config: AppConfig) -> tuple[ButtonConfig, ...]:
    if _is_tracker_mode(config):
        return tuple(button for button in config.buttons if button.id == "toggle")
    return config.buttons


def _is_tracker_mode(config: AppConfig) -> bool:
    return config.locomotion_mode == "tracker"


def _overlay_message(
    primary_title_text: str | None,
    primary_subtitle_text: str | None,
    primary_visible: bool,
    secondary_title_text: str | None,
    secondary_subtitle_text: str | None,
    secondary_visible: bool,
) -> tuple[str | None, str | None, bool]:
    if primary_visible:
        return primary_title_text, primary_subtitle_text, True
    if secondary_visible:
        return secondary_title_text, secondary_subtitle_text, True
    return None, None, False


def _update_tracker_drive(
    pedal_estimator: PedalEstimator,
    now: float,
    bike_relative_trackers: list[BikeRelativeTrackerPose],
    controls_visible: bool,
    calibration_active: bool,
) -> PedalEstimate:
    if not controls_visible or calibration_active:
        pedal_estimator.reset()
        return PedalEstimate(
            magnitude=0.0,
            cadence_hz=0.0,
            trackers_ready=False,
            trackers_visible=len(bike_relative_trackers),
        )
    return pedal_estimator.update(now, bike_relative_trackers)


def _bike_relative_lateral_offset_m(
    hmd_pose: HmdPose,
    calibrated_center_x_m: float,
    calibrated_center_z_m: float,
    calibrated_yaw_deg: float,
) -> float:
    delta_x = hmd_pose.position[0] - calibrated_center_x_m
    delta_z = hmd_pose.position[2] - calibrated_center_z_m
    yaw_rad = math.radians(calibrated_yaw_deg)
    right_x = math.cos(yaw_rad)
    right_z = -math.sin(yaw_rad)
    return delta_x * right_x + delta_z * right_z


def _lean_turn_axis(lateral_offset_m: float, config: AppConfig) -> float:
    magnitude_m = abs(lateral_offset_m)
    if magnitude_m <= config.lean_turn.deadzone_m:
        return 0.0

    span_m = max(
        0.001,
        config.lean_turn.full_scale_m - config.lean_turn.deadzone_m,
    )
    normalized = min(1.0, (magnitude_m - config.lean_turn.deadzone_m) / span_m)
    return math.copysign(normalized * config.osc.turn_axis, lateral_offset_m)
