from __future__ import annotations

from dataclasses import dataclass, field

from .config import DwellConfig


@dataclass(frozen=True)
class ButtonVisualState:
    hovered: bool = False
    armed: bool = False
    dwell_progress: float = 0.0
    cooldown_progress: float = 0.0
    committed: bool = False


@dataclass(frozen=True)
class DwellUpdate:
    hover_id: str | None
    committed_id: str | None
    visuals: dict[str, ButtonVisualState]


@dataclass
class _DwellState:
    hover_id: str | None = None
    hover_started_at: float | None = None
    commit_started_at: float | None = None
    committed_id: str | None = None
    retrigger_blocked_id: str | None = None
    cooldown_until: dict[str, float] = field(default_factory=dict)


class DwellTracker:
    def __init__(self, button_ids: list[str], config: DwellConfig) -> None:
        self._button_ids = button_ids
        self._config = config
        self._state = _DwellState()

    def update(self, now: float, hover_id: str | None) -> DwellUpdate:
        state = self._state
        committed_id: str | None = None

        if hover_id != state.hover_id:
            state.hover_id = hover_id
            state.hover_started_at = now if hover_id is not None else None
            state.commit_started_at = None
            state.committed_id = None
            state.retrigger_blocked_id = None

        if state.hover_id is not None and state.hover_started_at is not None:
            if state.hover_id == state.retrigger_blocked_id:
                pass
            elif now >= state.cooldown_until.get(state.hover_id, 0.0):
                armed_elapsed = now - state.hover_started_at
                if armed_elapsed >= self._config.onset_delay_s:
                    commit_elapsed = armed_elapsed - self._config.onset_delay_s
                    if commit_elapsed >= self._config.commit_duration_s and state.committed_id != state.hover_id:
                        committed_id = state.hover_id
                        state.committed_id = state.hover_id
                        state.commit_started_at = now
                        state.retrigger_blocked_id = state.hover_id
                        state.cooldown_until[state.hover_id] = now + self._config.cooldown_s
            else:
                state.hover_started_at = now
                state.commit_started_at = None
                state.committed_id = None

        visuals = self._build_visuals(now)
        if committed_id is not None:
            visuals[committed_id] = ButtonVisualState(
                hovered=True,
                armed=True,
                dwell_progress=1.0,
                cooldown_progress=0.0,
                committed=True,
            )
        return DwellUpdate(
            hover_id=state.hover_id,
            committed_id=committed_id,
            visuals=visuals,
        )

    def _build_visuals(self, now: float) -> dict[str, ButtonVisualState]:
        state = self._state
        visuals: dict[str, ButtonVisualState] = {}
        for button_id in self._button_ids:
            hovered = button_id == state.hover_id
            cooldown_until = state.cooldown_until.get(button_id, 0.0)
            cooldown_progress = 0.0
            if now < cooldown_until:
                remaining = cooldown_until - now
                cooldown_progress = min(1.0, remaining / self._config.cooldown_s)

            armed = False
            dwell_progress = 0.0
            committed = False
            if (
                hovered
                and state.hover_started_at is not None
                and cooldown_progress == 0.0
                and button_id != state.retrigger_blocked_id
            ):
                elapsed = now - state.hover_started_at
                if elapsed >= self._config.onset_delay_s:
                    armed = True
                    dwell_elapsed = elapsed - self._config.onset_delay_s
                    dwell_progress = min(1.0, dwell_elapsed / self._config.commit_duration_s)

            visuals[button_id] = ButtonVisualState(
                hovered=hovered,
                armed=armed,
                dwell_progress=dwell_progress,
                cooldown_progress=cooldown_progress,
                committed=committed,
            )
        return visuals
