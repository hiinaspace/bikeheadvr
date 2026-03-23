## bikeheadvr

Phase 1 prototype for a SteamVR/OpenVR overlay that will eventually drive
VRChat locomotion over OSC while riding an exercise bike.

Current status: creates and shows a single static world-space overlay using
`openvr` and a CPU-rendered RGBA texture.

Run with:

```powershell
uv run bikeheadvr
```

Notes:

- SteamVR must already be running.
- This is currently a normal overlay app, not a dashboard overlay.
- The sandbox here cannot fully verify OpenVR startup because SteamVR writes
  logs under the Steam install, so final runtime validation still needs to
  happen on your machine.
