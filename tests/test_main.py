import json
import os
from unittest import mock

import main
from tests.helpers import IsolatedTestCase


class CommandTests(IsolatedTestCase):
    def test_version_works_without_windows_or_personal_configuration(self):
        output = self.run / "version.txt"
        with mock.patch("main.load_settings", side_effect=AssertionError("must not load settings")):
            self.assertEqual(main.main(["--version", "--output", str(output)]), 0)
        self.assertEqual(output.read_text(encoding="utf-8"), "1.0.0\n")

    def test_status_does_not_start_a_server_or_read_quota(self):
        output = self.run / "status.json"
        settings = self.settings()
        controller = mock.Mock()
        controller.running.return_value = False
        with mock.patch("main.load_settings", return_value=settings), mock.patch("control.Controller", return_value=controller), \
             mock.patch("main.find_codex", side_effect=RuntimeError("fixture unavailable")), \
             mock.patch("rpc.AccountClient.open", side_effect=AssertionError("must not open a server")):
            self.assertEqual(main.main(["--status", "--output", str(output)]), 0)
        result = json.loads(output.read_text(encoding="utf-8"))
        self.assertFalse(result["running"])
        self.assertFalse(result["codex_available"])
        self.assertEqual(result["utc_offset"], "+08:00")
        self.assertEqual(result["timezone"], "Asia/Shanghai")
        self.assertTrue(result["read_only"])

    def test_stop_uses_management_defaults_without_a_real_registry(self):
        if os.name != "nt":
            self.skipTest("Windows control command")
        output = self.run / "stopped.json"
        broken = self.run / "broken.json"
        broken.write_text("not JSON", encoding="utf-8")
        controller = mock.Mock()
        controller.stop.return_value = {"stop_requested": True, "running": False}
        with mock.patch.dict(os.environ, {"LOCALAPPDATA": self.env["LOCALAPPDATA"]}), \
             mock.patch("control.Controller", return_value=controller), \
             mock.patch("installer.Registry", side_effect=AssertionError("must not access registry")):
            self.assertEqual(main.main(["--stop", "--config", str(broken), "--output", str(output)]), 0)
        self.assertFalse(json.loads(output.read_text(encoding="utf-8"))["running"])

    def test_stop_timeout_has_a_distinct_failure_exit_code(self):
        if os.name != "nt":
            self.skipTest("Windows control command")
        output = self.run / "timeout.json"
        controller = mock.Mock()
        controller.stop.return_value = {"stop_requested": True, "running": True}
        with mock.patch("main.load_settings", return_value=self.settings()), \
             mock.patch("control.Controller", return_value=controller):
            self.assertEqual(main.main(["--stop", "--output", str(output)]), 2)
        self.assertTrue(json.loads(output.read_text(encoding="utf-8"))["running"])
