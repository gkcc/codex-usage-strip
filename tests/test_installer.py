from unittest import mock

from installer import install, startup_command, startup_name, uninstall
from tests.helpers import IsolatedTestCase


class FakeRegistry:
    def __init__(self, values=None):
        self.values = dict(values or {})
        self.operations = []

    def read(self, name):
        return self.values.get(name)

    def write(self, name, command):
        self.operations.append(("write", name))
        self.values[name] = command

    def delete(self, name):
        self.operations.append(("delete", name))
        self.values.pop(name, None)


class LoginStartupTests(IsolatedTestCase):
    def test_install_is_idempotent_and_preserves_unrelated_entries(self):
        settings = self.settings()
        registry = FakeRegistry({"SomeOtherApp": "an unrelated command"})
        command = '"A Portable Folder\\CodexUsageStrip.exe"'
        self.assertTrue(install(settings, registry, command=command)["startup_registered"])
        install(settings, registry, command=command)
        self.assertEqual(registry.values, {"SomeOtherApp": "an unrelated command", startup_name(settings): command})

    def test_colliding_name_is_not_overwritten(self):
        settings = self.settings()
        registry = FakeRegistry({startup_name(settings): "an unrelated command"})
        with self.assertRaisesRegex(RuntimeError, "preserved"):
            install(settings, registry, command="owned command")
        self.assertEqual(registry.operations, [])
        self.assertFalse(settings.instance_dir.exists())

    def test_update_uses_the_recorded_owned_command(self):
        settings = self.settings()
        registry = FakeRegistry()
        install(settings, registry, command="old owned command")
        install(settings, registry, command="new owned command")
        self.assertEqual(registry.values[startup_name(settings)], "new owned command")

    def test_uninstall_deletes_only_its_own_entry_and_keeps_personal_config(self):
        settings = self.settings()
        registry = FakeRegistry({"AnotherStartup": "leave this alone"})
        install(settings, registry, command="owned command")
        settings.config_path.write_text("{}", encoding="utf-8")
        settings.state_path.write_text("{}", encoding="utf-8")
        result = uninstall(settings, registry, command="owned command")
        self.assertTrue(result["startup_removed"])
        self.assertEqual(registry.values, {"AnotherStartup": "leave this alone"})
        self.assertTrue(settings.config_path.exists())
        self.assertFalse(settings.instance_dir.exists())

    def test_uninstall_refuses_a_replaced_value(self):
        settings = self.settings()
        registry = FakeRegistry()
        install(settings, registry, command="owned command")
        registry.values[startup_name(settings)] = "replacement command"
        with self.assertRaisesRegex(RuntimeError, "preserved"):
            uninstall(settings, registry, command="owned command")
        self.assertEqual(registry.values[startup_name(settings)], "replacement command")

    def test_failed_private_record_write_rolls_back_the_registry_change(self):
        settings = self.settings()
        registry = FakeRegistry({"Other": "untouched"})
        with mock.patch("installer.write_json", side_effect=OSError("fixture failure")):
            with self.assertRaises(OSError):
                install(settings, registry, command="owned command")
        self.assertEqual(registry.values, {"Other": "untouched"})

    def test_commands_quote_source_exe_and_custom_config_paths_with_spaces(self):
        settings = self.settings()
        interpreter = self.run / "Python With Spaces" / "python.exe"
        interpreter.parent.mkdir()
        interpreter.touch()
        interpreter.with_name("pythonw.exe").touch()
        command = startup_command(settings, executable=interpreter, frozen=False, custom_config=True)
        self.assertTrue(command.startswith('"' + str(interpreter.with_name("pythonw.exe")) + '" -B '))
        self.assertIn('"' + str(settings.installation_dir / "main.py") + '"', command)
        self.assertIn('"' + str(settings.config_path) + '"', command)
        portable = self.run / "Packaged With Spaces" / "CodexUsageStrip.exe"
        self.assertEqual(startup_command(settings, executable=portable, frozen=True), '"' + str(portable) + '"')
