from __future__ import annotations

import importlib.metadata
import json
import logging
import math
import os
import uuid
from dataclasses import dataclass
from time import sleep

import openvr
from openvr.error_code import OpenVRError

from .config import ButtonConfig, OverlayPlacement
from .gpu_textures import OpenGLTextureManager
from .overlay_ui import OverlayTexture

LOGGER = logging.getLogger(__name__)


class RuntimeInitError(RuntimeError):
    """Raised when the OpenVR runtime cannot be initialized."""


@dataclass(frozen=True)
class OverlayHandle:
    value: int


@dataclass(frozen=True)
class GazeRay:
    source: tuple[float, float, float]
    direction: tuple[float, float, float]


@dataclass(frozen=True)
class HmdPose:
    position: tuple[float, float, float]
    direction: tuple[float, float, float]


@dataclass(frozen=True)
class TrackerPose:
    device_index: int
    serial: str
    position: tuple[float, float, float]


@dataclass(frozen=True)
class OverlayIntersection:
    uv: tuple[float, float]
    distance: float


def _rotation_matrix_xyz(
    yaw_deg: float, pitch_deg: float, roll_deg: float
) -> list[list[float]]:
    yaw = math.radians(yaw_deg)
    pitch = math.radians(pitch_deg)
    roll = math.radians(roll_deg)

    cy, sy = math.cos(yaw), math.sin(yaw)
    cx, sx = math.cos(pitch), math.sin(pitch)
    cz, sz = math.cos(roll), math.sin(roll)

    ry = [[cy, 0.0, sy], [0.0, 1.0, 0.0], [-sy, 0.0, cy]]
    rx = [[1.0, 0.0, 0.0], [0.0, cx, -sx], [0.0, sx, cx]]
    rz = [[cz, -sz, 0.0], [sz, cz, 0.0], [0.0, 0.0, 1.0]]
    return _matmul(_matmul(ry, rx), rz)


def _matmul(a: list[list[float]], b: list[list[float]]) -> list[list[float]]:
    return [
        [
            sum(row[k] * b[k][col_idx] for k in range(len(b)))
            for col_idx in range(len(b[0]))
        ]
        for row in a
    ]


def make_hmd_matrix34(placement: OverlayPlacement) -> openvr.HmdMatrix34_t:
    rotation = _rotation_matrix_xyz(
        yaw_deg=placement.yaw_deg,
        pitch_deg=placement.pitch_deg,
        roll_deg=placement.roll_deg,
    )
    matrix = openvr.HmdMatrix34_t()
    for row_idx in range(3):
        for col_idx in range(3):
            matrix.m[row_idx][col_idx] = rotation[row_idx][col_idx]
    matrix.m[0][3] = placement.x_m
    matrix.m[1][3] = placement.y_m
    matrix.m[2][3] = placement.z_m
    return matrix


