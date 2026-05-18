from __future__ import annotations

import importlib.metadata
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
    orientation: tuple[
        tuple[float, float, float],
        tuple[float, float, float],
        tuple[float, float, float],
    ] = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
    velocity_m_s: tuple[float, float, float] = (0.0, 0.0, 0.0)
    angular_velocity_rad_s: tuple[float, float, float] = (0.0, 0.0, 0.0)


@dataclass(frozen=True)
class TrackerPose:
    device_index: int
    serial: str
    position: tuple[float, float, float]
    orientation: tuple[
        tuple[float, float, float],
        tuple[float, float, float],
        tuple[float, float, float],
    ] = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
    velocity_m_s: tuple[float, float, float] = (0.0, 0.0, 0.0)
    angular_velocity_rad_s: tuple[float, float, float] = (0.0, 0.0, 0.0)


@dataclass(frozen=True)
class DevicePose:
    device_index: int
    serial: str
    device_class: int
    device_class_name: str
    controller_role: int
    controller_role_name: str
    position: tuple[float, float, float]
    orientation: tuple[
        tuple[float, float, float],
        tuple[float, float, float],
        tuple[float, float, float],
    ] = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
    velocity_m_s: tuple[float, float, float] = (0.0, 0.0, 0.0)
    angular_velocity_rad_s: tuple[float, float, float] = (0.0, 0.0, 0.0)


@dataclass(frozen=True)
class OverlayIntersection:
    uv: tuple[float, float]
    distance: float


