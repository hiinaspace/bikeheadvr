from __future__ import annotations

import logging
import math
import os
from ctypes import create_string_buffer
from dataclasses import dataclass
from time import sleep

import openvr
from openvr.error_code import OpenVRError

from .config import AppConfig, OverlayPlacement
from .overlay_ui import OverlayTexture

LOGGER = logging.getLogger(__name__)


class RuntimeInitError(RuntimeError):
    """Raised when the OpenVR runtime cannot be initialized."""


@dataclass(frozen=True)
class OverlayHandle:
    value: int


def _rotation_matrix_xyz(yaw_deg: float, pitch_deg: float, roll_deg: float) -> list[list[float]]:
    yaw = math.radians(yaw_deg)
    pitch = math.radians(pitch_deg)
    roll = math.radians(roll_deg)

    cy, sy = math.cos(yaw), math.sin(yaw)
    cx, sx = math.cos(pitch), math.sin(pitch)
    cz, sz = math.cos(roll), math.sin(roll)

    ry = [
        [cy, 0.0, sy],
        [0.0, 1.0, 0.0],
        [-sy, 0.0, cy],
    ]
    rx = [
        [1.0, 0.0, 0.0],
        [0.0, cx, -sx],
        [0.0, sx, cx],
    ]
    rz = [
        [cz, -sz, 0.0],
        [sz, cz, 0.0],
        [0.0, 0.0, 1.0],
    ]
    return _matmul(_matmul(ry, rx), rz)


def _matmul(a: list[list[float]], b: list[list[float]]) -> list[list[float]]:
    result: list[list[float]] = []
    for row in a:
        out_row: list[float] = []
        for col_idx in range(len(b[0])):
            out_row.append(sum(row[k] * b[k][col_idx] for k in range(len(b))))
        result.append(out_row)
    return result


def make_hmd_matrix34(placement: OverlayPlacement) -> openvr.HmdMatrix34_t:
    rotation = _rotation_matrix_xyz(
        yaw_deg=placement.yaw_deg,
        pitch_deg=placement.pitch_deg,
        roll_deg=placement.roll_deg,
    )
    matrix = openvr.HmdMatrix34_t()
    matrix.m[0][0] = rotation[0][0]
    matrix.m[0][1] = rotation[0][1]
    matrix.m[0][2] = rotation[0][2]
    matrix.m[0][3] = placement.x_m
    matrix.m[1][0] = rotation[1][0]
    matrix.m[1][1] = rotation[1][1]
    matrix.m[1][2] = rotation[1][2]
    matrix.m[1][3] = placement.y_m
    matrix.m[2][0] = rotation[2][0]
    matrix.m[2][1] = rotation[2][1]
    matrix.m[2][2] = rotation[2][2]
    matrix.m[2][3] = placement.z_m
    return matrix


class SteamVROverlayRuntime:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self._overlay_api: openvr.IVROverlay | None = None
        self._overlay_handle: OverlayHandle | None = None
        self._initialized = False

    def initialize(self) -> None:
        try:
            runtime_path = openvr.getRuntimePath()
            LOGGER.info("OpenVR runtime path: %s", runtime_path)
            openvr.init(openvr.VRApplication_Overlay)
            self._overlay_api = openvr.VROverlay()
            self._initialized = True
        except OpenVRError as exc:
            raise RuntimeInitError(self._format_init_error(exc)) from exc

    def create_main_overlay(self) -> OverlayHandle:
        if self._overlay_api is None:
            raise RuntimeError("OpenVR overlay API is not initialized")

        handle = self._overlay_api.createOverlay(
            self.config.overlay.key,
            self.config.overlay.name,
        )
        self._overlay_api.setOverlayWidthInMeters(handle, self.config.overlay.width_m)
        self._overlay_api.setOverlayAlpha(handle, self.config.overlay.alpha)
        self._overlay_api.setOverlayInputMethod(handle, openvr.VROverlayInputMethod_None)
        self._overlay_api.setOverlayFlag(handle, openvr.VROverlayFlags_NoDashboardTab, True)
        self._overlay_api.setOverlayTransformAbsolute(
            handle,
            openvr.TrackingUniverseStanding,
            make_hmd_matrix34(self.config.overlay.placement),
        )
        self._overlay_handle = OverlayHandle(value=handle)
        return self._overlay_handle

    def upload_texture(self, overlay: OverlayHandle, texture: OverlayTexture) -> None:
        if self._overlay_api is None:
            raise RuntimeError("OpenVR overlay API is not initialized")

        buffer = create_string_buffer(texture.rgba_bytes, len(texture.rgba_bytes))
        self._overlay_api.setOverlayRaw(
            overlay.value,
            buffer,
            texture.width_px,
            texture.height_px,
            4,
        )

    def show_overlay(self, overlay: OverlayHandle) -> None:
        if self._overlay_api is None:
            raise RuntimeError("OpenVR overlay API is not initialized")
        self._overlay_api.showOverlay(overlay.value)

    def wait_frame(self) -> None:
        if self._overlay_api is None:
            raise RuntimeError("OpenVR overlay API is not initialized")

        timeout_ms = max(1, int(round(1000.0 / self.config.tick_hz)))
        try:
            self._overlay_api.waitFrameSync(timeout_ms)
        except OpenVRError:
            sleep(1.0 / self.config.tick_hz)

    def shutdown(self) -> None:
        if self._overlay_api is not None and self._overlay_handle is not None:
            try:
                self._overlay_api.hideOverlay(self._overlay_handle.value)
            except OpenVRError:
                LOGGER.debug("Overlay hide failed during shutdown", exc_info=True)
            try:
                self._overlay_api.destroyOverlay(self._overlay_handle.value)
            except OpenVRError:
                LOGGER.debug("Overlay destroy failed during shutdown", exc_info=True)
            self._overlay_handle = None

        if self._initialized:
            openvr.shutdown()
            self._initialized = False
            self._overlay_api = None

    def _format_init_error(self, exc: OpenVRError) -> str:
        text = str(exc)
        if "Init_NoLogPath" in text:
            steam_log_dir = os.path.join(os.environ.get("PROGRAMFILES(X86)", ""), "Steam", "logs")
            return (
                "OpenVR failed to initialize because SteamVR could not open its log path. "
                f"Expected Steam log directory: {steam_log_dir}. "
                "This can happen inside the sandbox even when SteamVR is installed."
            )
        return f"OpenVR initialization failed: {text}"