class SteamVROverlayRuntime:
    def __init__(self, tick_hz: float) -> None:
        self.tick_hz = tick_hz
        self._system: openvr.IVRSystem | None = None
        self._overlay_api: openvr.IVROverlay | None = None
        self._texture_manager: OpenGLTextureManager | None = None
        self._created_overlays: dict[str, OverlayHandle] = {}
        self._initialized = False
        self._session_key_suffix = uuid.uuid4().hex[:8]

    def initialize(self) -> None:
        try:
            _log_openvr_diagnostics()
            runtime_path = openvr.getRuntimePath()
            LOGGER.info("OpenVR runtime path: %s", runtime_path)
            _log_steamvr_version(runtime_path)
            _log_vrserver_running()
            self._system = openvr.init(openvr.VRApplication_Overlay)
            self._overlay_api = openvr.VROverlay()
            self._texture_manager = OpenGLTextureManager()
            self._initialized = True
        except OpenVRError as exc:
            raise RuntimeInitError(self._format_init_error(exc)) from exc

    def create_overlay(self, button: ButtonConfig) -> OverlayHandle:
        if self._overlay_api is None:
            raise RuntimeError("OpenVR overlay API is not initialized")

        session_key = f"{button.key}.{self._session_key_suffix}"
        handle = self._overlay_api.createOverlay(session_key, button.label)
        self._overlay_api.setOverlayWidthInMeters(handle, button.width_m)
        self._overlay_api.setOverlayAlpha(handle, button.alpha)
        self._overlay_api.setOverlayInputMethod(
            handle, openvr.VROverlayInputMethod_None
        )
        self._overlay_api.setOverlayFlag(
            handle, openvr.VROverlayFlags_NoDashboardTab, True
        )
        self._overlay_api.setOverlayTransformAbsolute(
            handle,
            openvr.TrackingUniverseStanding,
            make_hmd_matrix34(button.placement),
        )
        overlay = OverlayHandle(value=handle)
        self._created_overlays[button.id] = overlay
        return overlay

    def update_overlay_placement(
        self, overlay: OverlayHandle, placement: OverlayPlacement
    ) -> None:
        if self._overlay_api is None:
            raise RuntimeError("OpenVR overlay API is not initialized")
        self._overlay_api.setOverlayTransformAbsolute(
            overlay.value,
            openvr.TrackingUniverseStanding,
            make_hmd_matrix34(placement),
        )

    def update_overlay_placement_relative_to_hmd(
        self, overlay: OverlayHandle, placement: OverlayPlacement
    ) -> None:
        if self._overlay_api is None:
            raise RuntimeError("OpenVR overlay API is not initialized")
        self._overlay_api.setOverlayTransformTrackedDeviceRelative(
            overlay.value,
            openvr.k_unTrackedDeviceIndex_Hmd,
            make_hmd_matrix34(placement),
        )

    def request_texture_upload(
        self, overlay: OverlayHandle, texture: OverlayTexture
    ) -> None:
        if self._overlay_api is None or self._texture_manager is None:
            raise RuntimeError("OpenVR overlay API is not initialized")

        if overlay.value not in {
            created.value for created in self._created_overlays.values()
        }:
            raise RuntimeError("Overlay handle is not tracked by this runtime")

        try:
            vr_texture = self._texture_manager.get_vr_texture(overlay.value)
        except KeyError:
            self._texture_manager.create_overlay_texture(overlay.value, texture)
            vr_texture = self._texture_manager.get_vr_texture(overlay.value)
            self._apply_texture_bounds(overlay)
            self._overlay_api.setOverlayTexture(overlay.value, vr_texture)
        else:
            self._texture_manager.update_overlay_texture(overlay.value, texture)
            self._overlay_api.setOverlayTexture(overlay.value, vr_texture)

    def set_visible(self, overlay: OverlayHandle, visible: bool) -> None:
        if self._overlay_api is None:
            raise RuntimeError("OpenVR overlay API is not initialized")
        if visible:
            self._overlay_api.showOverlay(overlay.value)
        else:
            self._overlay_api.hideOverlay(overlay.value)

    def get_hmd_pose(self) -> HmdPose | None:
        poses = self._get_all_poses()
        if poses is None:
            return None
        hmd_pose = poses[openvr.k_unTrackedDeviceIndex_Hmd]
        if not hmd_pose.bPoseIsValid:
            return None

        matrix = hmd_pose.mDeviceToAbsoluteTracking
        source = (matrix.m[0][3], matrix.m[1][3], matrix.m[2][3])
        direction = _normalize((-matrix.m[0][2], -matrix.m[1][2], -matrix.m[2][2]))
        return HmdPose(position=source, direction=direction)

    def get_tracker_poses(self) -> list[TrackerPose]:
        poses = self._get_all_poses()
        if poses is None or self._system is None:
            return []

        tracker_poses: list[TrackerPose] = []
        for device_index in range(openvr.k_unMaxTrackedDeviceCount):
            if device_index == openvr.k_unTrackedDeviceIndex_Hmd:
                continue
            if (
                self._system.getTrackedDeviceClass(device_index)
                != openvr.TrackedDeviceClass_GenericTracker
            ):
                continue
            pose = poses[device_index]
            if not pose.bPoseIsValid:
                continue
            matrix = pose.mDeviceToAbsoluteTracking
            tracker_poses.append(
                TrackerPose(
                    device_index=device_index,
                    serial=self._get_device_serial(device_index),
                    position=(matrix.m[0][3], matrix.m[1][3], matrix.m[2][3]),
                )
            )
        return tracker_poses

    def _get_all_poses(
        self,
    ) -> tuple[openvr.TrackedDevicePose_t, ...] | None:
        if self._system is None:
            raise RuntimeError("OpenVR system is not initialized")

        poses = (openvr.TrackedDevicePose_t * openvr.k_unMaxTrackedDeviceCount)()
        poses = self._system.getDeviceToAbsoluteTrackingPose(
            openvr.TrackingUniverseStanding,
            0.0,
            poses,
        )
        return tuple(poses)

    def get_hmd_gaze_ray(self) -> GazeRay | None:
        hmd_pose = self.get_hmd_pose()
        if hmd_pose is None:
            return None
        return GazeRay(source=hmd_pose.position, direction=hmd_pose.direction)

    def get_hmd_yaw_deg(self) -> float | None:
        hmd_pose = self.get_hmd_pose()
        if hmd_pose is None:
            return None
        return math.degrees(math.atan2(-hmd_pose.direction[0], -hmd_pose.direction[2]))

    def compute_overlay_intersection(
        self,
        overlay: OverlayHandle,
        gaze_ray: GazeRay,
    ) -> OverlayIntersection | None:
        if self._overlay_api is None:
            raise RuntimeError("OpenVR overlay API is not initialized")

        params = openvr.VROverlayIntersectionParams_t()
        params.eOrigin = openvr.TrackingUniverseStanding
        for idx, value in enumerate(gaze_ray.source):
            params.vSource.v[idx] = value
        for idx, value in enumerate(gaze_ray.direction):
            params.vDirection.v[idx] = value

        hit, results = self._overlay_api.computeOverlayIntersection(
            overlay.value, params
        )
        if not hit:
            return None
        return OverlayIntersection(
            uv=(results.vUVs.v[0], results.vUVs.v[1]),
            distance=results.fDistance,
        )

    def wait_frame(self) -> None:
        timeout_s = 1.0 / self.tick_hz
        sleep(timeout_s)

    def pump_overlay_events(self) -> None:
        return

    def shutdown(self) -> None:
        if self._overlay_api is not None:
            for overlay in self._created_overlays.values():
                try:
                    self._overlay_api.hideOverlay(overlay.value)
                except OpenVRError:
                    LOGGER.debug("Overlay hide failed during shutdown", exc_info=True)
                try:
                    self._overlay_api.destroyOverlay(overlay.value)
                except OpenVRError:
                    LOGGER.debug(
                        "Overlay destroy failed during shutdown", exc_info=True
                    )
            self._created_overlays.clear()
        if self._texture_manager is not None:
            self._texture_manager.destroy()
            self._texture_manager = None

        if self._initialized:
            openvr.shutdown()
            self._initialized = False
            self._overlay_api = None
            self._system = None

    def _format_init_error(self, exc: OpenVRError) -> str:
        text = str(exc)
        if "Init_NoLogPath" in text:
            steam_log_dir = os.path.join(
                os.environ.get("PROGRAMFILES(X86)", ""), "Steam", "logs"
            )
            return (
                "OpenVR failed to initialize because SteamVR could not open its log path. "
                f"Expected Steam log directory: {steam_log_dir}. "
                "This can happen inside the sandbox even when SteamVR is installed."
            )
        if "InterfaceNotFound" in text:
            return (
                "OpenVR initialization failed: SteamVR could not provide the required "
                f"interface ({openvr.IVRSystem_Version}, openvr {_openvr_package_version()}). "
                "Make sure SteamVR is running before starting bikeheadvr. "
                "If SteamVR is running: open Steam, right-click SteamVR > Properties > "
                "Local Files > Verify integrity of game files, then restart SteamVR. "
                "If the problem persists, check for SteamVR updates under Properties > Updates "
                "or try the SteamVR Beta branch (Properties > Betas). "
                f"Technical details: {text}"
            )
        return f"OpenVR initialization failed: {text}"

    def _apply_texture_bounds(self, overlay: OverlayHandle) -> None:
        if self._overlay_api is None:
            raise RuntimeError("OpenVR overlay API is not initialized")

        bounds = openvr.VRTextureBounds_t()
        bounds.uMin = 0.0
        bounds.uMax = 1.0
        bounds.vMin = 1.0
        bounds.vMax = 0.0
        self._overlay_api.setOverlayTextureBounds(overlay.value, bounds)

    def _get_device_serial(self, device_index: int) -> str:
        if self._system is None:
            raise RuntimeError("OpenVR system is not initialized")
        try:
            return self._system.getStringTrackedDeviceProperty(
                device_index,
                openvr.Prop_SerialNumber_String,
            )
        except OpenVRError:
            LOGGER.debug("Failed to read tracker serial", exc_info=True)
            return f"device_{device_index}"


