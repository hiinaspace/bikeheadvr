# Project: SteamVR/OpenVR overlay for controllerless VRChat locomotion on an exercise bike

### Summary

Build a SteamVR overlay app that lets the user control VRChat locomotion
through VRChat OSC input, without holding controllers. The primary input method
is head-gaze / dwell on world-space overlay quads. The MVP should support:

* toggle/open controls
* calibrate “bike forward” direction
* sticky forward movement
* stop
* left/right turning
* optional backward movement

Post-MVP, add Vive tracker support on the feet and estimate pedaling cadence
from tracker motion, then map cadence to forward locomotion magnitude.

OpenVR/SteamVR is the right API target for this project. SteamVR overlays are
provided through `IVROverlay`, while OpenXR overlay support is still
extension-based and not ratified in the core spec, so it is not the stable
portable path to bet on for this feature. ([Khronos Registry][1])

### Recommended implementation stack

For the MVP, Python is acceptable.

Recommended stack:

* `pyopenvr` / `openvr` for SteamVR/OpenVR bindings. The Python package is
  still maintained and had a release in August 2025. ([GitHub][2])
* `triad_openvr` as a convenience wrapper for enumerating named tracked devices
  and sampling poses. ([GitHub][3])
* a Python OSC library such as `python-osc` for VRChat OSC output
* simple image generation for overlay textures (Pillow is fine for the MVP)
* one main loop running at a stable tick rate, e.g. 60–90 Hz, with explicit
  state machines for calibration, dwell selection, and latched movement output

Do not use OpenXR for the overlay portion of the project.

### Relevant references / prior work

Use these as architectural references, not as code you must imitate
line-for-line.

#### OpenVR / overlay examples

* `Nyabsi/steamvr_overlay_vulkan`: modern OpenVR overlay template, C++23, SDL3,
  Vulkan, ImGui. Good reference for overlay lifecycle and a cleaner modern
  overlay architecture. ([GitHub][4])
* `hai-vr/h-view`: VRChat-adjacent tool that already combines VRChat
  OSC/OSCQuery and a SteamVR overlay path. Useful reference for VRChat-specific
  integration patterns. ([GitHub][5])
* `MeroFune/GOpy`: small Python SteamVR overlay that reads VRChat OSC and
  displays a gesture overlay. Most relevant minimal Python reference.
  ([GitHub][6])
* `rrazgriz/VRCMicOverlay`: small C# OpenVR overlay for VRChat microphone
  state, with OSCQuery support. Good reference for “small VRChat utility
  overlay” structure. ([GitHub][7])
* `lukis101/VRPoleOverlay`: exercise/fitness-adjacent overlay built on top of
  `VRCMicOverlay`; useful as a sanity check for calibration and
  fitness-world-space UI ideas. ([GitHub][8])

#### Core API docs

* `IVROverlay` overview and overlay management API. ([GitHub][9])
* `CreateOverlay` vs `CreateDashboardOverlay`. This app should be a normal
  non-dashboard overlay. ([GitHub][10])
* `SetOverlayWidthInMeters`, `ShowOverlay`, `SetOverlayTransformAbsolute`,
  `SetOverlayTransformTrackedDeviceRelative`, and `ComputeOverlayIntersection`
  are the key calls to plan around. ([GitHub][11])
* For MVP rendering, `SetOverlayRaw` is acceptable. The docs explicitly say
  `SetOverlayTexture` is preferred when possible, but `SetOverlayRaw` is the
  easy CPU-side path for a simple Python prototype. ([GitHub][12])

#### VRChat OSC docs

Use the VRChat OSC input controller API as the source of truth for addresses
and semantics. Axes are floats in `[-1, 1]` and must reset to `0` when not in
use. Buttons are `1` on press and `0` on release and also need correct reset
behavior. Relevant controls include `/input/Vertical`, `/input/Horizontal`,
`/input/LookHorizontal`, and the comfort turn buttons. ([VRChat][13])

### Product goals

The user is on an exercise bike and should be able to:

