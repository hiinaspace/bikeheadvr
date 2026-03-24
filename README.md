## bikeheadvr

Prototype for a SteamVR/OpenVR overlay that lets you move around in vrchat
without your controller joysticks. instead you look at some gaze targets a bit
to trigger forward/back/left/right.

This is specifically useful for when you want ride a stationary bike while
looking at scenery in VRChat but without having to awkwardly keep the
controllers in your palms while also holding the handlebars.

The forward/back velocity is just static now (inputs full forward/backward on
the joystick). I'll probably add some sort of velocity estimation if you wear
foot trackers while pedalling. If you have a fancier exercise bike than mine
that has bluetooth or whatever, you could probably pipe that in as an
alternative.

It currently works okay, though the gaze targets are jumpy.

Run with:

```powershell
uv run bikeheadvr
```

Turn on [VRChat OSC](https://docs.vrchat.com/docs/osc-overview) if it's not on
already. Then sit on your bike.

Look down under your feet, you should see a circle that says 'toggle'. If you
stare at it a bit, you'll see a "calibrate" countdown. Look forward, and this'll
calibrate your bike forward direction.

Then you'll see forward/left/right/stop gaze buttons. Stare at the forward one a
bit to move forward, until you gaze at the 'stop' button. The forward vector
will compensate for your head movement so you can look sideways while still
moving forward (relative to your bike).

Stare at the left/right buttons to temporarily turn with the joystick. For some
reason this only worked with smooth turning (aka comfort turning off) on my
machine. Maybe it'll work for you though.

There's also a 'backward' button behind you, though it's pretty hard to stare at.
