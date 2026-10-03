import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import unittest

from tests.helpers import IsolatedTestCase

SOURCE = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.name == "nt" and shutil.which("powershell.exe"), "Windows PowerShell")
class LauncherTests(IsolatedTestCase):
    def powershell(self, content):
        script = self.run / "Script With Spaces.ps1"
        script.write_text(content, encoding="utf-8-sig")
        result = subprocess.run([shutil.which("powershell.exe"), "-NoLogo", "-NoProfile",
                                 "-ExecutionPolicy", "Bypass", "-File", str(script)],
                                text=True, encoding="utf-8", capture_output=True, timeout=30,
                                creationflags=subprocess.CREATE_NO_WINDOW)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def test_all_shipped_powershell_scripts_parse(self):
        text = self.powershell(r"""
$ErrorActionPreference = 'Stop'
$files = Get-ChildItem -LiteralPath '%s' -Filter '*.ps1' -Recurse
foreach ($file in $files) {
    $tokens = $null; $parseErrors = $null
    [void][System.Management.Automation.Language.Parser]::ParseFile($file.FullName, [ref]$tokens, [ref]$parseErrors)
    if ($parseErrors.Count) { throw ($parseErrors | Out-String) }
}
Write-Output 'parsed'
""" % str(SOURCE).replace("'", "''"))
        self.assertEqual(text, "parsed")

    def test_source_python_and_packaged_exe_detection_do_not_change_the_system(self):
        root = self.run / "Portable Source With Spaces"
        root.mkdir()
        (root / "main.py").touch()
        text = self.powershell(r"""
$ErrorActionPreference = 'Stop'
. '%s'
$source = Get-StripLaunch -Root '%s' -Console -PythonExe '%s'
[IO.File]::WriteAllText((Join-Path '%s' 'CodexUsageStrip.exe'), 'fixture')
$packaged = Get-StripLaunch -Root '%s' -Console
@{ source = $source; packaged = $packaged } | ConvertTo-Json -Depth 4 -Compress
""" % tuple(str(path).replace("'", "''") for path in (
            SOURCE / "scripts" / "common.ps1", root, Path(sys.executable), root, root)))
        result = json.loads(text)
        self.assertEqual(result["source"]["Executable"].casefold(), str(Path(sys.executable).resolve()).casefold())
        self.assertEqual(result["source"]["Arguments"], ["-B", str(root / "main.py")])
        self.assertEqual(result["packaged"]["Executable"], str(root / "CodexUsageStrip.exe"))

    def test_windows_argument_quoting_round_trips_spaces_quotes_and_backslashes(self):
        receiver = self.run / "Argument Receiver.py"
        output = self.run / "Arguments.json"
        receiver.write_text("import json,sys\nfrom pathlib import Path\nPath(sys.argv[1]).write_text(json.dumps(sys.argv[2:]),encoding='utf-8')\n", encoding="utf-8")
        values = ["a folder with spaces", 'embedded "quotes"', "trailing\\", "", "日本語"]
        literals = ", ".join("'" + value.replace("'", "''") + "'" for value in values)
        self.powershell(r"""
$ErrorActionPreference = 'Stop'
. '%s'
$arguments = @('-B', '%s', '%s', %s)
$process = Start-Process -FilePath '%s' -ArgumentList (Join-StripArguments $arguments) -WindowStyle Hidden -Wait -PassThru
if ($process.ExitCode -ne 0) { throw 'fixture process failed' }
Write-Output 'done'
""" % (str(SOURCE / "scripts" / "common.ps1").replace("'", "''"),
         str(receiver).replace("'", "''"), str(output).replace("'", "''"), literals,
         str(Path(sys.executable)).replace("'", "''")))
        self.assertEqual(json.loads(output.read_text(encoding="utf-8")), values)
