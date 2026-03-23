from __future__ import annotations

import argparse
import logging
import signal
import sys
from contextlib import suppress

from .config import AppConfig
from .overlay_ui import build_phase1_texture
from .vr_runtime import RuntimeInitError, SteamVROverlayRuntime

LOGGER = logging.getLogger(__name__)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="bikeheadvr Phase 1 static overlay")
    parser.add_argument(
        "--duration",
        type=float,
        default=0.0,
        help="Optional number of seconds to keep the overlay alive before exiting.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable debug logging.",
    )
    return parser.parse_args(argv)


def configure_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    configure_logging(args.verbose)

    config = AppConfig()
    runtime = SteamVROverlayRuntime(config)
    should_stop = False
    frames_remaining = None

    if args.duration > 0:
        frames_remaining = max(1, int(round(args.duration * config.tick_hz)))

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
        overlay = runtime.create_main_overlay()
        texture = build_phase1_texture(config.overlay.texture)
        runtime.upload_texture(overlay, texture)
        runtime.show_overlay(overlay)
        LOGGER.info("Overlay visible. Press Ctrl+C to exit.")

        while not should_stop:
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
