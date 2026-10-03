"""A native child window in Codex's title bar, with a passive quota reader.

No packaged Codex files are changed. No browser port, login flow or model turn
is opened. Closing Codex destroys its child; this helper can attach next launch.
"""
from __future__ import annotations

import ctypes as c
from ctypes import wintypes as w
import json
import os
from pathlib import Path
import re
import threading
import time

from quota import Quota, countdown, stamp
from rpc import AccountClient
from version import VERSION

u = c.WinDLL("user32", use_last_error=True)
k = c.WinDLL("kernel32", use_last_error=True)
g = c.WinDLL("gdi32", use_last_error=True)
LRESULT = c.c_ssize_t
WNDPROC = c.WINFUNCTYPE(LRESULT, w.HWND, w.UINT, w.WPARAM, w.LPARAM)


class WNDCLASS(c.Structure):
    _fields_ = [("style", w.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", c.c_int),
                ("cbWndExtra", c.c_int), ("hInstance", w.HINSTANCE), ("hIcon", w.HICON),
                ("hCursor", w.HANDLE), ("hbrBackground", w.HBRUSH),
                ("lpszMenuName", w.LPCWSTR), ("lpszClassName", w.LPCWSTR)]


class PAINTSTRUCT(c.Structure):
    _fields_ = [("hdc", w.HDC), ("fErase", w.BOOL), ("rcPaint", w.RECT),
                ("fRestore", w.BOOL), ("fIncUpdate", w.BOOL), ("reserved", c.c_byte * 32)]


class TOOLINFO(c.Structure):
    _fields_ = [("cbSize", w.UINT), ("uFlags", w.UINT), ("hwnd", w.HWND),
                ("uId", c.c_size_t), ("rect", w.RECT), ("hinst", w.HINSTANCE),
                ("lpszText", w.LPWSTR), ("lParam", w.LPARAM), ("lpReserved", c.c_void_p)]


def bind(dll, name, result, *args):
    function = getattr(dll, name)
    function.restype, function.argtypes = result, list(args)
    return function


bind(k, "GetModuleHandleW", w.HMODULE, w.LPCWSTR)
bind(k, "CreateMutexW", w.HANDLE, c.c_void_p, w.BOOL, w.LPCWSTR)
bind(k, "CreateEventW", w.HANDLE, c.c_void_p, w.BOOL, w.BOOL, w.LPCWSTR)
bind(k, "OpenEventW", w.HANDLE, w.DWORD, w.BOOL, w.LPCWSTR)
bind(k, "SetEvent", w.BOOL, w.HANDLE)
bind(k, "ResetEvent", w.BOOL, w.HANDLE)
bind(k, "WaitForSingleObject", w.DWORD, w.HANDLE, w.DWORD)
bind(k, "CloseHandle", w.BOOL, w.HANDLE)
bind(k, "OpenProcess", w.HANDLE, w.DWORD, w.BOOL, w.DWORD)
bind(k, "QueryFullProcessImageNameW", w.BOOL, w.HANDLE, w.DWORD, w.LPWSTR, c.POINTER(w.DWORD))
bind(u, "RegisterClassW", w.ATOM, c.POINTER(WNDCLASS))
bind(u, "CreateWindowExW", w.HWND, w.DWORD, w.LPCWSTR, w.LPCWSTR, w.DWORD,
     c.c_int, c.c_int, c.c_int, c.c_int, w.HWND, w.HMENU, w.HINSTANCE, c.c_void_p)
bind(u, "DefWindowProcW", LRESULT, w.HWND, w.UINT, w.WPARAM, w.LPARAM)
bind(u, "DestroyWindow", w.BOOL, w.HWND)
bind(u, "GetClientRect", w.BOOL, w.HWND, c.POINTER(w.RECT))
bind(u, "IsWindow", w.BOOL, w.HWND)
bind(u, "IsWindowVisible", w.BOOL, w.HWND)
bind(u, "IsIconic", w.BOOL, w.HWND)
bind(u, "GetParent", w.HWND, w.HWND)
bind(u, "SetLayeredWindowAttributes", w.BOOL, w.HWND, w.DWORD, w.BYTE, w.DWORD)
bind(u, "SetWindowPos", w.BOOL, w.HWND, w.HWND, c.c_int, c.c_int, c.c_int, c.c_int, w.UINT)
bind(u, "ShowWindow", w.BOOL, w.HWND, c.c_int)
bind(u, "SetWindowTextW", w.BOOL, w.HWND, w.LPCWSTR)
bind(u, "GetWindowTextW", c.c_int, w.HWND, w.LPWSTR, c.c_int)
bind(u, "GetClassNameW", c.c_int, w.HWND, w.LPWSTR, c.c_int)
bind(u, "GetWindowThreadProcessId", w.DWORD, w.HWND, c.POINTER(w.DWORD))
bind(u, "GetDC", w.HDC, w.HWND)
bind(u, "ReleaseDC", c.c_int, w.HWND, w.HDC)
bind(u, "BeginPaint", w.HDC, w.HWND, c.POINTER(PAINTSTRUCT))
bind(u, "EndPaint", w.BOOL, w.HWND, c.POINTER(PAINTSTRUCT))
bind(u, "FillRect", c.c_int, w.HDC, c.POINTER(w.RECT), w.HBRUSH)
bind(u, "DrawTextW", c.c_int, w.HDC, w.LPCWSTR, c.c_int, c.POINTER(w.RECT), w.UINT)
bind(u, "InvalidateRect", w.BOOL, w.HWND, c.c_void_p, w.BOOL)
bind(u, "SendMessageW", LRESULT, w.HWND, w.UINT, w.WPARAM, w.LPARAM)
bind(u, "PostMessageW", w.BOOL, w.HWND, w.UINT, w.WPARAM, w.LPARAM)
bind(u, "SetTimer", c.c_size_t, w.HWND, c.c_size_t, w.UINT, c.c_void_p)
bind(u, "KillTimer", w.BOOL, w.HWND, c.c_size_t)
bind(u, "GetMessageW", w.BOOL, c.POINTER(w.MSG), w.HWND, w.UINT, w.UINT)
bind(u, "TranslateMessage", w.BOOL, c.POINTER(w.MSG))
bind(u, "DispatchMessageW", LRESULT, c.POINTER(w.MSG))
bind(u, "PostQuitMessage", None, c.c_int)
bind(u, "ReleaseCapture", w.BOOL)
bind(u, "LoadCursorW", w.HANDLE, w.HINSTANCE, c.c_void_p)
bind(u, "CreatePopupMenu", w.HMENU)
bind(u, "AppendMenuW", w.BOOL, w.HMENU, w.UINT, c.c_size_t, w.LPCWSTR)
bind(u, "TrackPopupMenu", w.UINT, w.HMENU, w.UINT, c.c_int, c.c_int, c.c_int, w.HWND, c.c_void_p)
bind(u, "DestroyMenu", w.BOOL, w.HMENU)
bind(u, "GetCursorPos", w.BOOL, c.POINTER(w.POINT))
bind(g, "CreateSolidBrush", w.HBRUSH, w.DWORD)
bind(g, "DeleteObject", w.BOOL, w.HANDLE)
bind(g, "CreatePen", w.HANDLE, c.c_int, c.c_int, w.DWORD)
bind(g, "RoundRect", w.BOOL, w.HDC, c.c_int, c.c_int, c.c_int, c.c_int, c.c_int, c.c_int)
bind(g, "SelectObject", w.HANDLE, w.HDC, w.HANDLE)
bind(g, "SetTextColor", w.DWORD, w.HDC, w.DWORD)
bind(g, "SetBkMode", c.c_int, w.HDC, c.c_int)
bind(g, "GetPixel", w.DWORD, w.HDC, c.c_int, c.c_int)
bind(g, "GetTextExtentPoint32W", w.BOOL, w.HDC, w.LPCWSTR, c.c_int, c.POINTER(w.SIZE))
bind(g, "CreateFontW", w.HFONT, c.c_int, c.c_int, c.c_int, c.c_int, c.c_int,
     w.DWORD, w.DWORD, w.DWORD, w.DWORD, w.DWORD, w.DWORD, w.DWORD, w.DWORD, w.LPCWSTR)
ENUMPROC = c.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)
bind(u, "EnumWindows", w.BOOL, ENUMPROC, w.LPARAM)
bind(u, "GetDpiForWindow", w.UINT, w.HWND)


