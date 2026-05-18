# Bike Locomotion Design

This document captures the stable exercise-bike behavior. `PLAN.md` is reserved
for the current tactical prototype plan.

## Goal

The bike mode lets a seated VRChat user drive locomotion without controllers.
The core interaction is a SteamVR overlay controlled by HMD gaze and dwell,
with movement sent to VRChat through OSC input axes.

The stable workflow is:

1. Dwell on the toggle control.
2. Stand or sit in the bike position and look along the desired bike-forward
   direction during calibration.
3. Use overlay controls or tracker-derived cadence to drive VRChat movement.
4. On shutdown, tracking loss, overlay hide, or recalibration, send zeroed OSC
   inputs so VRChat does not keep moving.

## Modules

`vr_runtime` owns OpenVR initialization, HMD/tracker pose sampling, overlay
handles, overlay transforms, and gaze/overlay intersections.

`overlay_ui` renders CPU-side Pillow textures for the simple overlay controls
and debug quads.

`interaction` runs dwell state machines and calibration countdown state.

`pedal_estimation` estimates cadence from the lowest two generic trackers when
tracker mode is enabled.

`vrchat_osc` owns VRChat OSC output state and emits only changed axes. It always
has a failsafe path that sends zeroes.

## Frames

The bike model is intentionally stationary in the calibrated playspace.
Calibration records:

- a center XZ position from the HMD
- a bike-forward yaw from the HMD look direction

The calibrated bike frame is used for overlay placement and for converting
tracker motion into bike-relative signals.

When drive compensation is active, the intended bike-forward vector is mapped
through the current HMD yaw before sending `/input/Horizontal` and
`/input/Vertical`, so looking sideways does not change the intended bike travel
direction.

## Controls

Bike/manual modes use:

- `/input/Vertical` for forward/back movement
- `/input/Horizontal` when head-yaw compensation requires strafe
- `/input/LookHorizontal` for lean turning

Skating mode deliberately does not use `/input/LookHorizontal` by default.

All axes must return to `0.0` when inactive. This is a hard safety rule because
VRChat input can otherwise stick.

## Tracker Cadence Mode

Tracker mode assumes the two lowest generic trackers are attached to feet.
Calibration records the bike-relative tracker motion and then estimates cadence
from approximately circular pedal motion. The cadence estimator is deliberately
separate from overlay and OSC code so the manual overlay controls remain useful
without trackers.

## UX Constraints

The overlay should avoid repeated large head sweeps. Dwell targets should be
large enough for HMD gaze jitter and use visible progress, onset delay, leave
hysteresis, and cooldown.

The toggle/calibration control is allowed to be lower-frequency and slightly
less convenient than primary movement controls, but it must be reliable.
