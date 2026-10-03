import json
from pathlib import Path
from unittest import mock

from settings import instance_scope, load_settings, personal_directory
from tests.helpers import IsolatedTestCase


class PortabilityTests(IsolatedTestCase):
    def test_default_home_and_optional_personal_config_need_no_files(self):
        settings = self.settings()
        self.assertEqual(settings.codex_home, self.run / "Home With Spaces" / ".codex")
        self.assertEqual(settings.config_path, self.run / "App Data" / "CodexUsageStrip" / "config.json")
        self.assertFalse(settings.personal_dir.exists())

    def test_codex_home_environment_is_respected(self):
        self.env["CODEX_HOME"] = str(self.run / "Custom Codex Home")
        self.assertEqual(self.settings().codex_home, self.run / "Custom Codex Home")

    def test_personal_config_overrides_environment(self):
        self.env["CODEX_HOME"] = str(self.run / "Environment Home")
        settings = self.settings()
        settings.personal_dir.mkdir(parents=True)
        settings.config_path.write_text(json.dumps({
            "codexHome": str(self.run / "Configured Home"),
            "codexExecutable": str(self.run / "Codex CLI" / "codex.exe"),
        }), encoding="utf-8")
        selected = self.settings()
        self.assertEqual(selected.codex_home, self.run / "Configured Home")
        self.assertEqual(selected.codex_executable, self.run / "Codex CLI" / "codex.exe")

    def test_explicit_missing_or_malformed_config_is_an_error(self):
        path = self.run / "broken.json"
        with self.assertRaisesRegex(ValueError, "does not exist"):
            self.settings(config_path=path)
        path.write_text("not JSON", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "JSON object"):
            self.settings(config_path=path)

    def test_unknown_and_relative_fields_fail_without_writing_defaults(self):
        path = self.run / "config.json"
        for value in ({"verificationFile": "forbidden.json"}, {"codexHome": "relative"},
                      {"codexHome": ""}, {"codexHome": True}, []):
            path.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaises(ValueError):
                self.settings(config_path=path)
        self.assertFalse((self.run / "App Data").exists())

    def test_management_ignores_a_bad_config_so_stop_and_uninstall_work(self):
        path = self.run / "broken.json"
        path.write_text("not JSON", encoding="utf-8")
        selected = self.settings(config_path=path, management=True)
        self.assertEqual(selected.config_path, path)
        self.assertEqual(selected.codex_home.name, ".codex")

    def test_installations_and_users_have_different_control_scopes(self):
        first = instance_scope(self.run / "Install One", self.run / "User One")
        self.assertEqual(first, instance_scope(self.run / "Install One", self.run / "User One"))
        self.assertNotEqual(first, instance_scope(self.run / "Install Two", self.run / "User One"))
        self.assertNotEqual(first, instance_scope(self.run / "Install One", self.run / "User Two"))

    def test_localappdata_fallback_is_user_local(self):
        self.assertEqual(personal_directory({}, self.run / "Home"),
                         self.run / "Home" / "AppData" / "Local" / "CodexUsageStrip")

    def test_frozen_installation_uses_executable_parent(self):
        from settings import installation_directory
        with mock.patch("sys.frozen", True, create=True), mock.patch("sys.executable", str(self.run / "Release" / "CodexUsageStrip.exe")):
            self.assertEqual(installation_directory(), self.run / "Release")
