# Tactical Plan

This file tracks the active prototype work. Stable design notes live in:

- `docs/bike_design.md`
- `docs/skating_design.md`

## Current Goal

Collect clean raw-frame skating recordings and use them with synthetic tests to
debug contact, braking, and turn behavior.

## Active Hypotheses

- Touchdown braking is improved by passive braking slop and landing grace.
- Remaining sideways-feeling failures are mostly frame/turning issues, not pure
  push-gain tuning.
- Chaperone yaw should not be enabled as a default until skating physics reads a
  frame that is independent of chaperone edits.
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

## Near-Term Tasks

1. Record clean single-push and alternating-push samples with raw-frame metadata.
2. Live-test the recovery relief and looser passive braking against alternating
   pushes.
3. Record deliberate braking samples if stopping becomes too hard.
4. Replay the new recordings and compare contact load, force, and touchdown
   braking against expected motion.
5. Decide whether hip tracker COM should replace HMD XZ for force/torque
   leverage beyond normal-load estimation.
6. Use the ghost debug overlays to compare COM, force, torque, and body yaw
   during live testing.
7. Re-test chaperone yaw as a presentation transform only.

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
calibration, estimation, debug overlays, and JSONL recording active, but sends
no VRChat joystick motion and suppresses chaperone yaw:

```powershell
uv run bikeheadvr-cli --locomotion-mode skating --skating-record-only --skating-record-path recordings/skate-single-push-left
```

Candidate committed fixtures should be short, segmented, include
`pose_universe: raw` plus `raw_to_standing`, and ideally capture one clean
single push or one clean alternating push sequence. Older recordings are still
useful for local replay, but many lack the newer segment/debug fields.