* start locomoting forward without touching controllers
* stop reliably
* turn left/right reliably
* optionally move backward
* calibrate the “bike forward” heading while seated on the bike
* keep using the app even without foot trackers
* later, add tracker-derived pedal speed as an input to forward velocity

Primary ergonomic constraint: minimize annoying neck motion and avoid
interactions that require repeated large up/down head sweeps.

### High-level architecture

Implement the app as five mostly separate modules:

1. `vr_runtime`

   * initialize/shutdown OpenVR
   * enumerate HMD and trackers
   * sample poses
   * create/manage overlay handles
   * perform ray/overlay intersection tests

2. `overlay_ui`

   * define button geometry and labels
   * render overlay textures
   * manage visible/hidden state
   * update button visuals for hover, dwell progress, active/latched state, and
     errors

3. `interaction`

   * compute head-forward gaze ray from HMD pose
   * run dwell state machines
   * manage calibration state
   * resolve which button is targeted
   * handle hysteresis and latch/unlatch logic

4. `vrchat_osc`

   * send OSC packets
   * maintain current intended output state
   * always zero outputs on shutdown / exceptions / tracking loss
   * abstract movement and turning commands behind a tiny local API

5. `pedal_estimation` (post-MVP)

   * tracker calibration
   * tracker signal filtering
   * cadence estimation
   * mapping cadence to forward axis magnitude

Keep these modules loosely coupled. The tactical coding agent can choose exact
classes/files.

### Overlay and spatial layout recommendations

Use a standard non-dashboard overlay created with `CreateOverlay`. Place button
quads in world space, probably using absolute transforms after calibration. The
OpenVR overlay API supports absolute and tracked-device-relative transforms;
for this project, absolute placement relative to the calibrated bike-forward
frame is probably the clearest mental model. ([GitHub][10])

Initial recommendation:

* one hidden/toggle control near the lower field of view, but do **not** make
  the user repeatedly look all the way at their feet if this can be avoided
* forward button in front and above the horizon
* stop button below the horizon
* left/right buttons off to the sides
* larger backward button behind the user, only because it is low-frequency

Implementation detail: use `ComputeOverlayIntersection` instead of manually
raycasting against your own quad math unless there is a strong reason not to.
It already gives overlay-space hit coordinates. ([GitHub][14])

For MVP textures, `SetOverlayRaw` is fine. Later, if rendering complexity
increases, switch to a GPU texture path. ([GitHub][12])

### Head-gaze / dwell UX recommendations

Do not blindly copy the “look down at the feet to toggle” idea. Microsoft’s
head-gaze guidance explicitly warns about the “yo-yo effect”: repeated up/down
head movement is uncomfortable. It also recommends that head-gaze targets be at
least around 2 degrees of angular size, which your proposed targets already
exceed. Size is not the problem; repeated neck motion is. ([Microsoft
Learn][15])

Recommended dwell interaction model:

* onset delay: about 150–250 ms
* then visible dwell progress
* default total dwell time around 600 ms

That recommendation is grounded both in Microsoft guidance on onset delay and
in a dwell-time study that found 600 ms was the easiest-to-use dwell time
overall among tested values. ([Microsoft Learn][16])

Non-obvious implementation recommendations:

* use hysteresis, not a single hard hitbox:

  * `enter_radius`
  * `commit_radius`
  * `leave_radius`
* once dwell starts, allow small head jitter without canceling immediately
* give continuous progress feedback, likely a ring or radial fill
* separate “hovered” from “armed” from “committed”
* use a cooldown after commit so one long stare does not retrigger repeatedly
* for sticky forward movement, dwell once to latch on; stop is a separate dwell
  target

For the menu-toggle / recalibration action, consider a different confirmation
method than plain dwell. A 2025 comparison study found nod was the most
preferred technique overall, while gaze dwell and head-and-gaze were broadly
similar; nod is a good fit for a low-frequency action like recalibration, even
if you avoid it for primary movement commands. ([Frontiers][17])

### Movement semantics and VRChat OSC recommendations

Drive locomotion using axis inputs, not button spam.