Matrix34Rows = tuple[
    tuple[float, float, float, float],
    tuple[float, float, float, float],
    tuple[float, float, float, float],
]


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
        self._chaperone_setup: openvr.IVRChaperoneSetup | None = None
        self._playspace_baseline: openvr.HmdMatrix34_t | None = None
        self._playspace_yaw_active = False
        self._last_playspace_yaw_deg = 0.0

    def initialize(self) -> None:
        try:
            _log_openvr_diagnostics()
            _log_openvrpaths()
            runtime_path = openvr.getRuntimePath()
            LOGGER.info("OpenVR runtime path: %s", runtime_path)
            _log_vrclient_dll(runtime_path)
            _log_vrserver_running()
            self._system = openvr.init(openvr.VRApplication_Overlay)
            self._overlay_api = openvr.VROverlay()
            self._chaperone_setup = openvr.VRChaperoneSetup()
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

    def set_overlay_width(self, overlay: OverlayHandle, width_m: float) -> None:
        if self._overlay_api is None:
            raise RuntimeError("OpenVR overlay API is not initialized")
        self._overlay_api.setOverlayWidthInMeters(overlay.value, width_m)

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
        return self._get_hmd_pose(_tracking_universe_origin("standing"))

    def get_raw_hmd_pose(self) -> HmdPose | None:
        return self._get_hmd_pose(_tracking_universe_origin("raw"))

    def _get_hmd_pose(self, origin: int) -> HmdPose | None:
        poses = self._get_all_poses(origin)
        if poses is None:
            return None
        hmd_pose = poses[openvr.k_unTrackedDeviceIndex_Hmd]
        if not hmd_pose.bPoseIsValid:
            return None

        matrix = hmd_pose.mDeviceToAbsoluteTracking
        source = (matrix.m[0][3], matrix.m[1][3], matrix.m[2][3])
        direction = _normalize((-matrix.m[0][2], -matrix.m[1][2], -matrix.m[2][2]))
        return HmdPose(
            position=source,
            direction=direction,
            orientation=_matrix34_orientation(matrix),
            velocity_m_s=_vector3(hmd_pose.vVelocity),
            angular_velocity_rad_s=_vector3(hmd_pose.vAngularVelocity),
        )

    def get_tracker_poses(self) -> list[TrackerPose]:
        return self._get_tracker_poses(_tracking_universe_origin("standing"))

    def get_raw_tracker_poses(self) -> list[TrackerPose]:
        return self._get_tracker_poses(_tracking_universe_origin("raw"))

    def _get_tracker_poses(self, origin: int) -> list[TrackerPose]:
        poses = self._get_all_poses(origin)
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
                    orientation=_matrix34_orientation(matrix),
                    velocity_m_s=_vector3(pose.vVelocity),
                    angular_velocity_rad_s=_vector3(pose.vAngularVelocity),
                )
            )
        return tracker_poses

    def get_device_poses(self, include_hmd: bool = False) -> list[DevicePose]:
        return self._get_device_poses(
            _tracking_universe_origin("standing"),
            include_hmd=include_hmd,
        )

    def get_raw_device_poses(self, include_hmd: bool = False) -> list[DevicePose]:
        return self._get_device_poses(
            _tracking_universe_origin("raw"),
            include_hmd=include_hmd,
        )

    def _get_device_poses(
        self,
        origin: int,
        *,
        include_hmd: bool = False,
    ) -> list[DevicePose]:
        poses = self._get_all_poses(origin)
        if poses is None or self._system is None:
            return []

        device_poses: list[DevicePose] = []
        for device_index in range(openvr.k_unMaxTrackedDeviceCount):
            if (
                device_index == openvr.k_unTrackedDeviceIndex_Hmd
                and not include_hmd
            ):
                continue
            pose = poses[device_index]
            if not pose.bPoseIsValid:
                continue
            device_class = self._system.getTrackedDeviceClass(device_index)
            if device_class == openvr.TrackedDeviceClass_Invalid:
                continue
            controller_role = self._controller_role(device_index, device_class)
            matrix = pose.mDeviceToAbsoluteTracking
            device_poses.append(
                DevicePose(
                    device_index=device_index,
                    serial=self._get_device_serial(device_index),
                    device_class=device_class,
                    device_class_name=_tracked_device_class_name(device_class),
                    controller_role=controller_role,
                    controller_role_name=_controller_role_name(controller_role),
                    position=(matrix.m[0][3], matrix.m[1][3], matrix.m[2][3]),
                    orientation=_matrix34_orientation(matrix),
                    velocity_m_s=_vector3(pose.vVelocity),
                    angular_velocity_rad_s=_vector3(pose.vAngularVelocity),
                )
            )
        return device_poses

    def _get_all_poses(
        self,
        origin: int = openvr.TrackingUniverseStanding,
    ) -> tuple[openvr.TrackedDevicePose_t, ...] | None:
        if self._system is None:
            raise RuntimeError("OpenVR system is not initialized")

        poses = (openvr.TrackedDevicePose_t * openvr.k_unMaxTrackedDeviceCount)()
        poses = self._system.getDeviceToAbsoluteTrackingPose(
            origin,
            0.0,
            poses,
        )
        return tuple(poses)

    def raw_yaw_to_standing_yaw(self, yaw_deg: float) -> float | None:
        matrix = self.get_raw_zero_to_standing_transform()
        if matrix is None:
            return None
        forward_raw = _forward_vector_from_yaw(yaw_deg)
        forward_standing = _matvec3(
            [list(row[:3]) for row in matrix],
            forward_raw,
        )
        horizontal_magnitude = math.hypot(forward_standing[0], forward_standing[2])
        if horizontal_magnitude < 0.001:
            return None
        return _yaw_from_forward_vector(forward_standing)

    def get_raw_zero_to_standing_transform(self) -> Matrix34Rows | None:
        if self._system is None:
            raise RuntimeError("OpenVR system is not initialized")
        try:
            matrix = self._system.getRawZeroPoseToStandingAbsoluteTrackingPose()
        except OpenVRError:
            LOGGER.debug(
                "Failed to read raw-to-standing transform",
                exc_info=True,
            )
            return None
        return _matrix34_rows(matrix)

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

    def capture_playspace_yaw_baseline(self) -> bool:
        if self._chaperone_setup is None:
            raise RuntimeError("OpenVR chaperone setup API is not initialized")
        try:
            matrix = _extract_hmd_matrix34(
                self._chaperone_setup.getWorkingStandingZeroPoseToRawTrackingPose()
            )
            if matrix is None:
                LOGGER.warning("Failed to capture playspace yaw baseline")
                return False
            self._playspace_baseline = _copy_hmd_matrix34(matrix)
            self._last_playspace_yaw_deg = 0.0
            self._playspace_yaw_active = False
            return True
        except OpenVRError:
            LOGGER.warning("Failed to capture playspace yaw baseline", exc_info=True)
            return False

    def apply_playspace_yaw_offset(
        self,
        yaw_deg: float,
        pivot_position: tuple[float, float, float],
    ) -> bool:
        if self._chaperone_setup is None:
            raise RuntimeError("OpenVR chaperone setup API is not initialized")
        if self._playspace_baseline is None and not self.capture_playspace_yaw_baseline():
            return False
        if self._playspace_baseline is None:
            return False

        try:
            matrix = _yaw_matrix_about_pivot(
                self._playspace_baseline,
                math.radians(yaw_deg),
                pivot_position,
            )
            self._chaperone_setup.setWorkingStandingZeroPoseToRawTrackingPose(matrix)
            self._chaperone_setup.showWorkingSetPreview()
            self._playspace_yaw_active = True
            self._last_playspace_yaw_deg = yaw_deg
            return True
        except OpenVRError:
            LOGGER.warning("Failed to apply playspace yaw offset", exc_info=True)
            return False

    def restore_playspace_yaw(self) -> None:
        if (
            self._chaperone_setup is None
            or self._playspace_baseline is None
            or not self._playspace_yaw_active
        ):
            return
        try:
            self._chaperone_setup.setWorkingStandingZeroPoseToRawTrackingPose(
                _copy_hmd_matrix34(self._playspace_baseline)
            )
            self._chaperone_setup.hideWorkingSetPreview()
        except OpenVRError:
            LOGGER.warning("Failed to restore playspace yaw baseline", exc_info=True)
        finally:
            self._playspace_yaw_active = False
            self._last_playspace_yaw_deg = 0.0

    def shutdown(self) -> None:
        self.restore_playspace_yaw()
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
            self._chaperone_setup = None
            self._playspace_baseline = None

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
            steam_logs = os.path.join(
                os.environ.get("PROGRAMFILES(X86)", ""), "Steam", "logs", "vrserver.txt"
            )
            return (
                "OpenVR initialization failed: could not load a required SteamVR runtime interface "
                f"({openvr.IVRSystem_Version}, openvr {_openvr_package_version()}). "
                "bikeheadvr requires SteamVR specifically — it does not work with the Meta/Oculus "
                "or Windows Mixed Reality runtimes. "
                "Open SteamVR from your Steam library and confirm it shows your headset as connected, "
                "then start bikeheadvr. "
                "If SteamVR is already open, the openvrpaths.vrpath and vrclient_x64.dll lines above "
                "in the log file will show where OpenVR is looking for its runtime. "
                f"SteamVR's own log for more detail: {steam_logs}. "
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

    def _controller_role(self, device_index: int, device_class: int) -> int:
        if (
            self._system is None
            or device_class != openvr.TrackedDeviceClass_Controller
        ):
            return openvr.TrackedControllerRole_Invalid
        try:
            return self._system.getControllerRoleForTrackedDeviceIndex(device_index)
        except OpenVRError:
            LOGGER.debug("Failed to read controller role", exc_info=True)
            return openvr.TrackedControllerRole_Invalid


def _matrix34_orientation(
    matrix: openvr.HmdMatrix34_t,
) -> tuple[
    tuple[float, float, float],
    tuple[float, float, float],
    tuple[float, float, float],
]:
    return (
        (matrix.m[0][0], matrix.m[0][1], matrix.m[0][2]),
        (matrix.m[1][0], matrix.m[1][1], matrix.m[1][2]),
        (matrix.m[2][0], matrix.m[2][1], matrix.m[2][2]),
    )


def _vector3(vector: openvr.HmdVector3_t) -> tuple[float, float, float]:
    return (float(vector.v[0]), float(vector.v[1]), float(vector.v[2]))


def _tracked_device_class_name(device_class: int) -> str:
    names = {
        openvr.TrackedDeviceClass_Invalid: "Invalid",
        openvr.TrackedDeviceClass_HMD: "HMD",
        openvr.TrackedDeviceClass_Controller: "Controller",
        openvr.TrackedDeviceClass_GenericTracker: "GenericTracker",
        openvr.TrackedDeviceClass_TrackingReference: "TrackingReference",
        openvr.TrackedDeviceClass_DisplayRedirect: "DisplayRedirect",
    }
    return names.get(device_class, f"Unknown{device_class}")


def _controller_role_name(role: int) -> str:
    names = {
        openvr.TrackedControllerRole_Invalid: "Invalid",
        openvr.TrackedControllerRole_LeftHand: "LeftHand",
        openvr.TrackedControllerRole_RightHand: "RightHand",
        openvr.TrackedControllerRole_OptOut: "OptOut",
        openvr.TrackedControllerRole_Treadmill: "Treadmill",
        openvr.TrackedControllerRole_Stylus: "Stylus",
    }
    return names.get(role, f"Unknown{role}")


def _tracking_universe_origin(name: str) -> int:
    if name == "standing":
        return openvr.TrackingUniverseStanding
    if name == "raw":
        return openvr.TrackingUniverseRawAndUncalibrated
    raise ValueError(f"Unknown tracking universe: {name}")


def _forward_vector_from_yaw(yaw_deg: float) -> tuple[float, float, float]:
    yaw_rad = math.radians(yaw_deg)
    return (-math.sin(yaw_rad), 0.0, -math.cos(yaw_rad))


def _yaw_from_forward_vector(vector: tuple[float, float, float]) -> float:
    return math.degrees(math.atan2(-vector[0], -vector[2]))


def _copy_hmd_matrix34(matrix: openvr.HmdMatrix34_t) -> openvr.HmdMatrix34_t:
    copied = openvr.HmdMatrix34_t()
    for row_idx in range(3):
        for col_idx in range(4):
            copied.m[row_idx][col_idx] = matrix.m[row_idx][col_idx]
    return copied


def _matrix34_rows(matrix: openvr.HmdMatrix34_t) -> Matrix34Rows:
    return (
        (matrix.m[0][0], matrix.m[0][1], matrix.m[0][2], matrix.m[0][3]),
        (matrix.m[1][0], matrix.m[1][1], matrix.m[1][2], matrix.m[1][3]),
        (matrix.m[2][0], matrix.m[2][1], matrix.m[2][2], matrix.m[2][3]),
    )


def _extract_hmd_matrix34(value: object) -> openvr.HmdMatrix34_t | None:
    if isinstance(value, tuple) and len(value) == 2:
        ok, matrix = value
        if not ok:
            return None
        if isinstance(matrix, openvr.HmdMatrix34_t):
            return matrix
    if isinstance(value, openvr.HmdMatrix34_t):
        return value
    return None


def _yaw_matrix_about_pivot(
    baseline: openvr.HmdMatrix34_t,
    yaw_rad: float,
    pivot_position: tuple[float, float, float],
) -> openvr.HmdMatrix34_t:
    baseline_rotation = [
        [baseline.m[row_idx][col_idx] for col_idx in range(3)]
        for row_idx in range(3)
    ]
    rotation = [
        [math.cos(yaw_rad), 0.0, math.sin(yaw_rad)],
        [0.0, 1.0, 0.0],
        [-math.sin(yaw_rad), 0.0, math.cos(yaw_rad)],
    ]
    next_rotation = _matmul(rotation, baseline_rotation)
    baseline_translation = (baseline.m[0][3], baseline.m[1][3], baseline.m[2][3])
    raw_pivot = _add3(_matvec3(baseline_rotation, pivot_position), baseline_translation)
    next_translation = _sub3(raw_pivot, _matvec3(next_rotation, pivot_position))

    matrix = openvr.HmdMatrix34_t()
    for row_idx in range(3):
        for col_idx in range(3):
            matrix.m[row_idx][col_idx] = next_rotation[row_idx][col_idx]
        matrix.m[row_idx][3] = next_translation[row_idx]
    return matrix


def _matvec3(
    matrix: list[list[float]],
    vector: tuple[float, float, float],
) -> tuple[float, float, float]:
    return (
        sum(matrix[0][idx] * vector[idx] for idx in range(3)),
        sum(matrix[1][idx] * vector[idx] for idx in range(3)),
        sum(matrix[2][idx] * vector[idx] for idx in range(3)),
    )


def _add3(
    left: tuple[float, float, float],
    right: tuple[float, float, float],
) -> tuple[float, float, float]:
    return (left[0] + right[0], left[1] + right[1], left[2] + right[2])


def _sub3(
    left: tuple[float, float, float],
    right: tuple[float, float, float],
) -> tuple[float, float, float]:
    return (left[0] - right[0], left[1] - right[1], left[2] - right[2])


def _openvr_package_version() -> str:
    try:
        return importlib.metadata.version("openvr")
    except importlib.metadata.PackageNotFoundError:
        return "unknown"


def _log_openvr_diagnostics() -> None:
    LOGGER.info("openvr package version: %s", _openvr_package_version())



def _log_openvrpaths() -> None:
    vrpath_file = os.path.join(
        os.environ.get("LOCALAPPDATA", ""), "openvr", "openvrpaths.vrpath"
    )
    try:
        with open(vrpath_file, encoding="utf-8") as f:
            contents = f.read()
        LOGGER.info("openvrpaths.vrpath (%s): %s", vrpath_file, contents.strip())
    except FileNotFoundError:
        LOGGER.warning("openvrpaths.vrpath not found at %s — OpenVR may not be configured", vrpath_file)
    except Exception:
        LOGGER.debug("Could not read openvrpaths.vrpath at %s", vrpath_file, exc_info=True)


def _log_vrclient_dll(runtime_path: str) -> None:
    dll_path = os.path.join(runtime_path, "bin", "vrclient_x64.dll")
    if os.path.exists(dll_path):
        size = os.path.getsize(dll_path)
        LOGGER.info("vrclient_x64.dll found (%d bytes): %s", size, dll_path)
    else:
        LOGGER.warning("vrclient_x64.dll not found at %s", dll_path)


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
