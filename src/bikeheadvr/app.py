from __future__ import annotations

import argparse
import logging
import signal
import sys
import time
from contextlib import suppress
from dataclasses import dataclass

from .config import AppConfig, ButtonConfig
from .interaction import ButtonVisualState, DwellTracker
from .overlay_ui import (
    OverlayTexture,
    TextureVariant,
    build_button_texture,
    quantize_visual,
)
from .vr_runtime import (
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
    dwell = DwellTracker([button.id for button in config.buttons], config.dwell)
    should_stop = False
    frames_remaining = (
        None
        if args.duration <= 0
        else max(1, int(round(args.duration * config.tick_hz)))
    )
    scene_buttons: dict[str, SceneButton] = {}
    texture_cache: dict[tuple[str, TextureVariant], OverlayTexture] = {}
    current_hover_id: str | None = None
    controls_visible = False
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
        _apply_visibility(runtime, scene_buttons, controls_visible)

        LOGGER.info("Phase 4 scene visible. Dwell on toggle to show controls.")

        while not should_stop:
            runtime.pump_overlay_events()
            gaze_ray = runtime.get_hmd_gaze_ray()
            now = time.monotonic()
            if gaze_ray is None:
                if no_pose_started_at is None:
                    no_pose_started_at = now
                elif now - no_pose_started_at >= config.osc.no_pose_failsafe_s:
                    osc.force_zero()
            else:
                no_pose_started_at = None

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
                controls_visible = _apply_commit(
                    update.committed_id,
                    osc,
                    controls_visible,
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
    texture_cache: dict[tuple[str, TextureVariant], OverlayTexture],
    scene_button: SceneButton,
    visual: ButtonVisualState,
) -> None:
    variant = quantize_visual(visual, config.render)
    if variant == scene_button.texture_variant:
        return
    cache_key = (scene_button.config.id, variant)
    texture = texture_cache.get(cache_key)
    if texture is None:
        texture = build_button_texture(scene_button.config, variant)
        texture_cache[cache_key] = texture
    runtime.request_texture_upload(scene_button.overlay, texture)
    scene_button.texture_variant = variant


def _apply_commit(
    committed_id: str,
    osc: VRChatOscController,
    controls_visible: bool,
) -> bool:
    if committed_id == "toggle":
        new_visible = not controls_visible
        if not new_visible:
            osc.force_zero()
        LOGGER.info("Controls %s", "shown" if new_visible else "hidden")
        return new_visible
    if committed_id == "forward":
        osc.set_forward()
    elif committed_id == "backward":
        osc.set_backward()
    elif committed_id == "stop":
        osc.stop_all()
    return controls_visible


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
