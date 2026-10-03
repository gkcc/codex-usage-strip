"""Only control this public installation through its own named Windows objects."""
from __future__ import annotations

from contextlib import contextmanager
import ctypes
from ctypes import wintypes
import os
import time

from settings import instance_scope

PREFIX = "Local\\CodexUsageStripPublicV1-"


class Kernel:
    def __init__(self):
        if os.name != "nt":
            raise RuntimeError("Codex Usage Strip requires Windows 10 or later")
        self.dll = ctypes.WinDLL("kernel32", use_last_error=True)
        definitions = {
            "CreateMutexW": (wintypes.HANDLE, ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR),
            "OpenMutexW": (wintypes.HANDLE, wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR),
            "CreateEventW": (wintypes.HANDLE, ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR),
            "OpenEventW": (wintypes.HANDLE, wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR),
            "SetEvent": (wintypes.BOOL, wintypes.HANDLE),
            "ResetEvent": (wintypes.BOOL, wintypes.HANDLE),
            "CloseHandle": (wintypes.BOOL, wintypes.HANDLE),
        }
        for name, (result, *args) in definitions.items():
            function = getattr(self.dll, name)
            function.restype, function.argtypes = result, args

    def create_mutex(self, name):
        handle = self.dll.CreateMutexW(None, False, name)
        return handle, ctypes.get_last_error() == 183

    def open_mutex(self, name):
        return self.dll.OpenMutexW(0x00100000, False, name)

    def create_event(self, name):
        return self.dll.CreateEventW(None, True, False, name)

    def open_event(self, name):
        return self.dll.OpenEventW(0x0002, False, name)

    def reset_event(self, handle):
        return self.dll.ResetEvent(handle)

    def set_event(self, handle):
        return self.dll.SetEvent(handle)

    def close(self, handle):
        if handle:
            self.dll.CloseHandle(handle)


class Controller:
    def __init__(self, scope: str | None = None, kernel=None):
        self.scope = scope or instance_scope()
        self.kernel = kernel or Kernel()
        self.mutex_name = PREFIX + self.scope + "-Instance"
        self.event_name = PREFIX + self.scope + "-Stop"

    def running(self) -> bool:
        handle = self.kernel.open_mutex(self.mutex_name)
        try:
            return bool(handle)
        finally:
            self.kernel.close(handle)

    @contextmanager
    def claim(self):
        mutex, existing = self.kernel.create_mutex(self.mutex_name)
        event = None
        try:
            if not mutex:
                raise OSError("Cannot create the usage strip instance mutex")
            if existing:
                yield None
                return
            event = self.kernel.create_event(self.event_name)
            if not event or not self.kernel.reset_event(event):
                raise OSError("Cannot create the usage strip stop event")
            yield event
        finally:
            self.kernel.close(event)
            self.kernel.close(mutex)

    def stop(self, timeout: float = 12) -> dict:
        requested = False
        deadline = time.monotonic() + timeout
        while self.running():
            if not requested:
                event = self.kernel.open_event(self.event_name)
                try:
                    if event:
                        if not self.kernel.set_event(event):
                            raise OSError("Cannot signal the owned usage strip")
                        requested = True
                finally:
                    self.kernel.close(event)
            if time.monotonic() >= deadline:
                return {"stop_requested": requested, "running": self.running()}
            time.sleep(0.05)
        return {"stop_requested": requested, "running": False}
