"""Native, read-only Codex quota cards for the Windows desktop title bar."""
from __future__ import annotations

import argparse
import ctypes
import json
import os
from pathlib import Path
import sys

from rpc import find_codex
from settings import load_settings, write_json
from version import VERSION


def emit(value: dict | str, destination: str | None = None, *, error: bool = False) -> None:
    text = json.dumps(value, ensure_ascii=False, indent=2) if isinstance(value, dict) else value
    if destination:
        path = Path(destination).expanduser().resolve()
        if isinstance(value, dict):
            write_json(path, value)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text + "\n", encoding="utf-8")
        return
    stream = sys.stderr if error else sys.stdout
    if stream is not None:
        print(text, file=stream)
    elif os.name == "nt":
        ctypes.windll.user32.MessageBoxW(None, text, "Codex Usage Strip", 0x10 if error else 0x40)


def status(settings, controller=None) -> dict:
    running = False
    if os.name == "nt":
        if controller is None:
            from control import Controller
            controller = Controller(settings.scope)
        running = controller.running()
    try:
        codex = str(find_codex(settings.codex_executable))
        available = True
        reason = None
    except (RuntimeError, OSError) as error:
        codex, available, reason = None, False, str(error)
    result = {
        "version": VERSION, "platform_supported": os.name == "nt", "running": running,
        "codex_available": available, "codex_executable": codex, "codex_error": reason,
        "codex_home": str(settings.codex_home), "personal_config": str(settings.config_path),
        "personal_config_exists": settings.config_path.is_file(),
        "read_only": True, "timezone": "Asia/Shanghai", "utc_offset": "+08:00",
    }
    if running:
        try:
            record = json.loads(settings.state_path.read_text(encoding="utf-8"))
            if isinstance(record, dict) and record.get("instance_scope") == settings.scope:
                # Status never exposes the server's raw account response or IDs.
                result["ui_status"] = record.get("status")
                result["attached_windows"] = len(record.get("windows", []))
                result["native_children"] = all(row.get("is_native_child") for row in record.get("windows", []))
        except (OSError, ValueError, TypeError):
            pass
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", help="Optional personal JSON configuration; default is in LOCALAPPDATA")
    parser.add_argument("--output", help="Write a command result to this file (useful for the GUI executable)")
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--version", action="store_true", help="Show the release version")
    action.add_argument("--status", action="store_true", help="Report status without launching Codex or reading quota")
    action.add_argument("--stop", action="store_true", help="Stop and wait for this installation's usage strip")
    action.add_argument("--install", action="store_true", help="Enable this installation at the current user's login")
    action.add_argument("--uninstall", action="store_true", help="Stop this installation and remove only its login entry")
    args = parser.parse_args(argv)
    try:
        if args.version:
            emit(VERSION, args.output)
            return 0
        if os.name != "nt" and not args.status:
            raise RuntimeError("Codex Usage Strip requires Windows 10 or later")
        # Stopping/removing a login entry must still work after a bad config edit.
        settings = load_settings(args.config, management=args.stop or args.uninstall)
        if args.status:
            emit(status(settings), args.output)
            return 0
        from control import Controller
        controller = Controller(settings.scope)
        if args.stop:
            result = controller.stop()
            emit(result, args.output)
            return 2 if result["running"] else 0
        if args.install:
            from installer import install
            emit(install(settings, custom_config=args.config is not None), args.output)
            return 0
        if args.uninstall:
            from installer import uninstall
            stopped = controller.stop()
            result = uninstall(settings, custom_config=args.config is not None, stopped=not stopped["running"])
            result.update(stopped)
            emit(result, args.output)
            return 2 if stopped["running"] else 0
        if args.output:
            raise ValueError("--output requires --version, --status, --stop, --install, or --uninstall")
        # Check executable availability before creating a GUI or background job.
        find_codex(settings.codex_executable)
        with controller.claim() as stop_event:
            if stop_event:
                from native import run
                run(settings.native_config(), stop_event)
        return 0
    except (OSError, RuntimeError, ValueError) as error:
        emit({"error": str(error), "version": VERSION}, args.output, error=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
