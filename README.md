## bikeheadvr

Desktop SteamVR/OpenVR overlay for controllerless VRChat bike locomotion.

You can move around in VRChat without using controller joysticks. In manual
mode, you stare at gaze targets to trigger movement. In tracker mode, you can
pedal or walk in place with foot trackers to move forward.

## Windows desktop app

The primary app entrypoint is now a small Windows desktop UI with:

- `manual` or `tracker` locomotion mode selection
- startup pedal calibration toggle
- verbose logging toggle
- `Start` / `Stop` controls
- a system tray icon so the app can hide and keep running in the background

User settings are persisted under the Windows roaming AppData config directory.

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
