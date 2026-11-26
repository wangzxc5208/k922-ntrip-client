$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $projectRoot

$pythonPath = Join-Path $projectRoot ".venv\Scripts\python.exe"
$iconPath = Join-Path $projectRoot "assets\k922_ntrip.ico"
$releasePath = Join-Path $projectRoot "build\release"
New-Item -ItemType Directory -Path $releasePath -Force | Out-Null
if (-not (Test-Path -LiteralPath $pythonPath)) {
    if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
        throw "未找到 Python 启动器 py，请先安装 Python 3.10 或更新版本。"
    }
    py -3 -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw "创建 Python 环境失败。" }
}

& $pythonPath -m pip install -r requirements-build.txt
if ($LASTEXITCODE -ne 0) { throw "安装打包依赖失败。" }

$buildArguments = @(
    "--noconfirm",
    "--clean",
    "--onedir",
    "--windowed",
    "--name", "K922 NTRIP Client",
    "--distpath", $releasePath,
    "--workpath", (Join-Path $projectRoot "build\pyinstaller"),
    "--specpath", (Join-Path $projectRoot "build\spec"),
    "--icon", $iconPath,
    "--add-data", "$iconPath;assets",
    "--collect-submodules", "serial.tools",
    "app.py"
)
& $pythonPath -m PyInstaller @buildArguments
if ($LASTEXITCODE -ne 0) { throw "PyInstaller 打包失败。" }

$distPath = Join-Path $projectRoot "dist"
New-Item -ItemType Directory -Path $distPath -Force | Out-Null
$bundlePath = Join-Path $releasePath "K922 NTRIP Client"
$executablePath = Join-Path $bundlePath "K922 NTRIP Client.exe"

# PyInstaller may collect an unrelated ICU DLL from the build machine's PATH.
# This Qt build resolves ICU through Windows; shipping an incompatible icuuc.dll
# makes Qt6Core fail to load with ERROR_PROC_NOT_FOUND.
$privateIcuPath = Join-Path $bundlePath "_internal\icuuc.dll"
if (Test-Path -LiteralPath $privateIcuPath) {
    [System.IO.File]::Delete($privateIcuPath)
}

Copy-Item -LiteralPath (Join-Path $projectRoot "README.md") -Destination $bundlePath -Force
Copy-Item -LiteralPath (Join-Path $projectRoot "config.example.json") -Destination $bundlePath -Force

$quickStartPath = Join-Path $bundlePath "QUICK_START.txt"
@'
K922 NTRIP Client 首次使用

1. 解压整个压缩包，并保持“K922 NTRIP Client”文件夹中的文件完整。
2. 双击文件夹中的“K922 NTRIP Client.exe”启动；不要单独移动 EXE。
3. 第一页“连接配置”中选择 RS232 串口和波特率，填写 CORS 主机、端口、挂载点和账号。
4. 点击“测试账号”会持续发送合成 GGA 并接收差分数据，不打开串口或保存测试配置；再次点击“停止测试”结束。
5. 默认测试坐标是上海示例位置。若服务商按区域授权，请改成服务覆盖范围内的坐标。
6. 在“板卡功能”页设置板卡 GGA 输出频率（当前授权最高 20 Hz）、GNSS/INS 和双天线姿态选项。点击“启动链路”后，客户端下发配置并保存；CORS 上行 GGA 仍固定每 5 秒一次。
7. 启用惯导前请按实际安装方向与实测杆臂设置 IMU 参数；双天线定向需要接好两根天线。调整姿态频率后，需选择“输出双天线定向与姿态”才会下发该频率。
8. 第三页“运行监控”查看链路状态、定位和姿态；第四页“运行日志”记录状态变化并保留最近 500 条，账号测试收到数据后可点击“查看差分”检查 RTCM 消息类型、CRC 校验和 HEX 样本。
9. 点击窗口顶部“外观”可切换深色/浅色主题和四种强调色；选择会自动保存。

配置保存在当前 Windows 用户的 %APPDATA%\K922 NTRIP Client\config.json。
账号密码由 Windows DPAPI 保护。若服务商端口不支持 TLS，界面会要求确认明文传输风险。
'@ | Set-Content -LiteralPath $quickStartPath -Encoding utf8

$archivePath = Join-Path $distPath "K922 NTRIP Client Windows.zip"
$temporaryArchive = Join-Path $distPath ("K922-" + [guid]::NewGuid().ToString("N") + ".zip")
try {
    Compress-Archive -LiteralPath $bundlePath -DestinationPath $temporaryArchive
    & $pythonPath (Join-Path $projectRoot "tests\smoke_windows_package.py") $temporaryArchive
    if ($LASTEXITCODE -ne 0) { throw "解压后的客户端未通过启动检查，未发布此压缩包。" }
    if ([System.IO.File]::Exists($archivePath)) {
        [System.IO.File]::Replace($temporaryArchive, $archivePath, [NullString]::Value)
    } else {
        [System.IO.File]::Move($temporaryArchive, $archivePath)
    }
} finally {
    [System.IO.File]::Delete($temporaryArchive)
}

Write-Output "打包完成：$executablePath"
Write-Output "压缩包：$archivePath"