Recommended mapping:

* forward/back movement: `/input/Vertical`
* optional strafe correction if compensating for head-facing vs bike-facing:
  `/input/Horizontal`
* turning:

  * smooth turn: `/input/LookHorizontal`
  * snap turn: `/input/ComfortLeft` and `/input/ComfortRight`

Critical behavior from the VRChat docs:

* axis inputs must return to `0`
* buttons must send proper `1 -> 0` transitions
* otherwise motion/turn state can stick unintentionally

Implement a watchdog/failsafe that zeroes all active outputs on:

* app shutdown
* unhandled exception
* overlay hidden state
* HMD tracking loss
* calibration invalidation
* prolonged no-pose / no-intersection state

That is not optional. ([VRChat][13])

### Calibration design

Implement a short calibration mode:

1. user triggers calibration
2. show countdown overlay, e.g. `3..2..1.. look forward`
3. average HMD yaw over a small stable window near the end of the countdown
4. store that yaw as `bike_forward_yaw`

This calibrated yaw becomes the reference frame for overlay placement and for
movement correction.

Optional post-MVP behavior:

When forward is latched, compensate for current head yaw relative to
`bike_forward_yaw` so that “bike forward” stays the locomotion direction even
if the user looks sideways. This means rotating the intended locomotion vector
by the negative head-vs-bike yaw delta before sending VRChat axes.

### Suggested MVP phases

#### Phase 1: runtime + one visible test overlay

* initialize OpenVR
* create one overlay
* show a static textured quad
* confirm stable placement and visibility

Exit criteria: overlay appears reliably in SteamVR and follows intended
placement rules. ([GitHub][9])

#### Phase 2: gaze hit testing

* compute HMD forward ray each frame
* intersect against overlay(s)
* highlight hovered target
* show debug text/logging for hit target and UV coordinates

Exit criteria: stable hover highlighting with acceptable jitter. ([GitHub][14])

#### Phase 3: dwell selection

* add onset delay
* add dwell progress visualization
* add hysteresis
* add commit cooldown

Exit criteria: reliable activation without accidental commits. ([Microsoft
Learn][16])

#### Phase 4: VRChat OSC integration

* implement output abstraction
* add forward latch, stop, left/right turn, backward
* add failsafe zeroing

Exit criteria: app can move and turn avatar reliably without controllers.
([VRChat][13])

#### Phase 5: calibration and bike-forward compensation

* implement calibration countdown
* place overlay buttons relative to calibrated yaw
* optionally rotate movement vector to preserve bike-forward motion when head
  turns

Exit criteria: user can sit on the bike, calibrate once, and move in the
intended bike direction.

### Post-MVP: tracker-based pedal speed estimation

Do **not** begin with raw tracker velocity in world space. A more robust
approach is to estimate cyclic motion from the geometry of the tracker path.

A useful prior result is VR cycling work that estimated pedaling cadence from a
single IMU by tracking a periodic hip-angle signal; they reported high
correlation against the reference platform at 30 and 60 rpm, with only moderate
degradation at 90 rpm. That suggests cadence can be recovered robustly from a
relatively simple periodic signal model. ([Springer][18])

Recommended tracker algorithm:

1. during calibration, collect several seconds of foot tracker positions while
pedaling
2. fit a best plane to the 3D points via SVD
3. project samples into that plane
4. fit a 2D circle in the plane
5. compute instantaneous phase angle with `atan2`
6. unwrap phase over time
7. low-pass filter the derivative to get cadence / angular velocity
8. map cadence to `/input/Vertical`

This is essentially turning the tracker path into a noisy rotary encoder. The
SVD + project + circle-fit approach is standard and simple. ([MeshLogic][19])

Additional recommendations:

* support either foot alone, but prefer both feet if available
* use the expected near-π phase offset between feet as a consistency check
* reject obvious outliers / tracking glitches
* include deadband near zero cadence
* smooth aggressively enough that tracking loss does not jerk the avatar

Keep manual forward control even after cadence mode exists. Manual mode is the
fallback when trackers are not set up.

