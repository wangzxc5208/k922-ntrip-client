# K922 NTRIP Client

面向 K922 RTK 板卡的 Windows 桌面客户端：读取 RS232 上的 GGA，通过 NTRIP 获取 CORS 差分流，再把 RTCM 原始数据写回板卡串口。

## 启动桌面界面

需要 Python 3.10 或更新版本。在 PowerShell 中进入项目目录：

```powershell
py -m pip install -r requirements.txt
py .\app.py
```

启动后默认打开“连接配置”。窗口顶部的启动和停止按钮在四个页面都可使用。板卡 GGA、IMU 和定向参数在“板卡功能”页设置。

## Windows 可执行程序

解压 `dist\K922 NTRIP Client Windows.zip` 后，双击 `K922 NTRIP Client\K922 NTRIP Client.exe`。请保留同一文件夹中的 `_internal` 依赖目录。如果需要自己重新打包，在项目目录打开 PowerShell 并运行：

```powershell
.\build_windows.ps1
```

脚本会安装打包依赖，在临时目录解压生成的 ZIP，并启动和关闭其中的客户端。启动检查通过后发布到 `dist\K922 NTRIP Client Windows.zip`。压缩包内的 `QUICK_START.txt` 有串口、CORS 和账号测试的操作步骤。

界面会扫描可用串口。填写串口号、波特率、CORS 主机、端口、挂载点和账号后，点击“启动链路”。用户名和密码可同时留空（取决于 CORS 服务商）。TLS 和 NTRIP 版本也可以在界面中选择。CORS 账号优先使用 TLS；如果服务商只提供未加密端口，界面会要求确认账号将以明文网络传输。

页面按“连接配置 → 板卡功能 → 运行监控 → 运行日志”排列。运行日志会记录链路状态变化，并提供更大的日志查看区域；RTCM 样本可从日志页打开。

窗口顶部的“外观”菜单可切换深色/浅色主题和薄荷绿、海湾蓝、暮光紫、暖阳橙强调色。设置会立即生效，并保存到当前 Windows 用户的应用首选项中。

点击“测试账号”可持续验证 CORS 认证、挂载点和 RTCM 返回。它会使用配置区里的十进制度纬度/经度生成带校验和的合成 GPGGA，并每 5 秒上传一次；实时累计 GGA 数量、接收字节数和时长，不会打开串口、保存测试配置或修改板卡设置。再次点击“停止测试”结束。默认坐标是上海示例位置，测试前请改成账号服务覆盖区域内的坐标。要确认实体板卡 GGA 到 RTCM 的完整链路，请使用“启动链路”。

账号测试收到差分数据后，可点击“运行日志”右上角的“查看差分”，浏览 RTCM 3 消息类型、站点 ID、CRC-24Q 校验状态和原始 HEX 样本；样本也可复制或另存为 `.rtcm` 文件。

账号测试分别显示挂载点是否接受连接、已收到多少字节、是否找到 CRC-24Q 校验通过的完整 RTCM 3 帧。切换账号并重新测试会清空旧样本。

连接配置保存在当前 Windows 用户的 `%APPDATA%\K922 NTRIP Client\config.json`。Windows 上密码使用当前用户的 DPAPI 保护；其他平台使用系统凭据库。启动时会先向板卡发送以下命令，每条以 CRLF 结束。按这台板卡 `log reglista` 的授权结果，界面中的 GGA 输出频率最高设为 20 Hz，程序会换算为 `ontime` 秒数（20 Hz 对应 0.05 秒）：

```text
log gpgga ontime 5
saveconfig
```

客户端等到收到有定位质量的 GPGGA/GNGGA 后再连接 CORS。NTRIP v2 将初始 GGA 放在请求头，v1 在成功响应后发送；连接期间两者仍固定每 5 秒向 CORS 上传一次 GGA，与板卡输出频率独立。收到的 RTCM 会原样转发至 RS232。界面显示串口/CORS/GGA 状态、板卡定位、下行速率、累计字节、运行时间和日志。网络中断后自动重连；CORS 明确拒绝连接时会停止，方便修正配置。

板卡报告失去定位后，客户端会暂停上传 GGA。板卡停止输出时，有效期按板卡输出周期和 5 秒中的较大值取两倍。恢复有效定位后继续上传。如果板卡持续提供有效定位，而 CORS 连续 30 秒没有下发差分数据，客户端会记录原因并重连。

“板卡功能”页可以选择启动时保持现状、启用或关闭 GNSS/INS，并配置 IMU 轴向、IMU 到天线相位中心的 X/Y/Z 杆臂、动态初始化速度门限和 GNSS 失锁后的惯导推算时长。双天线定向/姿态输出可单独启停并设置 0.1–20 Hz 频率；频率框可预设，但只有选择“输出双天线定向与姿态”后才会下发。运行监控页会解析板卡 GPHPR 报文，显示航向、俯仰、横滚和解状态。默认保持板卡现状，不会自动覆盖已有惯导或定向配置。启用前应按实际安装方向和实测杆臂填写，双天线定向需要载板实际接出并连接两根天线。惯导需在 RTK 固定后按门限速度动态行驶完成初始化。

## 命令行模式

命令行入口仍然保留，适合无桌面环境。复制并编辑 JSON 配置后运行：

```powershell
Copy-Item config.example.json config.json
$env:K922_CORS_PASSWORD = "从 CORS 服务商获取的密码"
py .\ntrip_client.py --config .\config.json
```

命令行配置通过 `password_env` 指定密码环境变量，配置文件不接受明文密码。未启用 TLS 时，如果使用用户名和密码，还需要在 JSON 中明确将 `allow_insecure_auth` 设为 `true`。不要把含有 CORS 账号信息的配置提交到版本库；`config.json` 已加入忽略列表。

## 模块结构

- `k922_ntrip/config.py`：配置模型、校验、安全存储和旧配置迁移。
- `k922_ntrip/secrets.py`：Windows DPAPI 和系统凭据库适配。
- `k922_ntrip/account_test.py`：合成 GGA、CORS 账号探测和 RTCM 返回验证。
- `k922_ntrip/protocol.py`：NTRIP 请求、响应解析、TLS 和 HTTP chunked 解码。
- `k922_ntrip/service.py`：串口初始化、GGA 读取、CORS 重连与 RTCM 转发，不依赖 Qt。
- `k922_ntrip/ui/`：PySide6 窗口、连接/账号测试后台线程和视觉主题。
- `app.py`：桌面入口；`ntrip_client.py`：兼容命令行入口。

## 本地验证

运行纯本地模拟测试（不会连接真实 CORS 或串口）：

```powershell
py -m unittest discover -s tests -v
```
