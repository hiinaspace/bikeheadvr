from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass, field

from .config import CalibrationConfig


@dataclass(frozen=True)
class CalibratedPose:
    x_m: float
    z_m: float
    yaw_deg: float


@dataclass(frozen=True)
class CalibrationStatus:
    active: bool
    completed_pose: CalibratedPose | None = None
    title_text: str | None = None
    subtitle_text: str | None = None


@dataclass
class _CalibrationState:
    active: bool = False
    started_at: float | None = None
    samples_deg: list[float] = field(default_factory=list)
    samples_position_xz: list[tuple[float, float]] = field(default_factory=list)


class CalibrationController:
    def __init__(self, config: CalibrationConfig) -> None:
        self._config = config
        self._state = _CalibrationState()

    def start(self, now: float) -> None:
        self._state = _CalibrationState(active=True, started_at=now)

    def update(
        self,
        now: float,
        yaw_deg: float | None,
        position_xz: tuple[float, float] | None,
    ) -> CalibrationStatus:
        state = self._state
        if not state.active or state.started_at is None:
            return CalibrationStatus(active=False)

        elapsed = now - state.started_at
        remaining = max(0.0, self._config.countdown_s - elapsed)
        if (
            yaw_deg is not None
            and remaining <= self._config.sample_window_s
            and remaining > 0.0
        ):
            state.samples_deg.append(yaw_deg)
        if (
            position_xz is not None
            and remaining <= self._config.sample_window_s
            and remaining > 0.0
        ):
            state.samples_position_xz.append(position_xz)

        if elapsed >= self._config.countdown_s:
            completed = CalibratedPose(
                x_m=_mean(component[0] for component in state.samples_position_xz),
                z_m=_mean(component[1] for component in state.samples_position_xz),
                yaw_deg=_circular_mean_deg(state.samples_deg),
            )
            self._state = _CalibrationState()
            return CalibrationStatus(active=False, completed_pose=completed)

        seconds = max(1, int(math.ceil(remaining)))
        subtitle = f"{seconds}"
        if remaining <= 1.0:
            subtitle = "LOOK FORWARD"
        return CalibrationStatus(
            active=True,
            title_text="CALIBRATE",
            subtitle_text=subtitle,
        )


def _circular_mean_deg(samples_deg: list[float]) -> float:
    if not samples_deg:
        return 0.0
    sin_sum = sum(math.sin(math.radians(sample)) for sample in samples_deg)
    cos_sum = sum(math.cos(math.radians(sample)) for sample in samples_deg)
    return math.degrees(math.atan2(sin_sum, cos_sum))


def _mean(values: Iterable[float]) -> float:
    sequence = list(values)
    if not sequence:
        return 0.0
    return sum(sequence) / len(sequence)