### General implementation recommendations

* Prefer a small, explicit state machine over clever implicit logic.
* Log every state transition.
* Separate “intended movement state” from “currently emitted OSC state”.
* Build a debug mode with visible overlay labels for:

  * current hovered button
  * dwell progress
  * calibrated yaw
  * current head yaw delta
  * current emitted OSC axis values
* Add a “panic stop” path that zeros all outputs immediately.
* Keep the MVP visually ugly if necessary; correctness and reliability matter
  more than appearance.
* Treat tracker support as a separate subsystem, not something entangled with
  the basic dwell UI.

### Success criteria

MVP is successful if:

* the user can mount the bike
* trigger calibration
* start moving forward
* stop
* turn
* optionally move backward
* do all of the above without holding controllers
* recover safely from missed gaze activations or tracking hiccups without
  leaving VRChat movement stuck on

Post-MVP tracker mode is successful if:

* cadence-derived movement feels stable and unsurprising
* temporary tracker glitches do not cause locomotion spikes
* manual mode still works independently

[1]:
https://registry.khronos.org/OpenXR/specs/1.1/html/xrspec.html?utm_source=chatgpt.com
"The OpenXR™ 1.1.57 Specification (with all registered ..." [2]:
https://github.com/cmbruns/pyopenvr/releases?utm_source=chatgpt.com "Releases ·
cmbruns/pyopenvr" [3]:
https://github.com/TriadSemi/triad_openvr?utm_source=chatgpt.com
"TriadSemi/triad_openvr: This is an enhanced wrapper ..." [4]:
https://github.com/Nyabsi/steamvr_overlay_vulkan?utm_source=chatgpt.com
"Nyabsi/steamvr_overlay_vulkan: OpenVR overlay template ..." [5]:
https://github.com/hai-vr/h-view?utm_source=chatgpt.com "H-View" [6]:
https://github.com/MeroFune/GOpy?utm_source=chatgpt.com "MeroFune/GOpy - VRChat
Gesture Overlay in Python" [7]:
https://github.com/rrazgriz/VRCMicOverlay?utm_source=chatgpt.com
"rrazgriz/VRCMicOverlay: Custom VRChat Mic Icon OpenVR ..." [8]:
https://github.com/lukis101/VRPoleOverlay?utm_source=chatgpt.com
"lukis101/VRPoleOverlay: Simple OpenVR overlay to show ..." [9]:
https://github.com/ValveSoftware/openvr/wiki/IVROverlay_Overview?utm_source=chatgpt.com
"IVROverlay_Overview · ValveSoftware/openvr Wiki" [10]:
https://github.com/ValveSoftware/openvr/wiki/IVROverlay%3A%3ACreateOverlay?utm_source=chatgpt.com
"IVROverlay::CreateOverlay · ValveSoftware/openvr Wiki" [11]:
https://github.com/ValveSoftware/openvr/wiki/IVROverlay%3A%3ASetOverlayWidthInMeters/2e4e62f3e8e234b0bc439724505aea33e6b344ac?utm_source=chatgpt.com
"IVROverlay::SetOverlayWidthInMeters · ValveSoftware/openvr Wiki" [12]:
https://github.com/ValveSoftware/openvr/wiki/IVROverlay%3A%3ASetOverlayRaw?utm_source=chatgpt.com
"IVROverlay::SetOverlayRaw · ValveSoftware/openvr Wiki" [13]:
https://docs.vrchat.com/docs/osc-as-input-controller?utm_source=chatgpt.com
"OSC as Input Controller" [14]:
https://github.com/ValveSoftware/openvr/wiki/IVROverlay%3A%3AComputeOverlayIntersection?utm_source=chatgpt.com
"IVROverlay::ComputeOverlayIntersection" [15]:
https://learn.microsoft.com/en-us/windows/mixed-reality/design/gaze-and-dwell-head?utm_source=chatgpt.com
"Head-gaze and dwell - Mixed Reality" [16]:
https://learn.microsoft.com/en-us/windows/mixed-reality/design/gaze-and-dwell-eyes?utm_source=chatgpt.com
"Eye-gaze and dwell - Mixed Reality" [17]:
https://www.frontiersin.org/journals/virtual-reality/articles/10.3389/frvir.2025.1576962/full?utm_source=chatgpt.com
"The interplay of user preference and precision in different ..." [18]:
https://link.springer.com/article/10.1007/s10055-022-00668-w?utm_source=chatgpt.com
"Virtual reality application for real-time pedalling cadence ..." [19]:
https://meshlogic.github.io/posts/jupyter/curve-fitting/fitting-a-circle-to-cluster-of-3d-points/?utm_source=chatgpt.com
"Fitting a Circle to Cluster of 3D Points | MeshLogic"

