"""Exercise the real renderer on an owned offscreen window, without live Codex."""
import ctypes
from ctypes import wintypes
import os
import time
import unittest
from unittest import mock

from quota import Quota
from tests.helpers import IsolatedTestCase


@unittest.skipUnless(os.name == "nt", "Native Windows rendering")
class OffscreenCardTests(IsolatedTestCase):
    def test_real_child_and_rounded_cards_render_on_an_owned_offscreen_window(self):
        import native
        parent = event = app = dc = memory = bitmap = previous = None
        native.bind(native.g, "CreateCompatibleDC", wintypes.HDC, wintypes.HDC)
        native.bind(native.g, "DeleteDC", wintypes.BOOL, wintypes.HDC)
        native.bind(native.g, "CreateCompatibleBitmap", wintypes.HBITMAP, wintypes.HDC, ctypes.c_int, ctypes.c_int)
        try:
            parent = native.u.CreateWindowExW(0x08000000, "STATIC", "Owned offscreen Codex fixture",
                                             0x10CF0000, -32000, -32000, 1600, 900,
                                             None, None, native.k.GetModuleHandleW(None), None)
            self.assertTrue(parent)
            event = native.k.CreateEventW(None, True, False, None)
            config = self.settings().native_config()
            app = native.Application(config, event)
            now = time.time()
            app.snapshot = Quota.parse({"rateLimitsByLimitId": {"codex": {"primary": {
                "usedPercent": 25, "windowDurationMins": 10080, "resetsAt": now + 86400,
            }}}, "rateLimitResetCredits": {"availableCount": 0, "credits": []}}, now)
            with mock.patch("native.native_windows", return_value={int(parent): os.getpid()}):
                app.tick()
            strip = app.windows[int(parent)]
            self.assertEqual(native.u.GetParent(strip.hwnd), parent)
            self.assertTrue(strip.visible)
            self.assertIs(strip.rich_snapshot, app.snapshot)
            self.assertEqual(strip.rich_widths, (140, 165, 220))
            self.assertIn("UTC+8", strip.tool_text.value)
            self.assertIsNone(app.client.process)
            dc = native.u.GetDC(strip.hwnd)
            memory = native.g.CreateCompatibleDC(dc)
            bitmap = native.g.CreateCompatibleBitmap(dc, strip.rect[2], strip.rect[3])
            self.assertTrue(memory and bitmap)
            previous = native.g.SelectObject(memory, bitmap)
            strip.render(memory)
            # The rounded corner exposes the host background; the body fills
            # the middle. This checks the real GDI geometry, not a text mock.
            self.assertEqual(native.g.GetPixel(memory, 0, 0), strip.bg)
            self.assertNotEqual(native.g.GetPixel(memory, round(70 * strip.scale), strip.rect[3] - 4), strip.bg)
        finally:
            if previous and memory:
                native.g.SelectObject(memory, previous)
            if bitmap:
                native.g.DeleteObject(bitmap)
            if memory:
                native.g.DeleteDC(memory)
            if dc and app and app.windows:
                native.u.ReleaseDC(next(iter(app.windows.values())).hwnd, dc)
            if app:
                for strip in list(app.windows.values()):
                    strip.close()
                native.u.DestroyWindow(app.host)
                app.client.close()
            if parent:
                native.u.DestroyWindow(parent)
            if event:
                native.k.CloseHandle(event)
