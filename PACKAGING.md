# 打包为独立应用

发布包会内置 Python、PyQt6、NumPy、Pandas、SciPy、Matplotlib 和
`gfci_analysis`，目标电脑不需要安装 Python。

## 前置条件

1. 在要发布的系统上构建：macOS 构建 `.app`，Windows 构建 `.exe`。PyInstaller
   不支持跨系统生成应用。
2. 安装 [uv](https://docs.astral.sh/uv/)。
3. 保证 `gfci_analysis` 位于下列任一位置：
   - 当前项目的同级目录 `../gfci_analysis_refactored`
   - 当前项目的 `vendor/gfci_analysis_refactored`
   - 通过 `--engine-path` 指定的任意目录

## macOS

如果尚未安装 Apple 命令行工具，请先执行：

```bash
xcode-select --install
```

在 Finder 中双击 `build_macos.command`，或在终端执行：

```bash
./build_macos.command
```

产物：`dist/GFCI Analyzer.app`

如果 Python 或 `gfci_analysis` 不在默认位置：

```bash
uv run --extra build python scripts/build_app.py \
  --engine-path /path/to/gfci_analysis_refactored
```

## Windows

双击 `build_windows.bat`，或在 PowerShell/CMD 中执行：

```powershell
.\build_windows.bat
```

也可以直接执行：

```powershell
uv sync --extra build
uv run --extra build python scripts\build_app.py
```

产物：`dist\GFCI Analyzer.exe`

指定分析引擎目录：

```powershell
uv run --extra build python scripts\build_app.py `
  --engine-path C:\path\to\gfci_analysis_refactored
```

## 自定义名称和图标

```bash
uv run --extra build python scripts/build_app.py \
  --app-name "GFCI Analyzer" \
  --icon assets/torchdragon.ico
```

默认使用 `assets/torchdragon.ico`。Windows 会直接嵌入 `.ico`；macOS 构建脚本
会自动将其转换为多尺寸 `.icns`，确保 Finder 和 Dock 显示应用图标。也可以直接
为 macOS 传入已有的 `.icns` 文件。

## 避免 Windows 的“已保护你的电脑”警告

Windows 的 SmartScreen 会对**没有代码签名**或**从网络下载**的 `.exe` 弹出
“Windows 已保护你的电脑 / 未知发布者”提示。构建脚本已经做了以下降低误报的
处理：

1. **嵌入版本信息**：`gfci_gui.spec` 会自动生成并写入 `CompanyName`、
   `ProductName`、`FileVersion` 等资源，让文件看起来是正规程序，而不是
   匿名可执行文件。可用以下命令确认：

   ```powershell
   (Get-Item 'dist\GFCI Analyzer.exe').VersionInfo | Format-List *
   ```

2. **不使用 UPX 压缩**：`upx=False`，避免被启发式引擎误判为加壳恶意软件。

3. **单文件、无控制台**：`console=False`，双击即可运行。

### 如果仍然出现警告

按影响从大到小，依次尝试：

- **解除“网络来源”标记（最常见原因）**：从网盘、邮件、浏览器下载的 exe 会被
  打上 Mark-of-the-Web。在目标电脑上执行一次即可解除：

  ```powershell
  Unblock-File -Path '.\GFCI Analyzer.exe'
  ```

  或右键文件 → 属性 → 勾选“解除锁定” → 确定。

- **使用代码签名证书（根治办法）**：购买 OV/EV 代码签名证书，用
  `signtool` 签署后 SmartScreen 才会信任发布者：

  ```powershell
  signtool sign /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 `
    /f mycert.pfx /p PASSWORD "dist\GFCI Analyzer.exe"
  ```

  EV 证书可立即获得 SmartScreen 信誉；OV 证书需要累积下载量后信誉才会提升。

- **让用户手动放行**：点击“更多信息”→“仍要运行”。这只适合内部可信分发，
  不建议对最终用户这样要求。

- **通过内网/共享盘分发**：局域网共享或企业软件分发渠道通常不会触发
  SmartScreen。

> 说明：SmartScreen 的判定基于“发布者信誉”，任何未签名的个人构建都可能在
> 首次运行时被拦截，这是 Windows 的正常安全机制，并非程序本身有问题。

## 签名与发布

当前配置可生成可直接运行的应用，但默认不包含代码签名。

- macOS 对外分发时，建议使用 Apple Developer ID 签名并公证，否则 Gatekeeper
  可能提示“无法验证开发者”。
- Windows 对外分发时，建议使用代码签名证书签署 `.exe`，否则 SmartScreen
  可能显示警告（详见上一节）。
- 在 Intel Mac 上构建得到 x86_64 应用；在 Apple Silicon Mac 上构建得到 arm64
  应用。如需同时支持两者，需要分别在两类 Mac 上构建发布包。

## 常见问题

- **提示找不到 `gfci_analysis`**：使用 `--engine-path` 指向包含
  `gfci_analysis/__init__.py` 的项目根目录。
- **macOS 提示包已损坏**：确认应用来自可信来源，并对应用进行签名和公证；不要
  建议用户绕过 Gatekeeper。
- **构建后界面能开但分析失败**：检查 `dist` 产物是否由最新源码重新构建，并且
  构建输出中没有缺少模块的警告。
