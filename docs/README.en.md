# Codex Usage Strip

A small Windows title-bar monitor for Codex quota, reset countdowns, and banked reset expiry.

[中文](../README.md) · [Download](https://github.com/gkcc/codex-usage-strip/releases/latest)

![Native quota cards with demo data](preview.png)

## Quick start

Use Windows 10/11 x64 with Codex desktop installed and signed in.

1. Download the Windows ZIP from Releases and extract it to a permanent folder.
2. Double-click `start.cmd`. The release includes its Python runtime.
3. Double-click `install.cmd` to enable startup at your Windows login. No administrator access is needed.

Hover for precise reset/expiry times and the last update. Right-click to refresh or exit. Data refreshes every minute; all dates use Beijing time (UTC+8). The current UI labels are Chinese.

`stop.cmd` stops this installation. `uninstall.cmd` also removes only its own login entry, preserving personal configuration and downloaded files. Uninstall before moving the folder, then install again at the new location. `status.cmd` shows local diagnostics.

## Optional settings

Codex home defaults to `CODEX_HOME`, then `~/.codex`. The installed Codex CLI is detected automatically. Optional absolute paths `codexHome`, `codexExecutable`, and `desktopExecutable` can be set in `%LOCALAPPDATA%\CodexUsageStrip\config.json`, or passed through `start.cmd -Config "C:\path\personal.json"`.

This community tool creates a native child window without modifying the Codex package. It only initializes and reads `account/rateLimits/read` through the [official app-server](https://learn.chatgpt.com/docs/app-server). It does not start model turns, consume reset credits, or copy credentials.

Missing dates remain unknown; incomplete bank details are labelled as the earliest *known* expiry. Failed reads retain explicitly stale data and retry with backoff. Local usage/configuration records are excluded from source and releases.

The Microsoft Store desktop build is verified. A different desktop executable can be configured explicitly. macOS/Linux are unsupported; future Codex UI/API changes may require an update.

## Development

Windows Python 3.10+; standard-library runtime. Run `python -B main.py` and `python -B -m unittest discover -v`. To build, install PyInstaller and run:

```powershell
python -B build.py --work-dir "$env:TEMP\codex-strip-build" --output-dir "C:\Releases\CodexUsageStrip"
```

The builder removes its owned temporary child directory and publishes an EXE, ZIP and SHA256 checksums outside the checkout.

MIT License. Issues and pull requests are welcome.
