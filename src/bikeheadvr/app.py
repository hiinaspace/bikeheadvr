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
from .config import AppConfig, ButtonConfig, OverlayPlacement, OverlayTextureConfig
from .interaction import ButtonVisualState, DwellTracker
from .overlay_ui import (
    OverlayTexture,
    TextureVariant,
    build_button_texture,
    build_debug_arrow_texture,
    build_debug_marker_texture,
    build_debug_torque_texture,
    build_skate_foot_texture,
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
from .skating_estimation import (
    SkatingCalibrationModel,
    SkatingEstimate,
    SkatingEstimator,
    build_skating_calibration,
)
from .skating_recording import SkatingRecordingWriter
from .vr_runtime import (
    DevicePose,
    GazeRay,
    HmdPose,
    OverlayHandle,
    OverlayIntersection,
    RuntimeInitError,
    SteamVROverlayRuntime,
    TrackerPose,
)
from .vrchat_osc import VRChatOscController

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class RuntimeOptions:
    duration: float = 0.0
    locomotion_mode: str = "manual"
    pedal_calibration: bool = False
    skating_playspace_turn: bool = False
    skating_record_only: bool = False
    skating_record_path: Path | None = None
    skating_push_yaw_gain: float | None = None
    skating_tracker_velocity_blend: float | None = None
    skating_contact_enter_m: float | None = None
    skating_contact_leave_m: float | None = None
    skating_contact_full_load_m: float | None = None
    skating_contact_tilt_full_load_deg: float | None = None
    skating_contact_tilt_zero_load_deg: float | None = None
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


@dataclass
class SkatingFootOverlay:
    serial: str
    side: str
    config: ButtonConfig
    overlay: OverlayHandle
    grounded: bool | None = None
    load_bucket: int | None = None


@dataclass
class SkatingDebugOverlay:
    id: str
    overlay: OverlayHandle
    width_m: float
    texture_key: tuple[str, int] | None = None


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="bikeheadvr development CLI")
    parser.add_argument("--duration", type=float, default=0.0)
    parser.add_argument(
        "--locomotion-mode",
        choices=("manual", "tracker", "skating"),
        default="manual",
    )
    parser.add_argument("--pedal-calibration", action="store_true")
    parser.add_argument("--skating-playspace-turn", action="store_true")
    parser.add_argument("--no-skating-playspace-turn", action="store_true")
    parser.add_argument(
        "--skating-record-only",
        action="store_true",
        help="Run skating estimation and recording without sending VRChat motion or chaperone yaw.",
    )
    parser.add_argument("--skating-record-path", type=Path)
    parser.add_argument("--skating-push-yaw-gain", type=float)
    parser.add_argument("--skating-tracker-velocity-blend", type=float)
    parser.add_argument("--skating-contact-enter-m", type=float)
    parser.add_argument("--skating-contact-leave-m", type=float)
    parser.add_argument("--skating-contact-full-load-m", type=float)
    parser.add_argument("--skating-contact-tilt-full-load-deg", type=float)
    parser.add_argument("--skating-contact-tilt-zero-load-deg", type=float)
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
    skating_config = base_config.skating
    if options.skating_push_yaw_gain is not None:
        skating_config = replace(
            skating_config,
            push_yaw_gain=options.skating_push_yaw_gain,
        )
    if options.skating_tracker_velocity_blend is not None:
        skating_config = replace(
            skating_config,
            tracker_velocity_blend=options.skating_tracker_velocity_blend,
        )
    skating_overrides = {
        "contact_enter_m": options.skating_contact_enter_m,
        "contact_leave_m": options.skating_contact_leave_m,
        "contact_full_load_m": options.skating_contact_full_load_m,
        "contact_tilt_full_load_deg": options.skating_contact_tilt_full_load_deg,
        "contact_tilt_zero_load_deg": options.skating_contact_tilt_zero_load_deg,
    }
    active_skating_overrides = {
        key: value
        for key, value in skating_overrides.items()
        if value is not None
    }
    if active_skating_overrides:
        skating_config = replace(skating_config, **active_skating_overrides)
    return replace(
        base_config,
        locomotion_mode=options.locomotion_mode,
        skating=skating_config,
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
    skating_recorder: SkatingRecordingWriter | None = None
    if options.skating_record_path is not None and _is_skating_mode(config):
        skating_recorder = SkatingRecordingWriter(
            options.skating_record_path,
            config.skating,
            pose_universe="raw",
        )
        publish("info", f"Recording skating poses to {skating_recorder.path}")
    elif options.skating_record_path is not None:
        publish("info", "Ignoring --skating-record-path outside skating mode.")
    calibration = CalibrationController(config.calibration)
    pedal_calibration = PedalCalibrationController(config.pedal_estimation)
    pedal_estimator = PedalEstimator(config.tracker, config.pedal_estimation)
    skating_estimator = SkatingEstimator(config.tracker, config.skating)
    active_buttons = _active_buttons(config)
    dwell = DwellTracker([button.id for button in active_buttons], config.dwell)
    shutdown_requested = False
    frames_remaining = (
        None
        if options.duration <= 0
        else max(1, int(round(options.duration * config.tick_hz)))
    )
    scene_buttons: dict[str, SceneButton] = {}
    skating_foot_overlays: dict[str, SkatingFootOverlay] = {}
    skating_debug_overlays: dict[str, SkatingDebugOverlay] = {}
    calibration_overlay: SceneButton | None = None
    texture_cache: dict[
        tuple[str, TextureVariant, str | None, str | None], OverlayTexture
    ] = {}
    skating_foot_texture_cache: dict[tuple[str, bool, int], OverlayTexture] = {}
    skating_debug_texture_cache: dict[tuple[str, int], OverlayTexture] = {}
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
    session_started_at: float | None = None
    tracker_estimate = PedalEstimate(
        magnitude=0.0,
        cadence_hz=0.0,
        trackers_ready=False,
        trackers_visible=0,
    )
    skating_estimate = SkatingEstimate()

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
        session_started_at = time.monotonic()

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
            skating_hmd_pose = hmd_pose
            skating_tracker_poses = tracker_poses
            if _is_skating_mode(config):
                skating_hmd_pose = runtime.get_raw_hmd_pose()
                skating_tracker_poses = runtime.get_raw_tracker_poses()
            device_poses: list[DevicePose] = []
            raw_to_standing = None
            if skating_recorder is not None and _is_skating_mode(config):
                device_poses = runtime.get_raw_device_poses()
                raw_to_standing = runtime.get_raw_zero_to_standing_transform()
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
            selected_trackers = infer_foot_trackers(
                tracker_poses,
                config.tracker.required_feet_count,
            )
            selected_skating_trackers = infer_foot_trackers(
                skating_tracker_poses,
                config.tracker.required_feet_count,
            )
            calibration_pose = (
                skating_hmd_pose if _is_skating_mode(config) else hmd_pose
            )

            calibration_status = calibration.update(
                now,
                _yaw_from_pose(calibration_pose),
                _position_xz_from_pose(calibration_pose),
            )
            if calibration_status.completed_pose is not None:
                calibrated_center_x_m = calibration_status.completed_pose.x_m
                calibrated_center_z_m = calibration_status.completed_pose.z_m
                calibrated_yaw_deg = calibration_status.completed_pose.yaw_deg
                pedal_estimator.reset()
                skating_estimator.reset()
                LOGGER.info(
                    "Calibration complete center=(%.2f, %.2f) yaw=%.1f deg",
                    calibrated_center_x_m,
                    calibrated_center_z_m,
                    calibrated_yaw_deg,
                )
                if _is_skating_mode(config):
                    skating_model = (
                        None
                        if skating_hmd_pose is None
                        else build_skating_calibration(
                            calibrated_center_x_m,
                            calibrated_center_z_m,
                            calibrated_yaw_deg,
                            skating_hmd_pose,
                            selected_skating_trackers,
                            config.tracker.required_feet_count,
                        )
                    )
                    if skating_model is None:
                        controls_visible = False
                        skating_estimator.clear_calibration()
                        _hide_skating_foot_overlays(runtime, skating_foot_overlays)
                        _hide_skating_debug_overlays(runtime, skating_debug_overlays)
                        publish(
                            "info",
                            "Skating calibration needs HMD tracking and two foot trackers.",
                        )
                    else:
                        controls_visible = True
                        skating_estimator.apply_calibration(skating_model)
                        if skating_recorder is not None:
                            skating_recorder.start_segment(
                                now - session_started_at,
                                now,
                                skating_model,
                            )
                        _ensure_skating_foot_overlays(
                            runtime,
                            config,
                            skating_model,
                            skating_foot_overlays,
                            skating_foot_texture_cache,
                        )
                        _ensure_skating_debug_overlays(
                            runtime,
                            config,
                            skating_debug_overlays,
                            skating_debug_texture_cache,
                        )
                        if options.skating_playspace_turn:
                            runtime.capture_playspace_yaw_baseline()
                        publish(
                            "info",
                            "Skating calibration completed "
                            f"for {len(skating_model.feet)} trackers.",
                        )
                        height_warning = _skating_tracker_height_warning(
                            skating_model
                        )
                        if height_warning is not None:
                            publish("info", height_warning)
                else:
                    controls_visible = True
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
                was_controls_visible = controls_visible
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
                if _is_skating_mode(config) and update.committed_id == "toggle":
                    if skating_recorder is not None:
                        skating_recorder.end_segment(
                            now - session_started_at,
                            now,
                            "toggle",
                        )
                    skating_estimator.clear_calibration()
                    runtime.restore_playspace_yaw()
                    _hide_skating_foot_overlays(runtime, skating_foot_overlays)
                    _hide_skating_debug_overlays(runtime, skating_debug_overlays)
                    skating_estimate = SkatingEstimate()
                    if was_controls_visible:
                        osc.clear_turn()
                _apply_visibility(runtime, scene_buttons, controls_visible)

            calibration_active = (
                pedal_calibration_status.active or calibration_status.active
            )
            if _is_skating_mode(config):
                skating_output_hmd_pose, skating_output_yaw_deg = (
                    _skating_output_frame(
                        runtime,
                        skating_estimator.calibration,
                        hmd_pose,
                        skating_hmd_pose,
                    )
                )
                skating_estimate = _update_skating_drive(
                    skating_estimator,
                    now,
                    skating_hmd_pose,
                    selected_skating_trackers,
                    controls_visible,
                    calibration_status.active,
                    output_hmd_pose=skating_output_hmd_pose,
                    output_calibrated_yaw_deg=skating_output_yaw_deg,
                )
                osc.clear_turn()
                if options.skating_record_only:
                    osc.clear_motion()
                else:
                    _apply_skating_motion(
                        osc,
                        skating_estimate,
                        controls_visible,
                        calibration_status.active,
                    )
                _update_skating_foot_overlays(
                    runtime,
                    config,
                    skating_foot_overlays,
                    skating_foot_texture_cache,
                    skating_estimator.calibration,
                    skating_estimate,
                    tracker_poses,
                    controls_visible and not calibration_status.active,
                )
                _update_skating_debug_overlays(
                    runtime,
                    config,
                    skating_debug_overlays,
                    skating_debug_texture_cache,
                    skating_estimator.calibration,
                    skating_estimate,
                    hmd_pose,
                    tracker_poses,
                    controls_visible and not calibration_status.active,
                )
                if (
                    options.skating_playspace_turn
                    and not options.skating_record_only
                    and controls_visible
                    and hmd_pose is not None
                    and not calibration_status.active
                ):
                    playspace_yaw_deg = skating_estimate.body_yaw_deg
                    if (
                        abs(playspace_yaw_deg)
                        < config.skating.playspace_yaw_deadzone_deg
                    ):
                        playspace_yaw_deg = 0.0
                    runtime.apply_playspace_yaw_offset(
                        playspace_yaw_deg,
                        hmd_pose.position,
                    )
                else:
                    runtime.restore_playspace_yaw()
            elif _is_tracker_mode(config):
                tracker_estimate = _update_tracker_drive(
                    pedal_estimator,
                    now,
                    bike_relative_trackers,
                    controls_visible,
                    calibration_active,
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
                _apply_drive_compensation(
                    osc,
                    latched_drive_id,
                    drive_magnitude,
                    controls_visible,
                    hmd_pose,
                    calibrated_yaw_deg,
                    config,
                )

            if (
                skating_recorder is not None
                and _is_skating_mode(config)
                and session_started_at is not None
                and skating_estimator.calibration is not None
                and not calibration_status.active
            ):
                try:
                    skating_recorder.write_frame(
                        relative_s=now - session_started_at,
                        monotonic_s=now,
                        hmd_pose=skating_hmd_pose,
                        trackers=skating_tracker_poses,
                        devices=device_poses,
                        selected_trackers=selected_skating_trackers,
                        calibration=skating_estimator.calibration,
                        estimate=skating_estimate,
                        controls_visible=controls_visible,
                        calibration_active=calibration_status.active,
                        record_only=options.skating_record_only,
                        raw_to_standing=raw_to_standing,
                    )
                except OSError:
                    LOGGER.warning("Failed to write skating recording", exc_info=True)
                    skating_recorder.close()
                    skating_recorder = None

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
        if skating_recorder is not None:
            skating_recorder.close()
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
        skating_playspace_turn=(
            args.skating_playspace_turn
            and not args.no_skating_playspace_turn
        ),
        skating_record_only=args.skating_record_only,
        skating_record_path=args.skating_record_path,
        skating_push_yaw_gain=args.skating_push_yaw_gain,
        skating_tracker_velocity_blend=args.skating_tracker_velocity_blend,
        skating_contact_enter_m=args.skating_contact_enter_m,
        skating_contact_leave_m=args.skating_contact_leave_m,
        skating_contact_full_load_m=args.skating_contact_full_load_m,
        skating_contact_tilt_full_load_deg=(
            args.skating_contact_tilt_full_load_deg
        ),
        skating_contact_tilt_zero_load_deg=(
            args.skating_contact_tilt_zero_load_deg
        ),
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
    if _is_tracker_mode(config) or _is_skating_mode(config):
        return tuple(button for button in config.buttons if button.id == "toggle")
    return config.buttons


def _is_tracker_mode(config: AppConfig) -> bool:
    return config.locomotion_mode == "tracker"


def _is_skating_mode(config: AppConfig) -> bool:
    return config.locomotion_mode == "skating"


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


def _update_skating_drive(
    skating_estimator: SkatingEstimator,
    now: float,
    hmd_pose: HmdPose | None,
    trackers: list[TrackerPose],
    controls_visible: bool,
    calibration_active: bool,
    *,
    output_hmd_pose: HmdPose | None = None,
    output_calibrated_yaw_deg: float | None = None,
) -> SkatingEstimate:
    if not controls_visible or calibration_active:
        skating_estimator.reset()
        return SkatingEstimate(trackers_visible=len(trackers))
    return skating_estimator.update(
        now,
        hmd_pose,
        trackers,
        output_hmd_pose=output_hmd_pose,
        output_calibrated_yaw_deg=output_calibrated_yaw_deg,
    )


def _skating_output_frame(
    runtime: SteamVROverlayRuntime,
    model: SkatingCalibrationModel | None,
    standing_hmd_pose: HmdPose | None,
    raw_hmd_pose: HmdPose | None,
) -> tuple[HmdPose | None, float | None]:
    if model is None or standing_hmd_pose is None:
        return raw_hmd_pose, None
    output_yaw_deg = runtime.raw_yaw_to_standing_yaw(model.yaw_deg)
    if output_yaw_deg is None:
        return raw_hmd_pose, None
    return standing_hmd_pose, output_yaw_deg


def _apply_skating_motion(
    osc: VRChatOscController,
    estimate: SkatingEstimate,
    controls_visible: bool,
    calibration_active: bool,
) -> None:
    if not controls_visible or calibration_active:
        osc.clear_motion()
        return
    if abs(estimate.horizontal) < 0.001 and abs(estimate.vertical) < 0.001:
        osc.clear_motion()
        return
    osc.set_motion_axes(estimate.horizontal, estimate.vertical)


def _ensure_skating_foot_overlays(
    runtime: SteamVROverlayRuntime,
    config: AppConfig,
    model: SkatingCalibrationModel,
    overlays: dict[str, SkatingFootOverlay],
    texture_cache: dict[tuple[str, bool, int], OverlayTexture],
) -> None:
    if not config.skating.debug_foot_overlay_enabled:
        return

    active_serials = set(model.feet)
    for serial, foot_overlay in overlays.items():
        if serial not in active_serials:
            runtime.set_visible(foot_overlay.overlay, False)

    for foot in model.feet.values():
        foot_overlay = overlays.get(foot.serial)
        if foot_overlay is None:
            overlay_config = ButtonConfig(
                id=f"skating_foot_{foot.side}_{foot.serial}",
                label=f"{foot.side.title()} Skate",
                key=f"dev.bikeheadvr.overlay.skating_foot.{foot.side}.{foot.serial}",
                width_m=config.skating.debug_foot_overlay_length_m,
                placement=OverlayPlacement(
                    x_m=0.0,
                    y_m=0.0,
                    z_m=0.0,
                    yaw_deg=0.0,
                    pitch_deg=-90.0,
                ),
                texture=OverlayTextureConfig(width_px=512, height_px=224),
                alpha=0.72,
                always_visible=False,
            )
            foot_overlay = SkatingFootOverlay(
                serial=foot.serial,
                side=foot.side,
                config=overlay_config,
                overlay=runtime.create_overlay(overlay_config),
            )
            overlays[foot.serial] = foot_overlay
        _apply_skating_foot_texture(
            runtime,
            foot_overlay,
            grounded=True,
            contact_load=1.0,
            texture_cache=texture_cache,
        )
        runtime.set_visible(foot_overlay.overlay, False)


def _update_skating_foot_overlays(
    runtime: SteamVROverlayRuntime,
    config: AppConfig,
    overlays: dict[str, SkatingFootOverlay],
    texture_cache: dict[tuple[str, bool, int], OverlayTexture],
    model: SkatingCalibrationModel | None,
    estimate: SkatingEstimate,
    trackers: list[TrackerPose],
    visible: bool,
) -> None:
    if (
        not visible
        or model is None
        or not config.skating.debug_foot_overlay_enabled
    ):
        _hide_skating_foot_overlays(runtime, overlays)
        return

    trackers_by_serial = {tracker.serial: tracker for tracker in trackers}
    for serial, foot_overlay in overlays.items():
        tracker = trackers_by_serial.get(serial)
        foot_estimate = estimate.feet.get(serial)
        if tracker is None or foot_estimate is None:
            runtime.set_visible(foot_overlay.overlay, False)
            continue

        _apply_skating_foot_texture(
            runtime,
            foot_overlay,
            grounded=foot_estimate.grounded,
            contact_load=foot_estimate.contact_load,
            texture_cache=texture_cache,
        )
        runtime.update_overlay_placement(
            foot_overlay.overlay,
            OverlayPlacement(
                x_m=tracker.position[0],
                y_m=tracker.position[1] + config.skating.debug_foot_overlay_y_offset_m,
                z_m=tracker.position[2],
                yaw_deg=model.yaw_deg + foot_estimate.skate_yaw_deg + 90.0,
                pitch_deg=-90.0,
            ),
        )
        runtime.set_visible(foot_overlay.overlay, True)


def _apply_skating_foot_texture(
    runtime: SteamVROverlayRuntime,
    foot_overlay: SkatingFootOverlay,
    grounded: bool,
    contact_load: float,
    texture_cache: dict[tuple[str, bool, int], OverlayTexture],
) -> None:
    load_bucket = int(round(max(0.0, min(1.0, contact_load)) * 4))
    if foot_overlay.grounded == grounded and foot_overlay.load_bucket == load_bucket:
        return
    cache_key = (foot_overlay.side, grounded, load_bucket)
    texture = texture_cache.get(cache_key)
    if texture is None:
        texture = build_skate_foot_texture(
            foot_overlay.config.texture.width_px,
            foot_overlay.config.texture.height_px,
            foot_overlay.side,
            grounded,
            load_bucket / 4.0,
        )
        texture_cache[cache_key] = texture
    runtime.request_texture_upload(foot_overlay.overlay, texture)
    foot_overlay.grounded = grounded
    foot_overlay.load_bucket = load_bucket


def _hide_skating_foot_overlays(
    runtime: SteamVROverlayRuntime,
    overlays: dict[str, SkatingFootOverlay],
) -> None:
    for foot_overlay in overlays.values():
        runtime.set_visible(foot_overlay.overlay, False)


def _ensure_skating_debug_overlays(
    runtime: SteamVROverlayRuntime,
    config: AppConfig,
    overlays: dict[str, SkatingDebugOverlay],
    texture_cache: dict[tuple[str, int], OverlayTexture],
) -> None:
    if not config.skating.debug_ghost_overlay_enabled:
        _hide_skating_debug_overlays(runtime, overlays)
        return

    specs = {
        "com": (0.16, OverlayTextureConfig(192, 192)),
        "velocity": (0.35, OverlayTextureConfig(384, 96)),
        "body": (0.30, OverlayTextureConfig(384, 96)),
        "torque": (0.24, OverlayTextureConfig(192, 192)),
        "lever_left": (0.35, OverlayTextureConfig(384, 48)),
        "lever_right": (0.35, OverlayTextureConfig(384, 48)),
        "force_left": (0.28, OverlayTextureConfig(384, 72)),
        "force_right": (0.28, OverlayTextureConfig(384, 72)),
    }
    for overlay_id, (width_m, texture_config) in specs.items():
        if overlay_id not in overlays:
            overlay_config = ButtonConfig(
                id=f"skating_debug_{overlay_id}",
                label=overlay_id,
                key=f"dev.bikeheadvr.overlay.skating_debug.{overlay_id}",
                width_m=width_m,
                placement=OverlayPlacement(
                    x_m=0.0,
                    y_m=0.0,
                    z_m=0.0,
                    yaw_deg=0.0,
                    pitch_deg=-90.0,
                ),
                texture=texture_config,
                alpha=0.72,
                always_visible=False,
            )
            overlays[overlay_id] = SkatingDebugOverlay(
                id=overlay_id,
                overlay=runtime.create_overlay(overlay_config),
                width_m=width_m,
            )
            runtime.set_visible(overlays[overlay_id].overlay, False)
        _apply_skating_debug_texture(
            runtime,
            overlays[overlay_id],
            overlay_id,
            texture_cache,
        )


def _update_skating_debug_overlays(
    runtime: SteamVROverlayRuntime,
    config: AppConfig,
    overlays: dict[str, SkatingDebugOverlay],
    texture_cache: dict[tuple[str, int], OverlayTexture],
    model: SkatingCalibrationModel | None,
    estimate: SkatingEstimate,
    hmd_pose: HmdPose | None,
    trackers: list[TrackerPose],
    visible: bool,
) -> None:
    if (
        not visible
        or model is None
        or hmd_pose is None
        or not config.skating.debug_ghost_overlay_enabled
    ):
        _hide_skating_debug_overlays(runtime, overlays)
        return

    _ensure_skating_debug_overlays(runtime, config, overlays, texture_cache)
    ghost_x_m, ghost_z_m = _skating_debug_ghost_offset(hmd_pose, config)
    debug_y_m = _skating_debug_floor_y(trackers, config)
    body_x_m = hmd_pose.position[0] + ghost_x_m
    body_z_m = hmd_pose.position[2] + ghost_z_m

    _place_skating_debug_marker(
        runtime,
        overlays,
        "com",
        body_x_m,
        debug_y_m + 0.07,
        body_z_m,
        0.16,
    )

    velocity_dx, velocity_dz = _world_vector_from_calibrated(
        estimate.velocity_right_m_s,
        estimate.velocity_forward_m_s,
        model.yaw_deg,
    )
    _place_skating_debug_vector(
        runtime,
        config,
        overlays,
        "velocity",
        body_x_m,
        debug_y_m + 0.09,
        body_z_m,
        velocity_dx,
        velocity_dz,
        config.skating.debug_velocity_arrow_scale_m,
    )

    body_dx, body_dz = _world_vector_from_yaw(model.yaw_deg + estimate.body_yaw_deg)
    _place_skating_debug_vector(
        runtime,
        config,
        overlays,
        "body",
        body_x_m,
        debug_y_m + 0.11,
        body_z_m,
        body_dx,
        body_dz,
        0.30,
        force_visible=True,
    )

    total_torque = sum(foot.torque for foot in estimate.feet.values())
    _place_skating_debug_torque(
        runtime,
        overlays,
        texture_cache,
        body_x_m,
        debug_y_m + 0.13,
        body_z_m,
        total_torque,
    )

    trackers_by_serial = {tracker.serial: tracker for tracker in trackers}
    for foot in estimate.feet.values():
        tracker = trackers_by_serial.get(foot.serial)
        if tracker is None:
            _set_debug_visible(runtime, overlays, f"force_{foot.side}", False)
            _set_debug_visible(runtime, overlays, f"lever_{foot.side}", False)
            continue
        foot_x_m = tracker.position[0] + ghost_x_m
        foot_z_m = tracker.position[2] + ghost_z_m
        lever_dx = foot_x_m - body_x_m
        lever_dz = foot_z_m - body_z_m
        _place_skating_debug_line(
            runtime,
            overlays,
            f"lever_{foot.side}",
            body_x_m + lever_dx * 0.5,
            debug_y_m + 0.03,
            body_z_m + lever_dz * 0.5,
            lever_dx,
            lever_dz,
        )
        force_dx, force_dz = _world_vector_from_calibrated(
            foot.force_right_m_s2,
            foot.force_forward_m_s2,
            model.yaw_deg,
        )
        _place_skating_debug_vector(
            runtime,
            config,
            overlays,
            f"force_{foot.side}",
            foot_x_m,
            debug_y_m + 0.05,
            foot_z_m,
            force_dx,
            force_dz,
            config.skating.debug_force_arrow_scale_m,
        )


def _apply_skating_debug_texture(
    runtime: SteamVROverlayRuntime,
    overlay: SkatingDebugOverlay,
    overlay_id: str,
    texture_cache: dict[tuple[str, int], OverlayTexture],
) -> None:
    texture_key = (overlay_id, 0)
    if overlay.texture_key == texture_key:
        return
    texture = texture_cache.get(texture_key)
    if texture is None:
        texture = _build_skating_debug_texture(overlay_id, 0)
        texture_cache[texture_key] = texture
    runtime.request_texture_upload(overlay.overlay, texture)
    overlay.texture_key = texture_key


def _build_skating_debug_texture(overlay_id: str, variant: int) -> OverlayTexture:
    if overlay_id == "com":
        return build_debug_marker_texture(192, 192, (255, 242, 153, 235))
    if overlay_id == "velocity":
        return build_debug_arrow_texture(384, 96, (92, 218, 255, 230))
    if overlay_id == "body":
        return build_debug_arrow_texture(384, 96, (203, 171, 255, 220))
    if overlay_id.startswith("lever_"):
        return build_debug_arrow_texture(
            384,
            48,
            (218, 228, 236, 120),
            arrow_head=False,
        )
    if overlay_id.startswith("force_"):
        color = (95, 255, 158, 230)
        return build_debug_arrow_texture(384, 72, color)
    clockwise = variant > 0
    color = (255, 183, 82, 230) if clockwise else (121, 184, 255, 230)
    return build_debug_torque_texture(192, 192, color, clockwise=clockwise)


def _place_skating_debug_marker(
    runtime: SteamVROverlayRuntime,
    overlays: dict[str, SkatingDebugOverlay],
    overlay_id: str,
    x_m: float,
    y_m: float,
    z_m: float,
    width_m: float,
) -> None:
    overlay = overlays.get(overlay_id)
    if overlay is None:
        return
    _set_debug_width(runtime, overlay, width_m)
    runtime.update_overlay_placement(
        overlay.overlay,
        OverlayPlacement(x_m=x_m, y_m=y_m, z_m=z_m, yaw_deg=0.0, pitch_deg=-90.0),
    )
    runtime.set_visible(overlay.overlay, True)


def _place_skating_debug_vector(
    runtime: SteamVROverlayRuntime,
    config: AppConfig,
    overlays: dict[str, SkatingDebugOverlay],
    overlay_id: str,
    x_m: float,
    y_m: float,
    z_m: float,
    dx_m: float,
    dz_m: float,
    scale_m: float,
    *,
    force_visible: bool = False,
) -> None:
    magnitude = math.hypot(dx_m, dz_m)
    if magnitude < 0.03 and not force_visible:
        _set_debug_visible(runtime, overlays, overlay_id, False)
        return
    overlay = overlays.get(overlay_id)
    if overlay is None:
        return
    width_m = _debug_arrow_width(magnitude, scale_m, config)
    _set_debug_width(runtime, overlay, width_m)
    runtime.update_overlay_placement(
        overlay.overlay,
        OverlayPlacement(
            x_m=x_m,
            y_m=y_m,
            z_m=z_m,
            yaw_deg=_overlay_yaw_for_world_vector(dx_m, dz_m),
            pitch_deg=-90.0,
        ),
    )
    runtime.set_visible(overlay.overlay, True)


def _place_skating_debug_line(
    runtime: SteamVROverlayRuntime,
    overlays: dict[str, SkatingDebugOverlay],
    overlay_id: str,
    x_m: float,
    y_m: float,
    z_m: float,
    dx_m: float,
    dz_m: float,
) -> None:
    magnitude = math.hypot(dx_m, dz_m)
    if magnitude < 0.04:
        _set_debug_visible(runtime, overlays, overlay_id, False)
        return
    overlay = overlays.get(overlay_id)
    if overlay is None:
        return
    _set_debug_width(runtime, overlay, max(0.06, magnitude))
    runtime.update_overlay_placement(
        overlay.overlay,
        OverlayPlacement(
            x_m=x_m,
            y_m=y_m,
            z_m=z_m,
            yaw_deg=_overlay_yaw_for_world_vector(dx_m, dz_m),
            pitch_deg=-90.0,
        ),
    )
    runtime.set_visible(overlay.overlay, True)


def _place_skating_debug_torque(
    runtime: SteamVROverlayRuntime,
    overlays: dict[str, SkatingDebugOverlay],
    texture_cache: dict[tuple[str, int], OverlayTexture],
    x_m: float,
    y_m: float,
    z_m: float,
    torque: float,
) -> None:
    overlay = overlays.get("torque")
    if overlay is None:
        return
    if abs(torque) < 0.02:
        runtime.set_visible(overlay.overlay, False)
        return
    variant = 1 if torque > 0.0 else -1
    texture_key = ("torque", variant)
    if overlay.texture_key != texture_key:
        texture = texture_cache.get(texture_key)
        if texture is None:
            texture = _build_skating_debug_texture("torque", variant)
            texture_cache[texture_key] = texture
        runtime.request_texture_upload(overlay.overlay, texture)
        overlay.texture_key = texture_key
    _set_debug_width(runtime, overlay, 0.24)
    runtime.update_overlay_placement(
        overlay.overlay,
        OverlayPlacement(x_m=x_m, y_m=y_m, z_m=z_m, yaw_deg=0.0, pitch_deg=-90.0),
    )
    runtime.set_visible(overlay.overlay, True)


def _hide_skating_debug_overlays(
    runtime: SteamVROverlayRuntime,
    overlays: dict[str, SkatingDebugOverlay],
) -> None:
    for overlay in overlays.values():
        runtime.set_visible(overlay.overlay, False)


def _set_debug_visible(
    runtime: SteamVROverlayRuntime,
    overlays: dict[str, SkatingDebugOverlay],
    overlay_id: str,
    visible: bool,
) -> None:
    overlay = overlays.get(overlay_id)
    if overlay is not None:
        runtime.set_visible(overlay.overlay, visible)


def _set_debug_width(
    runtime: SteamVROverlayRuntime,
    overlay: SkatingDebugOverlay,
    width_m: float,
) -> None:
    if abs(overlay.width_m - width_m) < 0.01:
        return
    runtime.set_overlay_width(overlay.overlay, width_m)
    overlay.width_m = width_m


def _skating_debug_ghost_offset(
    hmd_pose: HmdPose,
    config: AppConfig,
) -> tuple[float, float]:
    forward_x = hmd_pose.direction[0]
    forward_z = hmd_pose.direction[2]
    magnitude = math.hypot(forward_x, forward_z)
    if magnitude < 0.001:
        return 0.0, -config.skating.debug_ghost_forward_m
    scale = config.skating.debug_ghost_forward_m / magnitude
    return forward_x * scale, forward_z * scale


def _skating_debug_floor_y(
    trackers: list[TrackerPose],
    config: AppConfig,
) -> float:
    if trackers:
        return min(tracker.position[1] for tracker in trackers) + config.skating.debug_ghost_y_offset_m
    return config.skating.debug_ghost_y_offset_m


def _world_vector_from_calibrated(
    right: float,
    forward: float,
    yaw_deg: float,
) -> tuple[float, float]:
    yaw_rad = math.radians(yaw_deg)
    return (
        right * math.cos(yaw_rad) - forward * math.sin(yaw_rad),
        -right * math.sin(yaw_rad) - forward * math.cos(yaw_rad),
    )


def _world_vector_from_yaw(yaw_deg: float) -> tuple[float, float]:
    yaw_rad = math.radians(yaw_deg)
    return -math.sin(yaw_rad), -math.cos(yaw_rad)


def _overlay_yaw_for_world_vector(dx_m: float, dz_m: float) -> float:
    if abs(dx_m) < 0.001 and abs(dz_m) < 0.001:
        return 90.0
    return math.degrees(math.atan2(-dx_m, -dz_m)) + 90.0


def _debug_arrow_width(
    magnitude: float,
    scale_m: float,
    config: AppConfig,
) -> float:
    target_width = magnitude * scale_m
    return max(
        config.skating.debug_arrow_min_width_m,
        min(config.skating.debug_arrow_max_width_m, target_width),
    )


def _skating_tracker_height_warning(
    model: SkatingCalibrationModel,
) -> str | None:
    if len(model.feet) < 2:
        return None
    ground_heights = [foot.ground_y_m for foot in model.feet.values()]
    height_span_m = max(ground_heights) - min(ground_heights)
    if height_span_m < 0.35:
        return None
    by_side = ", ".join(
        f"{foot.side}={foot.ground_y_m:.2f} m"
        for foot in sorted(model.feet.values(), key=lambda foot: foot.side)
    )
    return (
        "Skating calibration warning: selected tracker standing heights differ "
        f"by {height_span_m:.2f} m ({by_side}). Verify both selected generic "
        "trackers are attached to feet."
    )


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
