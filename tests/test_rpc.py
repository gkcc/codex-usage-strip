import os
import threading
from unittest import mock

from rpc import AccountClient, find_codex
from tests.helpers import IsolatedTestCase


class DiscoveryAndReadOnlyTests(IsolatedTestCase):
    def test_explicit_executable_wins_even_when_installations_exist(self):
        explicit = self.run / "Custom Path" / "codex.exe"
        explicit.parent.mkdir()
        explicit.touch()
        self.assertEqual(find_codex(explicit, environ=self.env), explicit)

    def test_invalid_explicit_executable_is_not_silently_replaced(self):
        for name in ("missing.exe", "codex.ps1"):
            path = self.run / name
            if name.endswith(".ps1"):
                path.touch()
            with self.assertRaisesRegex(RuntimeError, "existing .exe"):
                find_codex(path, environ=self.env)

    def test_desktop_bundle_selects_the_newest_native_client(self):
        root = self.run / "App Data" / "OpenAI" / "Codex" / "bin"
        old, new = root / "old" / "codex.exe", root / "new" / "codex.exe"
        for path, timestamp in ((old, 1_700_000_000), (new, 1_800_000_000)):
            path.parent.mkdir(parents=True)
            path.touch()
            os.utime(path, (timestamp, timestamp))
        self.assertEqual(find_codex(environ=self.env), new)

    def test_path_native_executable_is_a_fallback(self):
        path = self.run / "CLI With Spaces" / "codex.exe"
        path.parent.mkdir()
        path.touch()
        lookup = mock.Mock(return_value=str(path))
        self.env["PATH"] = str(path.parent)
        self.assertEqual(find_codex(environ=self.env, which=lookup), path)
        lookup.assert_called_once_with("codex.exe", path=str(path.parent))

    def test_missing_localappdata_never_searches_the_current_directory(self):
        with self.assertRaisesRegex(RuntimeError, "unavailable"):
            find_codex(environ={"PATH": ""}, which=mock.Mock(return_value=None))

    def test_call_and_write_both_reject_turn_and_login_methods(self):
        client = AccountClient(str(self.run / "Fake Home"), threading.Event())
        for method in ("turn/start", "thread/start", "account/login/start", "config/write"):
            with self.assertRaises(ValueError):
                client.call(method, {})
            with self.assertRaises(ValueError):
                client._write({"method": method})
        self.assertIsNone(client.process)
