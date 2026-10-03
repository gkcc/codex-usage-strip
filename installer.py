"""Per-user login startup with an exact, installation-specific registry value."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

from settings import Settings, write_json

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


class Registry:
    """The production adapter. Tests inject a dictionary-backed adapter."""
    def __init__(self):
        import winreg
        self.api = winreg

    def read(self, name: str) -> str | None:
        api = self.api
        try:
            with api.OpenKey(api.HKEY_CURRENT_USER, RUN_KEY, 0, api.KEY_QUERY_VALUE) as key:
                value, kind = api.QueryValueEx(key, name)
        except FileNotFoundError:
            return None
        if kind != api.REG_SZ or not isinstance(value, str):
            raise RuntimeError("The startup name is already occupied by another registry value")
        return value

    def write(self, name: str, command: str) -> None:
        api = self.api
        with api.CreateKeyEx(api.HKEY_CURRENT_USER, RUN_KEY, 0, api.KEY_SET_VALUE) as key:
            api.SetValueEx(key, name, 0, api.REG_SZ, command)

    def delete(self, name: str) -> None:
        api = self.api
        try:
            with api.OpenKey(api.HKEY_CURRENT_USER, RUN_KEY, 0, api.KEY_SET_VALUE) as key:
                api.DeleteValue(key, name)
        except FileNotFoundError:
            pass


def startup_command(settings: Settings, *, executable: Path | None = None,
                    frozen: bool | None = None, custom_config: bool = False) -> str:
    frozen = getattr(sys, "frozen", False) if frozen is None else frozen
    interpreter = executable or Path(sys.executable)
    if frozen:
        arguments = [str(interpreter.resolve())]
    else:
        windowless = interpreter.with_name("pythonw.exe")
        selected = windowless if windowless.is_file() else interpreter
        arguments = [str(selected.resolve()), "-B", str(settings.installation_dir / "main.py")]
    if custom_config:
        arguments += ["--config", str(settings.config_path)]
    return subprocess.list2cmdline(arguments)


def startup_name(settings: Settings) -> str:
    return "CodexUsageStrip-" + settings.scope


def _saved_command(settings: Settings) -> str | None:
    path = settings.instance_dir / "startup.json"
    try:
        saved = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if (isinstance(saved, dict) and saved.get("scope") == settings.scope
            and saved.get("name") == startup_name(settings) and isinstance(saved.get("command"), str)):
        return saved["command"]
    return None


def install(settings: Settings, registry=None, *, command: str | None = None,
            custom_config: bool = False) -> dict:
    registry = registry if registry is not None else Registry()
    name = startup_name(settings)
    command = command or startup_command(settings, custom_config=custom_config)
    previous = registry.read(name)
    if previous is not None and previous not in {command, _saved_command(settings)}:
        raise RuntimeError("This installation's startup name is occupied; the existing entry was preserved")
    registry.write(name, command)
    try:
        write_json(settings.instance_dir / "startup.json", {
            "scope": settings.scope, "name": name, "command": command,
        })
    except OSError:
        if previous is None:
            registry.delete(name)
        else:
            registry.write(name, previous)
        raise
    return {"startup_registered": True, "startup_name": name, "admin_required": False}


def uninstall(settings: Settings, registry=None, *, command: str | None = None,
              custom_config: bool = False, stopped: bool = True) -> dict:
    registry = registry if registry is not None else Registry()
    name = startup_name(settings)
    existing = registry.read(name)
    expected = {command or startup_command(settings, custom_config=custom_config), _saved_command(settings)}
    if existing is not None:
        if existing not in expected:
            raise RuntimeError("The startup entry no longer belongs to this installation; it was preserved")
        registry.delete(name)
    (settings.instance_dir / "startup.json").unlink(missing_ok=True)
    if stopped:
        settings.state_path.unlink(missing_ok=True)
    # Do not recursively remove configuration, files from another installation,
    # or anything added to this directory by the user.
    try:
        settings.instance_dir.rmdir()
    except (FileNotFoundError, OSError):
        pass
    return {"startup_registered": False, "startup_removed": existing is not None,
            "startup_name": name, "personal_config_preserved": True}
