# bikeheadvr

SteamVR/OpenVR overlay for controllerless VRChat locomotion in a few different modes:

- Manual: look at gaze targets to speed up/slow down/turn.
- Pedal: use foot trackers while pedaling on a stationary bike to move, and lean left/right to turn.
- Skating: foot trackers act like virtual skates. Push off to glide and tilt feet to turn.

Essentially, it holds the joystick forwards for you.

## Why

I first made this so I could ride my stationary bike while looking at scenery in VRChat but without having to awkwardly keep the controllers in my palms while also trying to hold the handlebars.

The skating mode came to me later. While it stretches the name a bit, it shared enough of the
same code that I just bundled it.

## Bike mode demo

![bike mode demo](/docs/bikemode.avif)

## Skating mode demo

![skating mode demo](/docs/skatemode.avif)

## Install

From the [GitHub releases](https://github.com/hiinaspace/bikeheadvr/releases), download the latest `bikeheadvr.exe`. It's a portable file so put it anywhere.

Or if you like the command line and have `uv` installed:

```shell
uvx git+https://github.com/hiinaspace/bikeheadvr --help
```

## Use

1. Run SteamVR and VRChat.
2. Turn on [VRChat OSC](https://docs.vrchat.com/docs/osc-overview) if it's not on already. You might also have to turn off "comfort turn" (sorry).
3. Run `bikeheadvr.exe`, which opens the main GUI:

   ![screenshot of main GUI](/docs/screenshot.png)

4. Choose a top-level tab:
   - "Bike" contains Manual and Tracker bike controls.
   - "Skating" uses foot trackers as virtual skates.
5. Press "Start".

Then depending on your chosen mode:

### Manual mode

1. Sit on your bike (if you're using one; this mode technically doesn't require one).
2. Look down under your feet, you should see a circle that says 'toggle'. If you stare at it a bit, you'll see a "calibrate" countdown.
3. Look in your forward direction during calibration.
4. To start moving, look at the "forward" target; the longer you stare at it the faster you'll move.
5. Look at the stop target to slow down/stop.
6. Look at the turning targets to input smooth turns (you might have to disable "comfort turn" in VRChat's settings to get this to work unfortunately).
7. Look behind you at the "backwards" target if you want to do that for some reason.

### Bike tracker mode

1. Sit on your stationary bike, with your trackers on.
2. Look down under your feet, you should see a circle that says 'toggle'. If you stare at it a bit, you'll see a "calibrate" countdown.
3. Start pedaling to move forward.
4. Stop pedaling to stop.
5. Lean left or right to turn (you might have to disable "comfort turn" in VRChat's settings to get this to work unfortunately).

### Skating mode

1. Turn on and wear your foot (and optionally hip) trackers.
2. Look down under your feet, you should see a circle that says 'toggle'. If you stare at it a bit, you'll see a "calibrate" countdown.
3. Stand with both feet planted and pointing forward during calibration.
4. Push sideways/backward with one foot to glide along the current skate axis.
5. Bring your foot back to parallel to continue gliding. You can alternate pushing feet.
6. Stop by placing one foot perpendicular to your motion.
7. If enabled in the desktop GUI, you can also turn by tilting your feet. **Motion Sickness Warning**: this works by turning the SteamVR playspace around you and can be pretty subtle. Be careful.
8. Also, if enabled, the "diagnostic overlays" option shows the simulated blade/wheel axis on your feet, as well as a body diagram of your skates, your center of mass and the current velocity vector on the ground in front of you.

## Stopping

1. At any time, look straight down at the 'toggle' circle for a bit to stop all movement and hide any UI.
2. Exit the program with the "Quit" button, or by right-clicking on the icon in your system tray.

## Q&A

### Why do you slow down when turning your head to the side?

A lot of VRChat worlds have a slower strafe speed than "run" speed. If you look to the side, the app translates your bike/skate's velocity into a strafe for you, since VRChat's "forward" is fixed to your headset, which unfortunately gets scaled down.

### Can you use this with VR programs other than VRChat?

Not currently, since the [virtual input is specific to VRChat](https://docs.vrchat.com/docs/osc-as-input-controller). In theory, it could though, either as emulated joystick inputs, or by translating the SteamVR playspace for movement.

### It doesn't work very well

I tuned all the constants for me and my specific bike/playspace/tracking setup. I will add more tuning options in the GUI at some point. Until then you can clone the source and edit the config locally.

### How did you get the bike and skates in the demo videos?

The bike is a kind of complex avatar gimmick that I'm still working on. I'll post a download once I figure out how to make it more general purpose.

The skate model is from [Lakuza's Inline Skates Model Pack](https://booth.pm/en/items/3313933).

## Local development

If you want to run the desktop app locally:

```powershell
uv sync --group build
uv run bikeheadvr
```

If you want the old development CLI flow:

```powershell
uv run bikeheadvr-cli --locomotion-mode tracker --verbose
```

Skating CLI examples:

```powershell
uv run bikeheadvr-cli --locomotion-mode skating
uv run bikeheadvr-cli --locomotion-mode skating --skating-playspace-turn
uv run bikeheadvr-cli --locomotion-mode skating --skating-debug-overlays
```

## Packaging

The repository includes:

- a PyInstaller spec at `bikeheadvr.spec`
- a GitHub Actions workflow at `.github/workflows/release.yml`

Manual runs and version tags such as `v0.1.0` build a Windows executable and
upload it as an artifact. Tagged builds also attach `bikeheadvr.exe` to the
GitHub Release.

For local packaging:

```powershell
uv sync --group build
uv run pyinstaller --noconfirm bikeheadvr.spec
```

The built executable will be written to `dist\bikeheadvr.exe`.
