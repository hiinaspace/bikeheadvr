## bikeheadvr

Prototype for a SteamVR/OpenVR overlay that lets you move around in vrchat
without your controller joysticks. Instead, you can just look at some gaze
targets to trigger forward/back, and tilt your head from side to side to turn.
Or if you have feet trackers, you can pedal/walk to move forward.

This is specifically useful for when you want ride a stationary bike while
looking at scenery in VRChat but without having to awkwardly keep the
controllers in your palms while also holding the handlebars.

## Use

If you don't have `uv` already, [install it following their official instructions](https://docs.astral.sh/uv/#highlights), or if you're not some nerd open up a command line and run (dude trust me):

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Then you can run this actual project with:

```powershell
uvx git+https://github.com/hiinaspace/bikeheadvr 
```

or if you have trackers:

```powershell
uvx git+https://github.com/hiinaspace/bikeheadvr ---location-mode tracker
```

Turn on [VRChat OSC](https://docs.vrchat.com/docs/osc-overview) if it's not on
already. You might also have to turn off "comfort turn" (sorry).

Then sit on your bike (or treadmill).

Look down under your feet, you should see a circle that says 'toggle'. If you
stare at it a bit, you'll see a "calibrate" countdown. Look forward, and this'll
calibrate your forward direction.

Then you'll see forward/stop gaze buttons. Stare at the forward one a
bit to move forward, until you gaze at the 'stop' button. The forward vector
will compensate for your head movement so you can look sideways while still
moving forward (relative to your initial calibration).

If you're using tracker mode, you should start moving as soon as you move your feet.

At any time, look straight down at the 'toggle' circle to disable movement again, or press CTRL+C in the terminal where the program is running..
