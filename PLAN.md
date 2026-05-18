# Tactical Plan

This file tracks the active prototype work. Stable design notes live in:

- `docs/bike_design.md`
- `docs/skating_design.md`

## Current Goal

Make skating mode understandable and testable enough that frame changes can be
made safely.

## Active Hypotheses

- Touchdown braking is improved by passive braking slop and landing grace.
- Remaining sideways-feeling failures are mostly frame/turning issues, not pure
  push-gain tuning.
- Chaperone yaw should not be enabled as a default until skating physics reads a
  frame that is independent of chaperone edits.
- Raw OpenVR poses from `TrackingUniverseRawAndUncalibrated` are the likely
  source of truth for skating physics.

## Near-Term Tasks

1. Add deterministic estimator tests for ideal straight skating, push-off, and
   skating into a turn.
2. Use the ghost debug overlays to compare COM, force, torque, and body yaw
   during live testing.
3. Prototype raw-tracking-frame pose reads in `vr_runtime` without changing
   overlay placement.
4. Route skating physics through raw poses while preserving standing-frame
   overlays and VRChat/HMD joystick compensation.
5. Re-test chaperone yaw as a presentation transform only.

## Useful Commands

```powershell
uv run ruff check
uv run pytest
uv run python -m compileall src tests scripts
uv run python scripts\replay_skating_recording.py recordings\<file>.jsonl
```

## Recording Notes

Use `--skating-record-path recordings/<template>` without a `.jsonl` suffix.
The app will append a timestamp. Current recordings are local test artifacts and
are not committed.
