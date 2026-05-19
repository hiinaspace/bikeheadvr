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
- foot yaw changes the rolling/braking axis
- foot roll can optionally steer the playspace while the skater is moving
- touchdown and small yaw errors are softened because there is no force feedback

## Current Assumptions

- The two lowest generic trackers are the feet.
- Trackers are mounted on top of the feet, so tracker height and tilt are
  approximate contact/load signals rather than exact wheel contact.
- The highest non-foot generic tracker is treated as a hip/COM proxy when
  present; otherwise the HMD XZ position is used.
- VRChat joystick movement is understood well enough to keep as the output
  frame: horizontal/vertical axes are interpreted relative to VRChat/HMD facing.
- VRChat smooth turn is out of scope for skating tests. The intended turn input
  is physical body/skate movement, with optional playspace yaw from foot roll.
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
load, roll steering, force estimation, and JSONL pose recording use raw OpenVR
poses.

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
- the calibrated skate forward axis is also stored in tracker-local coordinates,
  so live 2D skate yaw comes from that calibrated foot axis rather than assuming
  a fixed tracker-local axis. This avoids pitch/roll changing the apparent yaw
  when trackers are mounted yawed relative to the foot.

Current estimator velocity, foot positions, force estimates, and steering state
are represented in this frame.

### Virtual Skater Body Frame

The simulated skater has:

- velocity
- yaw rate from optional roll steering
- integrated `body_yaw`

`body_yaw` is not the same as HMD yaw. It is the simulated body's orientation.
If playspace turning is enabled, this virtual yaw rotates the SteamVR working
standing space as an output transform. Physics remains anchored to raw tracking
poses, and the raw HMD pivot is used when applying the yaw so the working
chaperone transform does not feed back into itself.

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
2. Compute live skate yaw from the calibrated tracker-local skate forward axis.
3. Compute contact load from tracker height and tilt.
4. Scale load with a conservative hip/HMD balance estimate.
5. Compute contact slip from simulated body velocity plus foot velocity.
6. Apply low drag along the skate axis and high drag perpendicular to it.
7. Scale passive braking down when the skate is nearly aligned with current
   simulated velocity.
8. Apply landing and recovery-stroke relief so a returning foot does not erase
   glide too aggressively.
9. Accumulate force.

Roll steering is separate from contact-force torque:

1. Read grounded skate roll relative to calibration.
2. Apply deadzone, load, landing, and speed gates.
3. Integrate the resulting yaw rate into `body_yaw`.
4. If playspace turning is enabled, apply that yaw as a temporary OpenVR
   working standing transform around the raw HMD pivot.

The older COM-to-foot force torque path is still available for diagnostics but
is disabled by default (`torque_gain_per_s = 0.0`). Live testing showed foot
roll is a clearer steering intent signal for the current no-force-feedback
prototype.

## Turning Intent

Yawing the feet changes the wheel axes and therefore changes which directions
glide or brake. It does not directly rotate the playspace.

Rolling grounded skates around their wheel axis is the steering input. Steering
only builds while the skater has simulated speed, which avoids smooth-turn drift
while standing still. The desktop UI exposes this in the Skating tab as "Enable
playspace turning" and leaves it off by default because it has more
motion-sickness risk than straight joystick locomotion.

## Debug Visuals

Skating mode has two opt-in debug layers:

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

The desktop UI exposes both layers in the Skating tab behind "Show diagnostic
overlays", and the CLI exposes `--skating-debug-overlays`.

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
- COM is still an estimate. The hip tracker is preferred when available, but it
  is not a real weighted body center.
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
- Playspace-yaw turning is still opt-in. Physics is insulated from
  standing-frame yaw edits, and the output transform has safety clamps, but this
  can still be more uncomfortable than straight skating.
