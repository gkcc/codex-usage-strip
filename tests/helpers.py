from contextlib import ExitStack
import json
import os
from pathlib import Path
import tempfile
import unittest
import uuid


class IsolatedTestCase(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        parent = os.environ.get("CODEX_USAGE_STRIP_TEST_ROOT")
        if parent:
            root = Path(parent).resolve()
            root.relative_to(Path(tempfile.gettempdir()).resolve())
            root.mkdir(parents=True, exist_ok=True)
        else:
            root = Path(tempfile.gettempdir())
        self.temporary = self.stack.enter_context(tempfile.TemporaryDirectory(
            prefix="codex-usage-strip-test-", dir=root))
        self.run = Path(self.temporary)
        self.token = uuid.uuid4().hex
        (self.run / "owner.json").write_text(json.dumps({
            "owner": "CodexUsageStrip-tests", "token": self.token, "pid": os.getpid(),
        }), encoding="utf-8")
        self.env = {"LOCALAPPDATA": str(self.run / "App Data"), "PATH": ""}

    def tearDown(self):
        recorded = json.loads((self.run / "owner.json").read_text(encoding="utf-8"))
        self.assertEqual(recorded["token"], self.token)

    def settings(self, **options):
        from settings import load_settings
        return load_settings(environ=self.env, home=self.run / "Home With Spaces",
                             installation=self.run / "Install With Spaces", **options)
