from __future__ import annotations

import math

import openvr
import pytest

from bikeheadvr.vr_runtime import (
    SteamVROverlayRuntime,
    _copy_hmd_matrix34,
    _extract_hmd_matrix34,
    _tracking_universe_origin,
)


def test_extract_hmd_matrix_accepts_openvr_tuple_return_shape() -> None:
    matrix = openvr.HmdMatrix34_t()
    matrix.m[0][3] = 1.25

    extracted = _extract_hmd_matrix34((True, matrix))

    assert extracted is matrix


def test_extract_hmd_matrix_rejects_false_return_shape() -> None:
    matrix = openvr.HmdMatrix34_t()

    assert _extract_hmd_matrix34((False, matrix)) is None


def test_copy_hmd_matrix34_copies_all_values() -> None:
    matrix = openvr.HmdMatrix34_t()
    for row_idx in range(3):
        for col_idx in range(4):
            matrix.m[row_idx][col_idx] = row_idx * 10 + col_idx

    copied = _copy_hmd_matrix34(matrix)

    assert copied is not matrix
    for row_idx in range(3):
        for col_idx in range(4):
            assert copied.m[row_idx][col_idx] == matrix.m[row_idx][col_idx]


def test_tracking_universe_origin_maps_raw_and_standing_constants() -> None:
    assert _tracking_universe_origin("standing") == openvr.TrackingUniverseStanding
    assert (
        _tracking_universe_origin("raw")
        == openvr.TrackingUniverseRawAndUncalibrated
    )


def test_get_all_poses_passes_requested_tracking_universe() -> None:
    class FakeSystem:
        def __init__(self) -> None:
            self.origin: int | None = None

        def getDeviceToAbsoluteTrackingPose(
            self,
            origin: int,
            _predicted_s: float,
            poses: object,
        ) -> object:
            self.origin = origin
            return poses

    runtime = SteamVROverlayRuntime(tick_hz=45.0)
    fake = FakeSystem()
    runtime._system = fake

    runtime._get_all_poses(_tracking_universe_origin("raw"))

    assert fake.origin == openvr.TrackingUniverseRawAndUncalibrated


def test_raw_yaw_to_standing_yaw_uses_raw_zero_transform() -> None:
    class FakeSystem:
        def getRawZeroPoseToStandingAbsoluteTrackingPose(
            self,
        ) -> openvr.HmdMatrix34_t:
            matrix = openvr.HmdMatrix34_t()
            yaw_rad = math.radians(90.0)
            matrix.m[0][0] = math.cos(yaw_rad)
            matrix.m[0][2] = math.sin(yaw_rad)
            matrix.m[1][1] = 1.0
            matrix.m[2][0] = -math.sin(yaw_rad)
            matrix.m[2][2] = math.cos(yaw_rad)
            return matrix

    runtime = SteamVROverlayRuntime(tick_hz=45.0)
    runtime._system = FakeSystem()

    assert runtime.get_raw_zero_to_standing_transform()[0][0] == pytest.approx(0.0)
    assert runtime.raw_yaw_to_standing_yaw(0.0) == pytest.approx(90.0)