---

Original notes from me:

steamvr overlay app that lets you control vrchat joystick input over OSC
without using controllers, by using head cursor/gaze, visualized with overlay
quads. Purpose is being able to move around vrchat worlds while on an exercise
bike IRL, where using the controllers is inconvenient vs holding the
handlebars.

head buttons work in the usual 'stare at button at center of headset for enough
time'. main button is ~30cm radious circle on the floor below headset, so you
look down at your feet for half a second or so, which toggles the rest of the
overlay buttons, and also pops up a 'calibrating direction in 3..2..1.., look
forward' message, which at the end of the countdown, records the angle around Y
axis as the forward vector to locate the rest of the overlay buttons. so
assuming you're sitting on the exercise bike then that'll be the direction
you're facing.

The other buttons are overlay quads forward by ~2m and maybe 30cm squares with
basic transparent bounds and text visible. directly forward and ~30deg above
vertical is a "forward" button, which after activation by staring at it sends
the OSC command for vrchat movement joystick at forward vertical axis, held
indefinitely (until you look at stop button). To start it'll just send full Y
forward but once the basics work, might use the relative position of gaze
inside the button at activation time as "speed". e.g. to go slow you look up at
30 deg for a bit and send +0.2 vertical. but if you look way up at 60deg then
it sends the 0.5 vertical. Another extension is since vrchat forward movement
is based on head vector already but we actually want the movement to go forward
in the direction of the bike (which you calibrated in to), take the current
difference between head facing and bike facing and rotate the joystick vector
by that amount to cancel out the head facing behavior. e.g. if you're looking
90deg to the right but you activated the forward input, then the vrchat
movement joystick is actually input as -1 X, i.e. full strafe to the left,
which matches the "bike" movement still.

~60deg off to the left/right are left/right buttons, also 30cm squares or so.
looking at either sends a momentary X axis input on the turning joystick of
vrchat (the right controller) until you look away from the button. so a short
gaze can trigger snap turn generally (not strafing), or with smooth turn can
slowly keep turning left/right.

30deg below vertical is a stop button which cancels the "forward" movement.

and 2m behind the player (relative to bike forward) is a larger ~1m "backward"
button, which works the same as the forward button in inputting the movement
vector that moves the player backward (and since they're facing backward to
start, this usually means actually inputting +Y joystick axis). Idea is that
backward is fairly uncommon but if you need it you can do it without having to
turn around in place. backward movement is like forward in that it sticks on
until you stop.

https://docs.vrchat.com/docs/osc-as-input-controller is osc guide for vrchat
inputs. https://github.com/cmbruns/pyopenvr can probably use this for simple
quad overlays in openvr/steamvr and getting headset pose.
https://github.com/mdovgialo/steam-vr-wheel a related project I know works that
uses pyopenvr and basic quad overlays as example.

After the basic head controls work, a major feature would be to wear vive
trackers on feet and have the app also read the pose of those, estimate how
fast you're pedalling, and adjust the forward joystick movement magnitude based
on that. I think it'd be fairly simple to take some moving window of positions,
or maybe the velocity/acceleration if openvr gives that, estimate the central
axis of the pedals along with the forward direction, apply some smoothing (so
tracking loss and stuff doesn't weirdly jerk the joystick around). But still
useful to have manual 'go forward this fast' control, for when too lazy to set
up trackers and calibrate.
