from __future__ import annotations

import argparse
import logging
import math
import signal
import sys
import time
from contextlib import suppress
from dataclasses import dataclass

from .calibration import CalibrationController
from .config import AppConfig, ButtonConfig, OverlayPlacement
from .interaction import ButtonVisualState, DwellTracker
from .overlay_ui import (
    OverlayTexture,
    TextureVariant,
    build_button_texture,
    quantize_visual,
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
    parser = argparse.ArgumentParser(description="bikeheadvr Phase 4 OSC locomotion")
    parser.add_argument("--duration", type=float, default=0.0)
    parser.add_argument("--verbose", action="store_true")
    return parser.parse_args(argv)


def configure_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    configure_logging(args.verbose)

    config = AppConfig()
    runtime = SteamVROverlayRuntime(tick_hz=config.tick_hz)
    osc = VRChatOscController(config.osc)
    calibration = CalibrationController(config.calibration)
    dwell = DwellTracker([button.id for button in config.buttons], config.dwell)
    should_stop = False
    frames_remaining = (
        None
        if args.duration <= 0
        else max(1, int(round(args.duration * config.tick_hz)))
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
    no_pose_started_at: float | None = None
    turn_hold_id: str | None = None

    def request_stop(signum: int, _frame: object) -> None:
        nonlocal should_stop
        LOGGER.info("Received signal %s, shutting down.", signum)
        should_stop = True

    for signum in (signal.SIGINT, signal.SIGTERM):
        with suppress(ValueError):
            signal.signal(signum, request_stop)

    try:
        LOGGER.info("%s", config.startup_banner)
        runtime.initialize()

        for button in config.buttons:
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

        LOGGER.info(
            "Phase 5 scene visible. Dwell on toggle to calibrate and show controls."
        )

        while not should_stop:
            runtime.pump_overlay_events()
            now = time.monotonic()
            hmd_pose = runtime.get_hmd_pose()
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

            turn_hold_id = _apply_turn_hold(
                osc, new_hover_id, controls_visible, turn_hold_id
            )
            _apply_drive_compensation(
                osc,
                latched_drive_id,
                controls_visible,
                hmd_pose,
                calibrated_yaw_deg,
                config,
            )

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
                LOGGER.info(
                    "Calibration complete center=(%.2f, %.2f) yaw=%.1f deg",
                    calibrated_center_x_m,
                    calibrated_center_z_m,
                    calibrated_yaw_deg,
                )
                _apply_calibrated_placements(
                    runtime,
                    scene_buttons,
                    calibrated_center_x_m,
                    calibrated_center_z_m,
                    calibrated_yaw_deg,
                )
                _apply_visibility(runtime, scene_buttons, controls_visible)

            if calibration_overlay is not None and (
                calibration_overlay.title_text != calibration_status.title_text
                or calibration_overlay.subtitle_text != calibration_status.subtitle_text
            ):
                calibration_overlay.title_text = calibration_status.title_text
                calibration_overlay.subtitle_text = calibration_status.subtitle_text
                _apply_visual(
                    runtime,
                    config,
                    texture_cache,
                    calibration_overlay,
                    calibration_overlay.visual,
                )
            if calibration_overlay is not None:
                runtime.set_visible(
                    calibration_overlay.overlay, calibration_status.active
                )

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
                controls_visible, latched_drive_id = _apply_commit(
                    update.committed_id,
                    now,
                    osc,
                    calibration,
                    controls_visible,
                    latched_drive_id,
                )
                if update.committed_id in {"left", "right"}:
                    if update.committed_id == "left":
                        osc.pulse_comfort_left()
                    else:
                        osc.pulse_comfort_right()
                    turn_hold_id = update.committed_id
                    turn_hover_id = (
                        new_hover_id if new_hover_id == turn_hold_id else None
                    )
                    turn_hold_id = _apply_turn_hold(
                        osc,
                        turn_hover_id,
                        controls_visible,
                        turn_hold_id,
                    )
                elif update.committed_id in {"stop", "toggle"}:
                    turn_hold_id = _apply_turn_hold(osc, None, controls_visible, None)
                _apply_drive_compensation(
                    osc,
                    latched_drive_id,
                    controls_visible,
                    hmd_pose,
                    calibrated_yaw_deg,
                    config,
                )
                _apply_visibility(runtime, scene_buttons, controls_visible)

            osc.sync()

            runtime.wait_frame()
            if frames_remaining is not None:
                frames_remaining -= 1
                if frames_remaining <= 0:
                    LOGGER.info("Requested duration elapsed, shutting down.")
                    break
    except RuntimeInitError as exc:
        LOGGER.error("%s", exc)
        return 1
    except KeyboardInterrupt:
        LOGGER.info("Interrupted, shutting down.")
    finally:
        osc.force_zero()
        runtime.shutdown()

    return 0


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
    controls_visible: bool,
    latched_drive_id: str | None,
) -> tuple[bool, str | None]:
    if committed_id == "toggle":
        if controls_visible:
            osc.force_zero()
            LOGGER.info("Controls hidden")
            return False, None
        calibration.start(now)
        osc.clear_motion()
        LOGGER.info("Calibration started")
        return False, None
    if committed_id == "forward":
        return controls_visible, "forward"
    elif committed_id == "backward":
        return controls_visible, "backward"
    elif committed_id == "stop":
        osc.stop_all()
        return controls_visible, None
    return controls_visible, latched_drive_id


def _apply_visibility(
    runtime: SteamVROverlayRuntime,
    scene_buttons: dict[str, SceneButton],
    controls_visible: bool,
) -> None:
    for button_id, scene_button in scene_buttons.items():
        visible = controls_visible or button_id == "toggle"
        runtime.set_visible(scene_button.overlay, visible)


def _is_button_interactable(button_id: str, controls_visible: bool) -> bool:
    return controls_visible or button_id == "toggle"


def _apply_turn_hold(
    osc: VRChatOscController,
    hover_id: str | None,
    controls_visible: bool,
    turn_hold_id: str | None,
) -> str | None:
    if not controls_visible:
        osc.clear_turn()
        return None
    if turn_hold_id == "left" and hover_id == "left":
        osc.press_turn_left()
        return "left"
    if turn_hold_id == "right" and hover_id == "right":
        osc.press_turn_right()
        return "right"
    if turn_hold_id is not None:
        osc.clear_turn()
    return None


def _apply_drive_compensation(
    osc: VRChatOscController,
    latched_drive_id: str | None,
    controls_visible: bool,
    hmd_pose: HmdPose | None,
    calibrated_yaw_deg: float,
    config: AppConfig,
) -> None:
    if not controls_visible or latched_drive_id is None or hmd_pose is None:
        osc.clear_motion()
        return

    drive_scalar = 0.0
    if latched_drive_id == "forward":
        drive_scalar = config.osc.vertical_axis
    elif latched_drive_id == "backward":
        drive_scalar = config.osc.backward_axis

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
