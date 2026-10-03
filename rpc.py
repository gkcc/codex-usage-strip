"""A private, read-only app-server client. Never starts a model turn."""
from __future__ import annotations

import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import threading
import time
from typing import Mapping

from version import VERSION


def find_codex(preferred: str | Path | None = None, *, environ: Mapping[str, str] | None = None,
               which=None) -> Path:
    """Prefer an explicit native CLI, then the desktop bundle, then PATH."""
    env = os.environ if environ is None else environ
    if preferred is not None:
        selected = Path(preferred).expanduser().resolve()
        if not selected.is_file() or selected.suffix.casefold() != ".exe":
            raise RuntimeError("Configured Codex executable must be an existing .exe file")
        return selected
    local = env.get("LOCALAPPDATA")
    candidates = []
    if local:
        root = Path(local) / "OpenAI" / "Codex" / "bin"
        candidates = [p for p in root.glob("*/codex.exe") if p.is_file()]
        direct = root / "codex.exe"
        if direct.is_file():
            candidates.append(direct)
    if candidates:
        return max(candidates, key=lambda p: p.stat().st_mtime).resolve()
    resolve = which or shutil.which
    candidate = resolve("codex.exe", path=env.get("PATH", ""))
    if candidate and Path(candidate).is_file():
        return Path(candidate).resolve()
    raise RuntimeError("Codex CLI unavailable; install Codex or set codexExecutable in personal config.json")


class AccountClient:
    def __init__(self, codex_home: str, stop: threading.Event, executable: str | None = None):
        self.codex_home = codex_home
        self.stop = stop
        self.executable = executable
        self.process: subprocess.Popen | None = None
        self.messages: queue.Queue = queue.Queue(maxsize=32)
        self.sequence = 0
        self.job = None
        self.reader_thread = None

    def open(self) -> None:
        if self.process is not None and self.process.poll() is None:
            return
        self.close()
        env = os.environ.copy()
        env["CODEX_HOME"] = self.codex_home
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["RUST_LOG"] = "off"
        self.messages = queue.Queue(maxsize=32)
        process = subprocess.Popen(
            [str(find_codex(self.executable)), "app-server", "--stdio"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, encoding="utf-8", env=env,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        self.process = process
        self._own_process(process)
        messages = self.messages

        def reader():
            for line in process.stdout:
                try:
                    message = json.loads(line)
                except (ValueError, TypeError):
                    continue
                # Notifications contain no responses needed by this client.
                if isinstance(message, dict) and "id" in message:
                    try:
                        messages.put_nowait(message)
                    except queue.Full:
                        pass
            try:
                messages.put_nowait(None)
            except queue.Full:
                pass

        self.reader_thread = threading.Thread(target=reader, daemon=True)
        self.reader_thread.start()
        self.call("initialize", {
            "clientInfo": {"name": "codex_usage_strip", "title": "Codex Usage Strip", "version": VERSION},
            "capabilities": {"experimentalApi": True},
        })
        self._write({"method": "initialized"})

    def _own_process(self, process):
        """A Windows job closes only our reader, including on forced UI exit."""
        import ctypes
        from ctypes import wintypes as w
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        k.CreateJobObjectW.argtypes = [ctypes.c_void_p, w.LPCWSTR]
        k.CreateJobObjectW.restype = w.HANDLE
        k.SetInformationJobObject.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD]
        k.AssignProcessToJobObject.argtypes = [w.HANDLE, w.HANDLE]
        k.CloseHandle.argtypes = [w.HANDLE]
        # JOBOBJECT_EXTENDED_LIMIT_INFORMATION is 144 bytes on Win64;
        # BasicLimitInformation.LimitFlags is at offset 16 on Win32/Win64.
        size = 144 if ctypes.sizeof(ctypes.c_void_p) == 8 else 112
        info = ctypes.create_string_buffer(size)
        ctypes.c_uint32.from_buffer(info, 16).value = 0x2000
        job = k.CreateJobObjectW(None, None)
        if not job:
            process.terminate()
            raise OSError("Cannot own usage reader process")
        if not k.SetInformationJobObject(job, 9, info, size) or not k.AssignProcessToJobObject(job, w.HANDLE(process._handle)):
            k.CloseHandle(job)
            process.terminate()
            raise OSError("Cannot contain usage reader process")
        self.job = job

    def _write(self, message: dict) -> None:
        if message.get("method") not in ("initialize", "initialized", "account/rateLimits/read"):
            raise ValueError("Only initialization and reading rate limits are permitted")
        if self.process is None or self.process.poll() is not None:
            raise RuntimeError("Usage reader unavailable")
        self.process.stdin.write(json.dumps(message) + "\n")
        self.process.stdin.flush()

    def call(self, method: str, params: dict) -> dict:
        if method not in ("initialize", "account/rateLimits/read"):
            raise ValueError("Only initialization and reading rate limits are permitted")
        self.sequence += 1
        sequence = self.sequence
        self._write({"id": sequence, "method": method, "params": params})
        deadline = time.monotonic() + 25
        while not self.stop.is_set() and time.monotonic() < deadline:
            try:
                response = self.messages.get(timeout=0.2)
            except queue.Empty:
                continue
            if response is None:
                raise RuntimeError("Usage reader closed")
            if response.get("id") != sequence:
                continue
            if "error" in response:
                raise RuntimeError("Rate limit request failed")
            result = response.get("result")
            if not isinstance(result, dict):
                raise RuntimeError("Invalid rate limit response")
            return result
        raise TimeoutError("Rate limit request timed out")

    def read(self) -> dict:
        self.open()
        return self.call("account/rateLimits/read", {})

    def abort(self):
        process = self.process
        if process is not None and process.poll() is None:
            try:
                process.terminate()
            except OSError:
                pass

    def close(self):
        process, self.process = self.process, None
        if process is not None:
            try:
                if process.stdin:
                    process.stdin.close()
                process.wait(timeout=2)
            except (subprocess.TimeoutExpired, OSError):
                try:
                    process.terminate()
                    process.wait(timeout=2)
                except (subprocess.TimeoutExpired, OSError):
                    process.kill()
                    process.wait(timeout=2)
            finally:
                # Stop owned descendants before joining a reader whose stdout
                # pipe might still be held by one of them.
                self._close_job()
                if self.reader_thread:
                    self.reader_thread.join(timeout=1)
                if process.stdout:
                    process.stdout.close()
        self.reader_thread = None
        self._close_job()

    def _close_job(self):
        if self.job:
            import ctypes
            from ctypes import wintypes as w
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.CloseHandle.argtypes = [w.HANDLE]
            kernel.CloseHandle(self.job)
            self.job = None
