import json
import os
from pathlib import Path
import subprocess
import unittest
from unittest import mock
import zipfile

import build
from tests.helpers import IsolatedTestCase


@unittest.skipUnless(os.name == "nt", "Windows release")
class ExternalBuildTests(IsolatedTestCase):
    def test_release_contains_the_runtime_licenses_and_third_party_notices(self):
        inputs = dict((name, path) for path, name in build.release_files())
        for name in ("THIRD_PARTY_NOTICES.md", "LICENSES/Python.txt", "LICENSES/PyInstaller.txt"):
            self.assertIn(name, inputs)
            self.assertGreater(inputs[name].stat().st_size, 0)

    def inputs(self):
        folder = self.run / "Inputs"
        folder.mkdir()
        for name in ("README.md", "LICENSE"):
            (folder / name).write_text("synthetic packaging input", encoding="utf-8")
        return [(folder / name, name) for name in ("README.md", "LICENSE")]

    def test_build_packages_and_hashes_only_the_requested_outputs_and_cleans_work(self):
        work, output = self.run / "Work", self.run / "Release"
        inputs = self.inputs()

        def runner(command, *, cwd, env, check):
            self.assertTrue(check)
            self.assertIn("-B", command)
            self.assertEqual(env["PYTHONDONTWRITEBYTECODE"], "1")
            self.assertTrue(Path(env["PYINSTALLER_CONFIG_DIR"]).is_relative_to(cwd))
            self.assertEqual(json.loads((cwd / "owner.json").read_text())["owner"], "CodexUsageStrip-build")
            binary = cwd / "dist" / "CodexUsageStrip.exe"
            binary.parent.mkdir()
            binary.write_bytes(b"synthetic executable for packaging test")

        with mock.patch("build.release_files", return_value=inputs):
            result = build.build(work, output, runner=runner)
        self.assertEqual(list(work.iterdir()), [])
        self.assertEqual(set(path.name for path in output.iterdir()), {
            "CodexUsageStrip.exe", "CodexUsageStrip-1.0.0-windows-x64.zip", "SHA256SUMS.txt",
        })
        with zipfile.ZipFile(output / "CodexUsageStrip-1.0.0-windows-x64.zip") as package:
            self.assertEqual(package.namelist(), ["CodexUsageStrip.exe", "README.md", "LICENSE"])
        self.assertEqual(result["version"], "1.0.0")
        self.assertEqual(len(result["sha256"]), 2)

    def test_failed_build_cleans_its_owned_run_and_leaves_no_release(self):
        work, output = self.run / "Work", self.run / "Release"
        with mock.patch("build.release_files", return_value=self.inputs()):
            with self.assertRaises(subprocess.CalledProcessError):
                build.build(work, output, runner=mock.Mock(side_effect=subprocess.CalledProcessError(1, "fixture")))
        self.assertEqual(list(work.iterdir()), [])
        self.assertFalse(output.exists())

    def test_paths_refuse_checkout_builds_and_disposable_release_outputs(self):
        for work, output in ((build.SOURCE, self.run / "Release"),
                             (self.run / "Work", build.SOURCE),
                             (self.run / "Work", self.run / "Work" / "Release")):
            with self.assertRaises(ValueError):
                build.validate_paths(work, output)