def color(hexadecimal: str) -> int:
    value = hexadecimal.removeprefix("#")
    return int(value[0:2], 16) | (int(value[2:4], 16) << 8) | (int(value[4:6], 16) << 16)


def native_windows(desktop_executable: str | None = None) -> dict[int, int]:
    """Attach only to a verified Codex image, never just a same-named window."""
    found = {}
    preferred = str(Path(desktop_executable).resolve()).casefold() if desktop_executable else None

    @ENUMPROC
    def visit(hwnd, _):
        if not u.IsWindowVisible(hwnd) and not u.IsIconic(hwnd):
            return True
        title, name = c.create_unicode_buffer(200), c.create_unicode_buffer(100)
        u.GetWindowTextW(hwnd, title, len(title))
        u.GetClassNameW(hwnd, name, len(name))
        if title.value not in ("ChatGPT", "Codex") or name.value != "Chrome_WidgetWin_1":
            return True
        pid = w.DWORD()
        u.GetWindowThreadProcessId(hwnd, c.byref(pid))
        process = k.OpenProcess(0x1000, False, pid.value)
        if not process:
            return True
        try:
            path, length = c.create_unicode_buffer(32768), w.DWORD(32768)
            if k.QueryFullProcessImageNameW(process, 0, path, c.byref(length)):
                packaged = re.search(r"\\OpenAI\.Codex_[^\\]+\\app\\ChatGPT\.exe$", path.value, re.I)
                configured = preferred and str(Path(path.value).resolve()).casefold() == preferred
                if packaged or configured:
                    found[int(hwnd)] = pid.value
        finally:
            k.CloseHandle(process)
        return True

    u.EnumWindows(visit, 0)
    return found


