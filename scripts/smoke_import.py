from __future__ import annotations

import importlib


def main() -> int:
    modules = [
        "bikeheadvr.desktop",
        "bikeheadvr.app",
        "openvr",
        "pyglet",
        "PySide6",
    ]
    for module_name in modules:
        importlib.import_module(module_name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
