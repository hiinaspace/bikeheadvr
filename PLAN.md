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

1. Prototype raw-tracking-frame pose reads in `vr_runtime` without changing
   overlay placement.
2. Route skating physics through raw poses while preserving standing-frame
   overlays and VRChat/HMD joystick compensation.
3. Add recording metadata for pose universe and frame transforms before
   committing real recording fixtures.
4. Use the ghost debug overlays to compare COM, force, torque, and body yaw
   during live testing.
5. Re-test chaperone yaw as a presentation transform only.

## Regression Tests

The estimator test suite now includes synthetic checks for:

- aligned straight coasting
- idealized push-off
- yawed skates plus shifted COM producing lateral force and torque
- rigid world yaw/translation invariance
- hitched tracker frames not creating larger impulses than regular frames

The next test gap is raw-frame plumbing: raw-vs-standing equivalence, explicit
pose-universe serialization, and chaperone-yaw feedback isolation.

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

For pure motion-capture samples, add `--skating-record-only`. This keeps
calibration, estimation, debug overlays, and JSONL recording active, but sends
no VRChat joystick motion and suppresses chaperone yaw:

```powershell
uv run bikeheadvr-cli --locomotion-mode skating --skating-record-only --skating-record-path recordings/skate-single-push-left
```

Candidate committed fixtures should be short, segmented, include pose-universe
metadata, and ideally capture one clean single push or one clean alternating
push sequence. Older recordings are still useful for local replay, but many lack
the newer segment/debug fields.
