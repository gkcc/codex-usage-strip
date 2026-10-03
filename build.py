"""Build in an owned OS-temp run and publish only an exe, zip, and checksum."""
from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import uuid
import zipfile

from version import VERSION

SOURCE = Path(__file__).resolve().parent
LAUNCHERS = ("start", "install", "stop", "uninstall", "status")


def inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def validate_paths(work_dir: Path, output_dir: Path) -> tuple[Path, Path]:
    work, output = work_dir.expanduser().resolve(), output_dir.expanduser().resolve()
    temporary = Path(tempfile.gettempdir()).resolve()
    if not inside(work, temporary):
        raise ValueError("--work-dir must be inside the operating system's temporary directory")
    if inside(work, SOURCE) or inside(output, SOURCE):
        raise ValueError("Build/cache and release artifacts must remain outside the checkout")
    if inside(output, work):
        raise ValueError("The release output must be outside the disposable work directory")
    return work, output


def release_files() -> list[tuple[Path, str]]:
    files = [(SOURCE / "README.md", "README.md"), (SOURCE / "LICENSE", "LICENSE")]
    files += [(SOURCE / "docs" / "README.en.md", "docs/README.en.md"),
              (SOURCE / "docs" / "preview.png", "docs/preview.png")]
    files += [(SOURCE / "THIRD_PARTY_NOTICES.md", "THIRD_PARTY_NOTICES.md"),
              (SOURCE / "LICENSES" / "Python.txt", "LICENSES/Python.txt"),
              (SOURCE / "LICENSES" / "PyInstaller.txt", "LICENSES/PyInstaller.txt")]
    files += [(SOURCE / (name + ".cmd"), name + ".cmd") for name in LAUNCHERS]
    files += [(SOURCE / "scripts" / (name + ".ps1"), "scripts/" + name + ".ps1") for name in LAUNCHERS]
    files += [(SOURCE / "scripts" / "common.ps1", "scripts/common.ps1")]
    for file, _ in files:
        if not file.is_file():
            raise ValueError(f"Release input is missing: {file.name}")
    return files


def run_pyinstaller(command, *, cwd, env, check):
    """Contain the owned builder and stop its descendants before scratch cleanup."""
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    for name, result, arguments in (
        ("CreateJobObjectW", wintypes.HANDLE, [ctypes.c_void_p, wintypes.LPCWSTR]),
        ("SetInformationJobObject", wintypes.BOOL, [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]),
        ("AssignProcessToJobObject", wintypes.BOOL, [wintypes.HANDLE, wintypes.HANDLE]),
        ("CloseHandle", wintypes.BOOL, [wintypes.HANDLE]),
    ):
        function = getattr(kernel, name)
        function.restype, function.argtypes = result, arguments
    job = kernel.CreateJobObjectW(None, None)
    if not job:
        raise OSError("Cannot own the release build process")
    process = None
    try:
        size = 144 if ctypes.sizeof(ctypes.c_void_p) == 8 else 112
        limits = ctypes.create_string_buffer(size)
        ctypes.c_uint32.from_buffer(limits, 16).value = 0x2000  # KILL_ON_JOB_CLOSE
        if not kernel.SetInformationJobObject(job, 9, limits, size):
            raise OSError("Cannot contain the release build process")
        process = subprocess.Popen(command, cwd=cwd, env=env, creationflags=subprocess.CREATE_NO_WINDOW)
        if not kernel.AssignProcessToJobObject(job, wintypes.HANDLE(process._handle)):
            raise OSError("Cannot contain the release build process")
        result = process.wait()
        if check and result:
            raise subprocess.CalledProcessError(result, command)
        return subprocess.CompletedProcess(command, result)
    finally:
        # Closing this unnamed job affects only the builder assigned above.
        kernel.CloseHandle(job)
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


def build(work_dir: Path, output_dir: Path, *, runner=run_pyinstaller) -> dict:
    if os.name != "nt" or struct.calcsize("P") != 8:
        raise RuntimeError("The release must be built with 64-bit Python on Windows")
    work, output = validate_paths(work_dir, output_dir)
    inputs = release_files()
    work.mkdir(parents=True, exist_ok=True)
    run = Path(tempfile.mkdtemp(prefix="codex-usage-strip-build-", dir=work)).resolve()
    token = uuid.uuid4().hex
    owner = run / "owner.json"
    try:
        owner.write_text(json.dumps({"owner": "CodexUsageStrip-build", "token": token,
                                     "pid": os.getpid()}), encoding="utf-8")
        env = os.environ.copy()
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["PYINSTALLER_CONFIG_DIR"] = str(run / "pyinstaller-cache")
        command = [sys.executable, "-B", "-m", "PyInstaller", "--noconfirm", "--clean",
                   "--distpath", str(run / "dist"), "--workpath", str(run / "build"),
                   str(SOURCE / "CodexUsageStrip.spec")]
        runner(command, cwd=run, env=env, check=True)
        executable = run / "dist" / "CodexUsageStrip.exe"
        if not executable.is_file():
            raise RuntimeError("PyInstaller did not produce CodexUsageStrip.exe")
        output.mkdir(parents=True, exist_ok=True)
        published = output / "CodexUsageStrip.exe"
        shutil.copy2(executable, published)
        archive = output / f"CodexUsageStrip-{VERSION}-windows-x64.zip"
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as package:
            package.write(executable, "CodexUsageStrip.exe")
            for path, name in inputs:
                package.write(path, name)
        checksums = {}
        for path in (published, archive):
            checksums[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
        (output / "SHA256SUMS.txt").write_text(
            "".join(f"{digest}  {name}\n" for name, digest in checksums.items()), encoding="utf-8")
        return {"version": VERSION, "architecture": "windows-x64", "sha256": checksums}
    finally:
        recorded = json.loads(owner.read_text(encoding="utf-8")) if owner.exists() else {"token": token}
        if recorded.get("token") != token or not inside(run, work) or not inside(run, Path(tempfile.gettempdir())):
            raise RuntimeError(f"Build ownership changed; retained {run}")
        shutil.rmtree(run)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", required=True, type=Path, help="Owned parent directory under OS temp")
    parser.add_argument("--output-dir", required=True, type=Path, help="Requested release artifact destination")
    args = parser.parse_args(argv)
    try:
        result = build(args.work_dir, args.output_dir)
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f"Build failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    print("Owned disposable build files were deleted.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
