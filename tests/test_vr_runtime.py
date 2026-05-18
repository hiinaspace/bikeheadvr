from __future__ import annotations

import openvr

from bikeheadvr.vr_runtime import _copy_hmd_matrix34, _extract_hmd_matrix34


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
