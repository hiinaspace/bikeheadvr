from __future__ import annotations

import math

import openvr
import pytest

from bikeheadvr.vr_runtime import (
    SteamVROverlayRuntime,
    _baseline_standing_position_from_raw,
    _copy_hmd_matrix34,
    _extract_hmd_matrix34,
    _is_safe_playspace_baseline,
    _is_safe_playspace_matrix,
    _tracking_universe_origin,
    _yaw_matrix_about_pivot,
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
    assert _tracking_universe_origin("raw") == openvr.TrackingUniverseRawAndUncalibrated


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


def test_raw_pivot_is_converted_to_baseline_standing_space() -> None:
    baseline = openvr.HmdMatrix34_t()
    yaw_rad = math.radians(90.0)
    baseline.m[0][0] = math.cos(yaw_rad)
    baseline.m[0][2] = math.sin(yaw_rad)
    baseline.m[1][1] = 1.0
    baseline.m[2][0] = -math.sin(yaw_rad)
    baseline.m[2][2] = math.cos(yaw_rad)
    baseline.m[0][3] = 1.0
    baseline.m[2][3] = 2.0

    standing_pivot = (0.5, 0.0, -1.0)
    raw_pivot = (
        baseline.m[0][0] * standing_pivot[0]
        + baseline.m[0][2] * standing_pivot[2]
        + baseline.m[0][3],
        0.0,
        baseline.m[2][0] * standing_pivot[0]
        + baseline.m[2][2] * standing_pivot[2]
        + baseline.m[2][3],
    )

    converted = _baseline_standing_position_from_raw(baseline, raw_pivot)

    assert converted == pytest.approx(standing_pivot)


def test_playspace_matrix_safety_rejects_huge_translation() -> None:
    baseline = openvr.HmdMatrix34_t()
    baseline.m[0][0] = 1.0
    baseline.m[1][1] = 1.0
    baseline.m[2][2] = 1.0
    safe = _yaw_matrix_about_pivot(
        baseline,
        math.radians(45.0),
        (0.0, 0.0, -1.0),
    )
    unsafe = _copy_hmd_matrix34(safe)
    unsafe.m[0][3] = 25000.0

    assert _is_safe_playspace_baseline(baseline)
    assert _is_safe_playspace_matrix(safe, baseline)
    assert not _is_safe_playspace_matrix(unsafe, baseline)


def test_apply_playspace_yaw_from_raw_pivot_rejects_feedback_pivot() -> None:
    class FakeChaperone:
        def __init__(self) -> None:
            self.baseline = openvr.HmdMatrix34_t()
            self.baseline.m[0][0] = 1.0
            self.baseline.m[1][1] = 1.0
            self.baseline.m[2][2] = 1.0
            self.set_calls = 0

        def getWorkingStandingZeroPoseToRawTrackingPose(
            self,
        ) -> openvr.HmdMatrix34_t:
            return self.baseline

        def setWorkingStandingZeroPoseToRawTrackingPose(
            self,
            _matrix: openvr.HmdMatrix34_t,
        ) -> None:
            self.set_calls += 1

        def showWorkingSetPreview(self) -> None:
            return

        def hideWorkingSetPreview(self) -> None:
            return

    runtime = SteamVROverlayRuntime(tick_hz=45.0)
    fake = FakeChaperone()
    runtime._chaperone_setup = fake

    applied = runtime.apply_playspace_yaw_offset_from_raw_pivot(
        45.0,
        (25000.0, 0.0, 35000.0),
    )

    assert applied is False
    assert fake.set_calls == 0
