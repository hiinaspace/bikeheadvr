# bikeheadvr

SteamVR/OpenVR overlay for controllerless VRChat locomotion. In manual
mode, you stare at gaze targets to trigger movement. In tracker mode, you can
pedal or walk in place with foot trackers to move forward.

This is specifically useful for when you want ride a stationary bike while
looking at scenery in VRChat but without having to awkwardly keep the
controllers in your palms while also holding the handlebars.

Essentially, it holds the joystick forwards for you.

![demo video](/docs/demo.webp)

## Install

From the [Github releases](https://github.com/hiinaspace/bikeheadvr/releases), download the latest `bikeheadvr.exe`. It's a portable file so put it anywhere.

Or if you like the command line and have `uv` installed:

```shell
uvx git+https://github.com/hiinaspace/bikeheadvr --help
```

## Use

1. Run SteamVR and VRChat.
2. Turn on [VRChat OSC](https://docs.vrchat.com/docs/osc-overview) if it's not on already. You might also have to turn off "comfort turn" (sorry).
3. Run `bikeheadvr.exe`, which opens the main GUI:

   ![screenshot of main GUI](/docs/screenshot.png)

4. If you have full body tracking (FBT), you may want to select "Tracker" mode.
5. Press "Start".
6. Sit on your stationary bike.
7. Look down under your feet, you should see a circle that says 'toggle'. If you stare at it a bit, you'll see a "calibrate" countdown. Look forward, and this'll calibrate your forward direction.
8. You'll see forward/stop gaze buttons. Stare at the forward one a bit to move forward, until you gaze at the 'stop' button. If you're using tracker mode, there aren't any buttons, but moving your feet (presumably on pedals) will move you forward. This will also compensate for your head movement, so you can look sideways while still moving forward.
9. To turn, move your head left or right by about ~20cm. 
10. At any time, look straight down at the 'toggle' circle to stop all movement and hide the targets.
11. Exit the program by right-clicking on the icon in your system tray.

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
