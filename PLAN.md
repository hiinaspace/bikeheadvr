# Tactical Plan

This file tracks the active prototype work. Stable design notes live in:

- `docs/bike_design.md`
- `docs/skating_design.md`

## Current Goal

Keep the skating prototype release-ready while preserving enough diagnostics to
continue live tuning from the CLI.

## Active Hypotheses

- Raw OpenVR poses from `TrackingUniverseRawAndUncalibrated` are now the source
  of truth for skating physics and recordings.
- Raw-frame contact Y is probably stable enough to test, but may need a
  standing-up projection if live contact state looks wrong.
- Hip/COM-derived balance load is useful telemetry and a conservative force
  multiplier, but current recordings show it is not enough by itself to classify
  recovery-foot braking.
- The current tuning intentionally preserves forward glide: recovery strokes and
  mostly aligned passive braking are relieved aggressively until we capture
  deliberate braking samples.
- Live tests found and fixed the major frame/yaw issue: new calibrations store a
  tracker-local skate forward axis, and physics stays in raw tracking space.
- Roll-based steering feels usable in live testing, but remains opt-in because
  playspace yaw is more motion-sickness sensitive.
- Foot and ghost diagnostics are useful for development but should be off by
  default in the release UI.

## Near-Term Tasks

1. Live-smoke the desktop app with skating selected, playspace turning off, and
   diagnostics off by default.
2. Package a local executable and verify the settings persist through restart.
3. Keep CLI flags available for record-only runs, diagnostics, and tuning.
4. Record deliberate braking samples if stopping becomes too hard after release
   tuning.
5. Consider a replay-backed fixture from a short clean recording once the data
   format stabilizes.

## Regression Tests

The estimator test suite now includes synthetic checks for:

- aligned straight coasting
- idealized push-off
- yawed skates plus shifted COM producing lateral force and torque
- rigid world yaw/translation invariance
- hitched tracker frames not creating larger impulses than regular frames

Raw-frame plumbing now has tests for OpenVR universe selection, raw-to-standing
yaw conversion, explicit pose-universe serialization, and separated
physics/output axis frames. The next test gap is replay-backed regression from
clean raw recordings.

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
calibration, estimation, and JSONL recording active, but sends no VRChat
joystick motion and suppresses chaperone yaw. Add `--skating-debug-overlays` if
the diagnostic visuals are needed during recording:

```powershell
uv run bikeheadvr-cli --locomotion-mode skating --skating-record-only --skating-record-path recordings/skate-single-push-left
```

Candidate committed fixtures should be short, segmented, include
`pose_universe: raw` plus `raw_to_standing`, and ideally capture one clean
single push or one clean alternating push sequence. Older recordings are still
useful for local replay, but many lack the newer segment/debug fields.
