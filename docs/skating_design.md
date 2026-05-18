# Skating Locomotion Design

This document captures the current skating prototype intent, assumptions, and
frame model. It is expected to change as the prototype is tested.

## Goal

Skating mode uses the user's foot trackers as virtual skates. The user should
turn and push with their real body and feet, while the app sends VRChat joystick
axes that make the avatar move like the simulated skater.

The target feeling is not a full rigid-body simulator. It is a simple,
forgiving locomotion estimator:

- low rolling resistance along each skate's wheel axis
- high resistance perpendicular to the wheel axis
- foot pushes produce acceleration
- sideways skates brake
- foot yaw and COM offset produce torque
- touchdown and small yaw errors are softened because there is no force feedback

## Current Assumptions

- The two lowest generic trackers are the feet.
- Trackers are mounted on top of the feet, so tracker height and tilt are
  approximate contact/load signals rather than exact wheel contact.
- The HMD XZ position is currently the body/COM proxy. Hip tracker support is a
  likely improvement, but not required for the current prototype.
- VRChat joystick movement is understood well enough to keep as the output
  frame: horizontal/vertical axes are interpreted relative to VRChat/HMD facing.
- VRChat smooth turn is out of scope for skating tests. The intended turn input
  is physical body/skate turning.
- OSCQuery/VRChat velocity feedback is useful for diagnostics at most. It is not
  currently part of the control loop because world settings, collisions, slopes,
  and gravity add noise.

## Frames

There are several frames. Keep them separate.

### Raw Tracking Frame

The lighthouse/driver hardware frame. This should eventually be the source of
truth for skating physics because it is not affected by chaperone yaw.

OpenVR exposes this through `TrackingUniverseRawAndUncalibrated`.

Raw tracking is not necessarily a user-friendly playspace frame. In particular,
its vertical axis may not exactly match calibrated standing-space gravity/up.
The skating physics can still use raw horizontal consistency, but contact
height, overlay placement, and user-facing debug should be explicit about which
up vector/frame they use.

Current skating calibration, foot selection, foot velocities, skate yaw, contact
load, force, torque, and JSONL pose recording use raw OpenVR poses.

### Standing/Chaperone Frame

The SteamVR standing playspace frame. The app still reads HMD and tracker poses
in this frame for gaze interaction, overlay placement, and VRChat-facing HMD
axis compensation. Skating physics does not use standing-frame tracker poses as
its source of truth.

Base stations are exposed as `TrackedDeviceClass_TrackingReference`, but in
`TrackingUniverseStanding` their reported poses are still in the current
standing/chaperone frame.

### Calibrated Skate Frame

The room-fixed frame after skating calibration:

- `+forward` is the HMD forward yaw at calibration
- `+right` is perpendicular to that yaw
- foot tracker yaw offsets are recorded so live tracker yaw can become live
  skate-axis yaw

Current estimator velocity, foot positions, forces, and torque are represented
in this frame.

### Virtual Skater Body Frame

The simulated skater has:

- velocity
- yaw rate
- integrated `body_yaw`

`body_yaw` is not the same as HMD yaw. It is the simulated body's orientation.
If chaperone yaw turning is enabled, this virtual yaw is the candidate signal
for rotating the standing space, but the sign and transform must be verified.

### VRChat Input Frame

The final velocity vector is rotated into VRChat joystick axes using current HMD
yaw compensation and sent as:

- `/input/Horizontal`
- `/input/Vertical`

Skating mode does not currently send `/input/LookHorizontal`.

Because skating velocity is simulated in raw-calibrated coordinates, the app
uses SteamVR's raw-zero-to-standing transform to convert the calibrated forward
yaw into the standing/HMD output frame before joystick compensation. If that
transform is unavailable, it falls back to raw HMD yaw and raw calibration yaw so
the estimator does not accidentally mix unrelated yaw frames.

## Physics Sketch

For each contacted foot:

1. Convert foot pose and velocity to calibrated skate frame.
2. Compute live skate yaw from tracker yaw minus calibration yaw offset.
3. Compute contact load from tracker height and tilt.
4. Compute contact slip from simulated body velocity plus yaw-rate contact
   velocity plus foot velocity.
5. Apply low drag along the skate axis and high drag perpendicular to it.
6. Scale passive braking down when the skate is nearly aligned with current
   simulated velocity.
7. Apply a short landing grace period after contact load returns.
8. Accumulate force and torque.

Torque is computed from the COM-to-foot lever arm and the contact force.

## Turning Intent

In the ideal right-turn case:

1. The skater has forward velocity aligned with feet and body.
2. The user yaws both feet to the right and shifts COM right.
3. The wheel axes no longer align with velocity, so lateral slip appears.
4. Anisotropic friction adds a rightward velocity component and a signed torque.
5. The virtual body yaw rotates until the skate axes and velocity stop sliding.
6. If chaperone yaw is enabled, the standing space should rotate as an output
   presentation transform, while physics remains anchored to raw tracking.

The unresolved design question is whether chaperone yaw should be enabled by
default. It may make turning feel more physically coherent, but only after the
physics input frame is insulated from chaperone edits.

## Debug Visuals

Skating mode has two debug layers:

- foot quads at the actual tracker positions, colored by contact state/load
- a ghost debug scene shifted forward from the headset

The ghost scene shows:

- COM marker
- velocity arrow
- virtual body-heading arrow
- COM-to-foot lever lines
- per-foot contact force arrows
- signed torque marker

This is intended to make force and yaw-frame problems visible without looking
straight down at the user's real feet.

## Recording

Skating recordings are JSONL. New recordings are segmented by skating
calibration:

- `meta` record: config and format
- `calibration` record: segment id and calibration model
- `frame` records: poses, selected trackers, devices, estimate, segment id, and
  segment-relative time
- `segment_end` record: emitted when a segment is toggled off

Recordings should remain local and are gitignored.

Current skating recordings use `pose_universe: raw`. Frame records also include
the current `raw_to_standing` 3x4 transform when SteamVR provides it.

## Known Limitations

- Contact height/load currently uses raw-frame tracker Y. If raw Y differs
  noticeably from standing gravity/up on a given SteamVR setup, contact may need
  a separate standing-up or baseline-up projection.
- COM is HMD XZ, not hip/weighted body center.
- Contact load is inferred from tracker height and tilt, not true normal force.
- Per-foot force is also scaled by a conservative balance-load estimate. The app
  uses the highest non-foot generic tracker as a hip/COM proxy when available,
  otherwise HMD XZ. Balance load is based on horizontal COM-to-foot distances and
  is exposed in recordings as `balance_load` plus final `force_load`.
- A recovery-stroke relief heuristic scales down backward force from a foot that
  is moving forward and roughly aligned with the current skate direction. This
  intentionally favors preserving glide over physical braking fidelity until we
  have clean braking recordings.
- Foot trackers do not provide force feedback, so passive braking requires
  generous slop.
- Chaperone-yaw turning is still experimental. Physics is now insulated from
  standing-frame yaw edits, but the output transform and turn feedback loop still
  need live verification.