class Strip:
    def __init__(self, app: "Application", parent: int, pid: int):
        self.app, self.parent, self.pid = app, parent, pid
        self.font, self.scale, self.text = None, 0, ""
        self.fonts, self.line_height = {}, 1
        self.padding = 10
        self.rich_snapshot, self.rich_failed, self.rich_widths = None, False, ()
        self.bg, self.ink = color("212121"), color("dfdfdf")
        self.rect, self.visible = None, False
        # Chromium's parent uses WS_EX_NOREDIRECTIONBITMAP. A layered child
        # needs its own DWM surface; a normal GDI child is accessible but unseen.
        self.hwnd = u.CreateWindowExW(0x08080000, app.class_name, "Codex 用量：正在读取…",
                                    0x40000000 | 0x10000000 | 0x04000000,
                                    0, 0, 1, 1, parent, None, app.instance, None)
        if not self.hwnd:
            raise c.WinError(c.get_last_error())
        if u.GetParent(self.hwnd) != parent:
            u.DestroyWindow(self.hwnd)
            raise RuntimeError("Native child did not attach to Codex")
        if not u.SetLayeredWindowAttributes(self.hwnd, 0, 255, 2):
            u.DestroyWindow(self.hwnd)
            raise c.WinError(c.get_last_error())
        app.by_handle[int(self.hwnd)] = self
        self.tooltip = u.CreateWindowExW(0x08000008, "tooltips_class32", None,
                                        0x80000003, 0, 0, 0, 0, self.hwnd, None, app.instance, None)
        self.tool_text = c.create_unicode_buffer("正在读取官方额度…")
        self.tool = TOOLINFO(c.sizeof(TOOLINFO), 0x10, self.hwnd, 1, w.RECT(0, 0, 1, 1),
                             None, c.cast(self.tool_text, w.LPWSTR), 0, None)
        if self.tooltip:
            u.SendMessageW(self.tooltip, 1074, 0, c.addressof(self.tool))
            u.SendMessageW(self.tooltip, 1048, 0, 800)

    def measure(self, text: str) -> int:
        dc = u.GetDC(self.hwnd)
        try:
            old = g.SelectObject(dc, self.font)
            size = w.SIZE()
            width = 0
            for line in text.splitlines():
                g.GetTextExtentPoint32W(dc, line, len(line), c.byref(size))
                width = max(width, size.cx)
            self.line_height = size.cy
            g.SelectObject(dc, old)
            return width + round(2 * self.padding * self.scale)
        finally:
            u.ReleaseDC(self.hwnd, dc)

    def get_font(self, pixels: int, weight: int = 400):
        key = (pixels, weight)
        if key not in self.fonts:
            font = g.CreateFontW(-pixels, 0, 0, 0, weight, 0, 0, 0, 1, 0, 0, 5, 0,
                                 "Segoe UI")
            if not font:
                raise c.WinError(c.get_last_error())
            self.fonts[key] = font
        return self.fonts[key]

    def use_font(self, pixels: int):
        self.font = self.get_font(pixels)

    def update(self, now: float):
        if u.IsIconic(self.parent) or not u.IsWindowVisible(self.parent):
            if self.visible:
                u.ShowWindow(self.hwnd, 0)
                self.visible = False
            return
        size = w.RECT()
        if not u.GetClientRect(self.parent, c.byref(size)):
            return
        scale = (u.GetDpiForWindow(self.parent) or 96) / 96
        self.scale = scale
        self.padding = 10
        pixels = round(12 * scale)
        self.use_font(pixels)
        # The real shell's Help menu ends at 275 logical px on this client.
        left, right = round(280 * scale), round(150 * scale)
        available = size.right - left - right
        if available <= 0:
            u.ShowWindow(self.hwnd, 0)
            self.visible = False
            return
        quota, failed = self.app.snapshot, self.app.failed
        if quota:
            strings = [quota.text(now, compact=level, failed=failed) for level in range(4)]
            detail = quota.detail(now, failed)
        else:
            strings = ["Codex 用量正在读取…" if not failed else "Codex 用量暂未获取 · 正在重试"] * 3
            detail = "未获取到用量数据；正在重试。\n不会把未知余额显示成0或100%。"
        budget = min(available, round(1250 * scale))
        text = next((value for value in strings if self.measure(value) <= budget), strings[-1])
        lines = len(text.splitlines())
        if lines > 1:
            self.padding = 2
            # Keep the reset and expiry dates in a 2/3-row title-bar layout.
            # A measured font, rather than dropping fields, fits the real DPI.
            floor = 4
            while pixels > floor and (
                self.measure(text) > budget or self.line_height * lines > round(32 * scale)
            ):
                pixels -= 1
                self.use_font(pixels)
        width = min(budget, self.measure(text))
        height = round(26 * scale) if lines == 1 else self.line_height * lines
        top = round(5 * scale) if lines == 1 else max(0, (round(36 * scale) - height) // 2)
        self.rich_snapshot, self.rich_widths = None, ()
        if quota and quota.windows:
            widths = (140, 165, 220) if len(quota.windows) == 1 else (210, 280, 220)
            total = round((sum(widths) + 12) * scale)
            if total <= available:
                self.rich_snapshot, self.rich_failed = quota, failed
                self.rich_widths = widths
                width, height, top = total, round(34 * scale), round(scale)
                text = strings[0]
        rect = (left + (available - width) // 2, top, width, height)
        u.SetWindowPos(self.hwnd, None, *rect, 0x0010 | 0x0040)
        self.rect, self.visible = rect, True
        dc = u.GetDC(self.parent)
        try:
            sample = g.GetPixel(dc, round(260 * scale), round(4 * scale))
        finally:
            u.ReleaseDC(self.parent, dc)
        if sample != 0xFFFFFFFF:
            channels = [sample & 255, (sample >> 8) & 255, (sample >> 16) & 255]
            if max(channels) - min(channels) < 12:
                self.bg = sample
        dark = ((self.bg & 255) + ((self.bg >> 8) & 255) + ((self.bg >> 16) & 255)) < 384
        self.ink = color("dfdfdf" if dark else "303030")
        if quota and (failed or (quota.bank_expiry is not None and quota.bank_expiry - now < 48 * 3600)
                      or any(win.remaining is not None and win.remaining <= 15 for win in quota.windows)):
            self.ink = color("e5b765" if dark else "80510c")
        changed = text != self.text
        self.text = text
        if changed:
            u.SetWindowTextW(self.hwnd, "Codex 用量 · " + text)
        self.tool_text = c.create_unicode_buffer(detail)
        self.tool.lpszText = c.cast(self.tool_text, w.LPWSTR)
        self.tool.rect = w.RECT(0, 0, width, rect[3])
        if self.tooltip:
            u.SendMessageW(self.tooltip, 1081, 0, c.addressof(self.tool))
            u.SendMessageW(self.tooltip, 1076, 0, c.addressof(self.tool))  # TTM_NEWTOOLRECTW
        u.InvalidateRect(self.hwnd, None, False)

    def paint(self):
        paint = PAINTSTRUCT()
        dc = u.BeginPaint(self.hwnd, c.byref(paint))
        try:
            self.render(dc)
        finally:
            u.EndPaint(self.hwnd, c.byref(paint))

    def render(self, dc):
        # WM_PRINTCLIENT uses this same renderer for a passive background check.
        rect = w.RECT()
        u.GetClientRect(self.hwnd, c.byref(rect))
        brush = g.CreateSolidBrush(self.bg)
        u.FillRect(dc, c.byref(rect), brush)
        g.DeleteObject(brush)
        old = g.SelectObject(dc, self.font) if self.font else None
        try:
            g.SetBkMode(dc, 1)
            if self.rich_snapshot:
                self.paint_cards(dc)
                return
            g.SetTextColor(dc, self.ink)
            rect.left += round(self.padding * self.scale)
            rect.right -= round(self.padding * self.scale)
            if "\n" in self.text:
                u.DrawTextW(dc, self.text, -1, c.byref(rect), 0x0800 | 0x8000)
            else:
                u.DrawTextW(dc, self.text, -1, c.byref(rect), 0x0004 | 0x0020 | 0x0800 | 0x8000)
        finally:
            if old:
                g.SelectObject(dc, old)

    def draw_label(self, dc, text, font, ink, rect):
        old = g.SelectObject(dc, font)
        try:
            g.SetTextColor(dc, ink)
            u.DrawTextW(dc, text, -1, c.byref(rect), 0x0020 | 0x0800 | 0x8000)
        finally:
            g.SelectObject(dc, old)

    def rounded(self, dc, rect, fill, border=None, radius=6):
        brush = g.CreateSolidBrush(fill)
        pen = g.CreatePen(0, max(1, round(self.scale)), border if border is not None else fill)
        old_brush, old_pen = g.SelectObject(dc, brush), g.SelectObject(dc, pen)
        try:
            rounding = max(2, round(radius * self.scale))
            g.RoundRect(dc, rect.left, rect.top, rect.right, rect.bottom, rounding, rounding)
        finally:
            g.SelectObject(dc, old_brush)
            g.SelectObject(dc, old_pen)
            g.DeleteObject(brush)
            g.DeleteObject(pen)

    def paint_cards(self, dc):
        quota, scale, now = self.rich_snapshot, self.scale, time.time()
        dark = ((self.bg & 255) + ((self.bg >> 8) & 255) + ((self.bg >> 16) & 255)) < 384
        fill, border = color("292929" if dark else "f7f7f7"), color("3d3d3d" if dark else "dddddd")
        muted, normal = color("a4a4a4" if dark else "666666"), color("eeeeee" if dark else "242424")
        mint, amber = color("8edab3" if dark else "16784e"), color("efbf7e" if dark else "8a580d")
        stale = self.rich_failed or now - quota.fetched_at > 180
        title_font = self.get_font(round(8 * scale), 400)
        value_font = self.get_font(round(11 * scale), 500)
        percent_font = self.get_font(round(13 * scale), 600)
        names = " / ".join(window.name for window in quota.windows)
        percentages = " / ".join(window.percent for window in quota.windows)
        first_title = ("旧数据 · " if stale else "") + names + "剩余"
        reset_title = "下次重置 · UTC+8" if len(quota.windows) == 1 else "重置 · UTC+8 · " + names
        if len(quota.windows) == 1:
            reset_title += " · " + countdown(quota.windows[0].resets_at, now)
        resets = "  ·  ".join(stamp(window.resets_at) for window in quota.windows)
        bank_title = "重置银行 · " + ("次数未知" if quota.bank_count is None else f"{quota.bank_count} 次")
        if quota.bank_count == 0:
            bank_value = "暂无待到期重置"
        elif quota.bank_expiry is None:
            bank_value = "到期时间未知"
        else:
            bank_title += " · " + countdown(quota.bank_expiry, now)
            known = "最早 " if quota.bank_expiry_exact else "已知最早 "
            bank_value = known + stamp(quota.bank_expiry) + " 到期"
        low = any(window.remaining is not None and window.remaining <= 15 for window in quota.windows)
        unknown = any(window.remaining is None for window in quota.windows)
        first_color = muted if stale or unknown else (amber if low else mint)
        soon = quota.bank_expiry is not None and quota.bank_expiry - now < 48 * 3600
        bank_color = amber if soon else normal
        cards = [(first_title, percentages, percent_font, first_color),
                 (reset_title, resets, value_font, normal),
                 (bank_title, bank_value, value_font, bank_color)]
        x, gap = 0, round(6 * scale)
        for index, ((title, value, font, ink), logical_width) in enumerate(zip(cards, self.rich_widths)):
            width = round(logical_width * scale)
            box = w.RECT(x, 0, x + width, self.rect[3] - 1)
            self.rounded(dc, box, fill, border)
            inset = round(10 * scale)
            self.draw_label(dc, title, title_font, muted,
                            w.RECT(x + inset, round(2 * scale), x + width - inset, round(14 * scale)))
            self.draw_label(dc, value, font, ink,
                            w.RECT(x + inset, round(13 * scale), x + width - inset, self.rect[3] - 2))
            if index == 0 and len(quota.windows) == 1 and quota.windows[0].remaining is not None:
                # A restrained meter gives the percentage an immediate visual cue.
                start = x + round(72 * scale)
                end = x + width - inset
                rail = w.RECT(start, round(24 * scale), end, round(27 * scale))
                self.rounded(dc, rail, border, radius=3)
                amount = round((end - start) * quota.windows[0].remaining / 100)
                if amount > 1:
                    self.rounded(dc, w.RECT(start, rail.top, start + amount, rail.bottom), first_color, radius=3)
            x += width + gap

    def menu(self):
        menu, point = u.CreatePopupMenu(), w.POINT()
        try:
            u.AppendMenuW(menu, 0, 1, "立即刷新用量")
            u.AppendMenuW(menu, 0, 2, "退出用量条")
            u.GetCursorPos(c.byref(point))
            chosen = u.TrackPopupMenu(menu, 0x0100 | 0x0080 | 0x0002,
                                      point.x, point.y, 0, self.hwnd, None)
            if chosen == 1:
                self.app.refresh.set()
            elif chosen == 2:
                self.app.stop.set()
        finally:
            u.DestroyMenu(menu)

    def close(self):
        self.app.by_handle.pop(int(self.hwnd), None)
        if self.tooltip and u.IsWindow(self.tooltip):
            u.DestroyWindow(self.tooltip)
        if u.IsWindow(self.hwnd):
            u.DestroyWindow(self.hwnd)
        for font in self.fonts.values():
            g.DeleteObject(font)
        self.fonts.clear()
        self.font = None


class Application:
    class_name = "CodexUsageStripPublicV1"

    def __init__(self, config: dict, stop_event):
        self.config, self.stop_event = config, stop_event
        self.stop, self.active, self.refresh = threading.Event(), threading.Event(), threading.Event()
        self.snapshot: Quota | None = None
        self.deadline_requested: set[float] = set()
        self.failed = False
        self.windows, self.by_handle = {}, {}
        self.instance = k.GetModuleHandleW(None)
        self.callback = WNDPROC(self.procedure)
        cls = WNDCLASS(8, self.callback, 0, 0, self.instance, None,
                       u.LoadCursorW(None, c.c_void_p(32512)), None, None, self.class_name)
        if not u.RegisterClassW(c.byref(cls)):
            raise c.WinError(c.get_last_error())
        common = c.WinDLL("comctl32")
        common.InitCommonControls()
        self.host = u.CreateWindowExW(0, self.class_name, "Codex Usage Strip Host", 0,
                                      0, 0, 0, 0, w.HWND(-3), None, self.instance, None)
        if not self.host:
            raise c.WinError(c.get_last_error())
        self.client = AccountClient(config["codexHome"], self.stop, config.get("codexExecutable"))
        self.thread = threading.Thread(target=self.reader, daemon=True)
        self.record_cache = None

    def reader(self):
        next_read = 0
        failures = 0
        try:
            while not self.stop.is_set():
                if not self.active.wait(0.25):
                    self.client.close()
                    next_read = 0
                    continue
                if time.monotonic() < next_read and not self.refresh.is_set():
                    self.stop.wait(0.25)
                    continue
                self.refresh.clear()
                try:
                    result = self.client.read()
                    self.snapshot = Quota.parse(result, time.time())
                    self.failed, failures = False, 0
                except Exception:
                    if self.stop.is_set():
                        break
                    self.failed = True
                    failures += 1
                    self.client.close()
                next_read = time.monotonic() + min(300, 60 * max(1, failures))
                u.PostMessageW(self.host, 0x8001, 0, 0)
        finally:
            self.client.close()

    def tick(self):
        if self.stop.is_set() or k.WaitForSingleObject(self.stop_event, 0) == 0:
            self.stop.set()
            u.PostQuitMessage(0)
            return
        found = native_windows(self.config.get("desktopExecutable"))
        for parent in list(self.windows):
            strip = self.windows[parent]
            if parent not in found or found[parent] != strip.pid or not u.IsWindow(strip.hwnd):
                strip.close()
                del self.windows[parent]
        for parent, pid in found.items():
            if parent not in self.windows:
                self.windows[parent] = Strip(self, parent, pid)
        if found:
            self.active.set()
        else:
            self.active.clear()
        now = time.time()
        self.request_deadline_refresh(now)
        for strip in self.windows.values():
            strip.update(now)
        self.record()

    def request_deadline_refresh(self, now: float):
        quota = self.snapshot
        if quota is None:
            return
        deadlines = {value for value in [w.resets_at for w in quota.windows] + [quota.bank_expiry]
                     if value is not None}
        self.deadline_requested.intersection_update(deadlines)
        pending = {value for value in deadlines if quota.fetched_at < value <= now} - self.deadline_requested
        if pending:
            self.deadline_requested.update(pending)
            self.refresh.set()

    def procedure(self, hwnd, message, wp, lp):
        try:
            strip = self.by_handle.get(int(hwnd))
            if message in (0x0113, 0x8001) and hwnd == getattr(self, "host", None):
                self.tick()
                return 0
            if strip:
                if message in (0x0317, 0x0318) and wp:
                    strip.render(wp)
                    return 0
                if message == 0x000F:
                    strip.paint()
                    return 0
                if message == 0x0014:
                    return 1
                if message == 0x0021:
                    return 3  # MA_NOACTIVATE: keep the chat's input focus.
                if message in (0x0201, 0x0203):
                    u.ReleaseCapture()
                    point = w.POINT()
                    u.GetCursorPos(c.byref(point))
                    screen_point = (point.x & 0xffff) | ((point.y & 0xffff) << 16)
                    u.SendMessageW(strip.parent, 0x00A1 if message == 0x0201 else 0x00A3, 2, screen_point)
                    return 0
                if message == 0x0205:
                    strip.menu()
                    return 0
            if message == 0x0016 and wp:
                self.stop.set()
                u.PostQuitMessage(0)
                return 0
        except Exception as error:
            self.record(ui_error=type(error).__name__)
        return u.DefWindowProcW(hwnd, message, wp, lp)

    def record(self, ui_error: str | None = None, stopped: bool = False):
        path = self.config.get("verificationFile")
        if not path:
            return
        data = {
            "version": VERSION, "instance_scope": self.config.get("instanceScope"),
            "pid": os.getpid(), "stopped": stopped,
            "status": "stopped" if stopped else ("refresh_failed" if self.failed else "running"),
            "ui_error": ui_error,
            "windows": [dict(parent_hwnd=s.parent, child_hwnd=int(s.hwnd), parent_pid=s.pid,
                             is_native_child=u.GetParent(s.hwnd) == s.parent, rect=s.rect,
                             visible=s.visible, text=s.text, dpi_scale=s.scale)
                        for s in self.windows.values()],
            "quota": self.snapshot.evidence() if self.snapshot else None,
            "reader_pid": self.client.process.pid if self.client.process else None,
            "read_only": True, "timezone": "Asia/Shanghai", "utc_offset": "+08:00",
        }
        serialized = json.dumps(data, ensure_ascii=False, indent=2)
        if serialized == self.record_cache:
            return
        destination = Path(path)
        pending = destination.with_suffix(".pending")
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            pending.write_text(serialized, encoding="utf-8")
            os.replace(pending, destination)
            self.record_cache = serialized
        finally:
            pending.unlink(missing_ok=True)

    def run(self):
        self.thread.start()
        u.SetTimer(self.host, 1, 1000, None)
        try:
            self.tick()
            msg = w.MSG()
            while True:
                result = u.GetMessageW(c.byref(msg), None, 0, 0)
                if result <= 0:
                    break
                u.TranslateMessage(c.byref(msg))
                u.DispatchMessageW(c.byref(msg))
        finally:
            self.stop.set()
            self.client.abort()
            self.thread.join(timeout=5)
            u.KillTimer(self.host, 1)
            for strip in list(self.windows.values()):
                strip.close()
            self.windows.clear()
            u.DestroyWindow(self.host)
            self.record(stopped=True)


def run(config: dict, stop_event):
    awareness = bind(u, "SetProcessDpiAwarenessContext", w.BOOL, c.c_void_p)
    awareness(c.c_void_p(-4))
    Application(config, stop_event).run()
