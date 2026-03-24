from __future__ import annotations

import logging
from dataclasses import dataclass

from pythonosc.udp_client import SimpleUDPClient

from .config import OscConfig

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class MovementIntent:
    horizontal: float = 0.0
    vertical: float = 0.0
    look_left: int = 0
    look_right: int = 0


class VRChatOscController:
    def __init__(self, config: OscConfig) -> None:
        self._config = config
        self._client = SimpleUDPClient(config.host, config.port)
        self._intended = MovementIntent()
        self._emitted = MovementIntent()

    @property
    def intended(self) -> MovementIntent:
        return self._intended

    def set_motion_axes(self, horizontal: float, vertical: float) -> None:
        next_intent = MovementIntent(
            horizontal=float(horizontal),
            vertical=float(vertical),
            look_left=self._intended.look_left,
            look_right=self._intended.look_right,
        )
        if next_intent != self._intended:
            self._intended = next_intent
            LOGGER.info(
                "Intent motion horizontal=%.2f vertical=%.2f",
                self._intended.horizontal,
                self._intended.vertical,
            )

    def clear_motion(self) -> None:
        next_intent = MovementIntent(
            horizontal=0.0,
            vertical=0.0,
            look_left=self._intended.look_left,
            look_right=self._intended.look_right,
        )
        if next_intent != self._intended:
            self._intended = next_intent
            LOGGER.info("Intent motion cleared")

    def press_turn_left(self) -> None:
        next_intent = MovementIntent(
            horizontal=self._intended.horizontal,
            vertical=self._intended.vertical,
            look_left=1,
            look_right=0,
        )
        if next_intent != self._intended:
            self._intended = next_intent
            LOGGER.info("Intent turn left pressed")

    def press_turn_right(self) -> None:
        next_intent = MovementIntent(
            horizontal=self._intended.horizontal,
            vertical=self._intended.vertical,
            look_left=0,
            look_right=1,
        )
        if next_intent != self._intended:
            self._intended = next_intent
            LOGGER.info("Intent turn right pressed")

    def clear_turn(self) -> None:
        next_intent = MovementIntent(
            horizontal=self._intended.horizontal,
            vertical=self._intended.vertical,
            look_left=0,
            look_right=0,
        )
        if next_intent != self._intended:
            self._intended = next_intent

    def stop_all(self) -> None:
        next_intent = MovementIntent()
        if next_intent != self._intended:
            self._intended = next_intent
            LOGGER.info("Intent stop all")

    def pulse_comfort_left(self) -> None:
        LOGGER.info("Pulse comfort left")
        self._send_button("/input/ComfortLeft", 1)
        self._send_button("/input/ComfortLeft", 0)

    def pulse_comfort_right(self) -> None:
        LOGGER.info("Pulse comfort right")
        self._send_button("/input/ComfortRight", 1)
        self._send_button("/input/ComfortRight", 0)

    def sync(self) -> None:
        if self._intended.horizontal != self._emitted.horizontal:
            self._send_axis("/input/Horizontal", self._intended.horizontal)
        if self._intended.vertical != self._emitted.vertical:
            self._send_axis("/input/Vertical", self._intended.vertical)
        if self._intended.look_left != self._emitted.look_left:
            self._send_button("/input/LookLeft", self._intended.look_left)
        if self._intended.look_right != self._emitted.look_right:
            self._send_button("/input/LookRight", self._intended.look_right)

    def force_zero(self) -> None:
        self._intended = MovementIntent()
        if self._emitted != MovementIntent():
            LOGGER.info("Failsafe zero")
        self._send_axis("/input/Horizontal", 0.0)
        self._send_axis("/input/Vertical", 0.0)
        self._send_button("/input/LookLeft", 0)
        self._send_button("/input/LookRight", 0)

    def _send_axis(self, address: str, value: float) -> None:
        self._client.send_message(address, float(value))
        if address == "/input/Horizontal":
            self._emitted = MovementIntent(
                horizontal=float(value),
                vertical=self._emitted.vertical,
                look_left=self._emitted.look_left,
                look_right=self._emitted.look_right,
            )
        elif address == "/input/Vertical":
            self._emitted = MovementIntent(
                horizontal=self._emitted.horizontal,
                vertical=float(value),
                look_left=self._emitted.look_left,
                look_right=self._emitted.look_right,
            )

    def _send_button(self, address: str, value: int) -> None:
        self._client.send_message(address, int(value))
        if address == "/input/LookLeft":
            self._emitted = MovementIntent(
                horizontal=self._emitted.horizontal,
                vertical=self._emitted.vertical,
                look_left=int(value),
                look_right=self._emitted.look_right,
            )
        elif address == "/input/LookRight":
            self._emitted = MovementIntent(
                horizontal=self._emitted.horizontal,
                vertical=self._emitted.vertical,
                look_left=self._emitted.look_left,
                look_right=int(value),
            )