def _openvr_package_version() -> str:
    try:
        return importlib.metadata.version("openvr")
    except importlib.metadata.PackageNotFoundError:
        return "unknown"


def _log_openvr_diagnostics() -> None:
    LOGGER.info("openvr package version: %s", _openvr_package_version())


def _log_steamvr_version(runtime_path: str) -> None:
    package_json = os.path.join(runtime_path, "package.json")
    try:
        with open(package_json, encoding="utf-8") as f:
            data = json.load(f)
        version = data.get("version") or data.get("Version") or "unknown"
        LOGGER.info("SteamVR package.json version: %s", version)
    except Exception:
        LOGGER.debug("Could not read SteamVR package.json at %s", package_json, exc_info=True)


def _log_vrserver_running() -> None:
    import subprocess

    try:
        result = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq vrserver.exe", "/NH", "/FO", "CSV"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        running = "vrserver.exe" in result.stdout.lower()
        if running:
            LOGGER.info("vrserver.exe is running")
        else:
            LOGGER.warning(
                "vrserver.exe not found in process list — SteamVR may not be running. "
                "Start SteamVR before launching bikeheadvr."
            )
    except Exception:
        LOGGER.debug("Could not check vrserver.exe status", exc_info=True)


def _normalize(vector: tuple[float, float, float]) -> tuple[float, float, float]:
    magnitude = math.sqrt(sum(component * component for component in vector))
    if magnitude == 0.0:
        return (0.0, 0.0, -1.0)
    return (
        vector[0] / magnitude,
        vector[1] / magnitude,
        vector[2] / magnitude,
    )
