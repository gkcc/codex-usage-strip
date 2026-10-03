# Codex Usage Strip

把 Codex 剩余额度、下次重置和重置银行到期时间放到 Windows 顶栏，省去反复点头像。

[English](docs/README.en.md) · [下载 Windows 版](https://github.com/gkcc/codex-usage-strip/releases/latest)

![顶部用量卡片，演示数据](docs/preview.png)

## 安装与使用

需要 Windows 10/11 64 位，以及已经安装并登录的 Codex 桌面应用。

1. 下载 Release 中的 `CodexUsageStrip-1.0.0-windows-x64.zip`。
2. 解压到准备长期保留的文件夹，双击 `start.cmd`。发布包自带运行环境，无需安装 Python。
3. 想随 Windows 登录启动，双击 `install.cmd`。它只登记当前用户，不需要管理员权限。

运行后，顶栏显示余额进度条、下次重置日期与倒计时、可用银行重置次数及最早到期时间。每分钟刷新；悬停显示精确时间和最后更新时间，右键可立即刷新或退出。时间统一为北京时间（UTC+8）。

`stop.cmd` 退出本次运行，`uninstall.cmd` 停止用量条并删除本安装位置的登录启动项；个人配置和下载文件保留。启用自动启动后请保留文件夹位置；要搬家，先卸载旧位置，再在新位置安装。`status.cmd` 可查看本地诊断。

## 可选配置

通常不用配置。程序使用 `CODEX_HOME`，未设置时使用 `~/.codex`；自动查找已安装的 Codex 可执行程序。

自定义设置放在 `%LOCALAPPDATA%\CodexUsageStrip\config.json`，三个字段均为可选的绝对路径：

```json
{
  "codexHome": "C:/path/to/your/codex-home",
  "codexExecutable": "C:/path/to/codex.exe",
  "desktopExecutable": "C:/path/to/ChatGPT.exe"
}
```

也可以用 `start.cmd -Config "C:\path\personal.json"` 指定另一份配置。账号凭据仍由你已登录的 Codex 管理。

## 数据与兼容性

这是独立社区工具。它创建附着于 Codex 主窗口的子窗口，不修改 Codex 安装包。只通过[官方 app-server 接口](https://learn.chatgpt.com/docs/app-server)初始化并读取 `account/rateLimits/read`，不发起模型对话或兑换银行重置。

银行次数采用服务返回的计数；只有完整、日期已知的可用明细才显示确定的最早到期。明细截断时标记“已知最早”，缺失时显示未知。读取失败会标记旧数据并退避重试；不同订阅返回的窗口可能不同。

当前在 Windows 商店版 Codex 验证。其他安装位置可通过 `desktopExecutable` 指定。macOS/Linux 不支持；Codex 更新若改变窗口结构或接口，可能需要适配。运行状态仅存本机，项目和发布包不包含个人配置、登录凭据或账号用量记录。

## 从源码运行与构建

源码运行需要 Windows Python 3.10+，运行时仅使用标准库：

```powershell
python -B main.py
python -B -m unittest discover -v
```

构建发布包还需要 PyInstaller。构建中间文件必须放在独立的系统临时目录，发布输出放到源码目录以外：

```powershell
python -B build.py --work-dir "$env:TEMP\codex-strip-build" --output-dir "C:\Releases\CodexUsageStrip"
```

构建器清理自己创建的临时子目录，输出 EXE、ZIP 和 SHA256 校验文件。

MIT License。欢迎提交 Issue 和 Pull Request。
