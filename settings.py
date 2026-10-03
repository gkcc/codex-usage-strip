"""Portable defaults; optional personal settings live outside the installation."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Mapping


def installation_directory() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def personal_directory(environ: Mapping[str, str] | None = None, home: Path | None = None) -> Path:
    env = os.environ if environ is None else environ
    local = env.get("LOCALAPPDATA")
    base = Path(local) if local else (home or Path.home()) / "AppData" / "Local"
    return base.expanduser().resolve() / "CodexUsageStrip"


def instance_scope(installation: Path | None = None, personal: Path | None = None) -> str:
    # A separate public namespace and installation identity protect other helpers.
    locations = (installation or installation_directory(), personal or personal_directory())
    identity = "\n".join(str(path.resolve()).casefold() for path in locations)
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]


def _path(value: object, name: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty absolute path")
    # Expand only an initial home marker. Environment expansion must not read
    # another user's environment during isolated tests or configuration loading.
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise ValueError(f"{name} must be an absolute path")
    return path.resolve()


@dataclass(frozen=True)
class Settings:
    codex_home: Path
    codex_executable: Path | None
    desktop_executable: Path | None
    config_path: Path
    personal_dir: Path
    installation_dir: Path

    @property
    def scope(self) -> str:
        return instance_scope(self.installation_dir, self.personal_dir)

    @property
    def instance_dir(self) -> Path:
        return self.personal_dir / "instances" / self.scope

    @property
    def state_path(self) -> Path:
        return self.instance_dir / "state.json"

    def native_config(self) -> dict:
        return {
            "codexHome": str(self.codex_home),
            "codexExecutable": str(self.codex_executable) if self.codex_executable else None,
            "desktopExecutable": str(self.desktop_executable) if self.desktop_executable else None,
            "verificationFile": str(self.state_path),
            "instanceScope": self.scope,
        }


def load_settings(config_path: Path | str | None = None, *,
                  environ: Mapping[str, str] | None = None, home: Path | None = None,
                  installation: Path | None = None, management: bool = False) -> Settings:
    env = os.environ if environ is None else environ
    personal = personal_directory(env, home)
    config = Path(config_path).expanduser().resolve() if config_path else personal / "config.json"
    values = {}
    if not management and config.exists():
        try:
            values = json.loads(config.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError) as error:
            raise ValueError("Cannot read personal config.json as a JSON object") from error
        if not isinstance(values, dict):
            raise ValueError("Personal config.json must contain a JSON object")
        unknown = set(values) - {"codexHome", "codexExecutable", "desktopExecutable"}
        if unknown:
            raise ValueError("Unknown personal configuration field: " + ", ".join(sorted(unknown)))
    elif not management and config_path is not None:
        raise ValueError("The requested personal configuration file does not exist")
    default_home = str((home or Path.home()) / ".codex")
    selected_home = default_home if management else values.get("codexHome", env.get("CODEX_HOME", default_home))
    codex_home = _path(selected_home, "codexHome")
    cli = values.get("codexExecutable", env.get("CODEX_USAGE_STRIP_CODEX"))
    desktop = values.get("desktopExecutable")
    return Settings(codex_home, _path(cli, "codexExecutable") if cli is not None else None,
                    _path(desktop, "desktopExecutable") if desktop is not None else None,
                    config, personal, (installation or installation_directory()).resolve())


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_name(path.name + ".pending")
    try:
        pending.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(pending, path)
    finally:
        pending.unlink(missing_ok=True)
