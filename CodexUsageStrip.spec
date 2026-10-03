# PyInstaller single-file GUI recipe. Build paths are supplied by build.py.
from pathlib import Path

source = Path(SPECPATH)
a = Analysis([str(source / 'main.py')], pathex=[str(source)], binaries=[], datas=[],
             hiddenimports=[], hookspath=[], hooksconfig={}, runtime_hooks=[],
             excludes=[], noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name='CodexUsageStrip',
          debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
          console=False, disable_windowed_traceback=False)
