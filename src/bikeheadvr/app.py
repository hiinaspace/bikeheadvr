from __future__ import annotations

import argparse
import logging
import signal
import sys
from contextlib import suppress
from dataclasses import dataclass

from .config import AppConfig, ButtonConfig
from .overlay_ui import build_button_texture
from .vr_runtime import OverlayIntersection, OverlayHandle, RuntimeInitError, SteamVROverlayRuntime

LOGGER = logging.getLogger(__name__)


@dataclass
class SceneButton:
    config: ButtonConfig
    overlay: OverlayHandle
    hovered: bool = False


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="bikeheadvr Phase 2 gaze hit testing")
    parser.add_argument("--duration", type=float, default=0.0)
    parser.add_argument("--verbose", action="store_true")
    return parser.parse_args(argv)


def configure_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    configure_logging(args.verbose)

    config = AppConfig()
    runtime = SteamVROverlayRuntime(tick_hz=config.tick_hz)
    should_stop = False
    frames_remaining = None if args.duration <= 0 else max(1, int(round(args.duration * config.tick_hz)))
    scene_buttons: dict[str, SceneButton] = {}
    current_hover_id: str | None = None

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
            runtime.upload_texture(overlay, build_button_texture(button, hovered=False))
            runtime.set_visible(overlay, button.always_visible)
            scene_buttons[button.id] = SceneButton(config=button, overlay=overlay)

        LOGGER.info("Phase 2 scene visible. Move your head to hover targets.")

        while not should_stop:
            gaze_ray = runtime.get_hmd_gaze_ray()
            best_hit: tuple[str, OverlayIntersection] | None = None
            if gaze_ray is not None:
                for button_id, scene_button in scene_buttons.items():
                    hit = runtime.compute_overlay_intersection(scene_button.overlay, gaze_ray)
                    if hit is None:
                        continue
                    if best_hit is None or hit.distance < best_hit[1].distance:
                        best_hit = (button_id, hit)

            new_hover_id = best_hit[0] if best_hit is not None else None
            if new_hover_id != current_hover_id:
                for button_id, scene_button in scene_buttons.items():
                    hovered = button_id == new_hover_id
                    if hovered == scene_button.hovered:
                        continue
                    scene_button.hovered = hovered
                    runtime.upload_texture(
                        scene_button.overlay,
                        build_button_texture(scene_button.config, hovered=hovered),
                    )
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
        runtime.shutdown()

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
