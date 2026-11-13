# Linux 标签打印服务

复用官方 dtpweb 打印助手，提供 4050 网页/业务接口和 4051 通用打印接口。
两个端口运行在同一进程、同一事件循环中，共享 SDK 和打印任务队列。
Windows 托盘入口仍使用同一份业务代码。

## 安装

建议使用已在飞牛 x86_64 上验证的 Python 3.11。源码、配置、虚拟环境和日志
均应放在持久存储目录。以下命令在仓库根目录运行：

```bash
export LABEL_STATE_DIR="$HOME/.local/state/label-print-assistant"
export LABEL_PYTHON="$PWD/.venv/bin/python"
bash linux/install.sh
```

安装脚本创建虚拟环境、安装 Python 依赖和用户级 Noto Sans CJK SC 字体。
Python 3.11 使用 `constraints-py311.txt` 中的实测版本；其他 Python 版本仅使用
公共依赖清单，尚未在飞牛上验收。已有配置不会被覆盖。
字体来自 Noto 官方仓库的固定提交，下载后校验 SHA256，保存原始 SIL Open Font License。
不需要 sudo，也不会修改 CUPS 或其他打印机队列。

### P1 持久 USB 授权

如果助手能发现 USB 设备却无法读取名称，先检查运行服务的账户是否能读写设备节点。
一次性的 `setfacl` 授权可能随拔插失效；持久授权使用 P1 的厂商和产品 ID，
只匹配该型号的 USB 设备，不依赖 Bus/Device 编号。

在实际运行服务的普通用户终端中执行：

```bash
bash linux/install_usb_rule.sh --user "$(id -un)" --dry-run
sudo bash linux/install_usb_rule.sh --user "$(id -un)"
```

安装器写入 `/etc/udev/rules.d/99-label-print-assistant-p1.rules`，
让指定用户成为 P1 设备节点的拥有者，使用 `0660` 权限；保留系统原有设备组。
它会重载规则，并只对匹配 P1 的设备触发 change 事件。此步需要一次 sudo，
之后打印服务仍以普通用户运行。插拔后应再次检查名称和连接；整机重启恢复也需实测。
安装器不会写入收货信息、密码、设备序列号或固定的个人用户名。

## 配置与启动

默认配置文件为 `$LABEL_STATE_DIR/config.json`，可用 `LABEL_CONFIG` 指定其他路径。
格式见 `config.example.json`。相对路径以配置文件所在目录为基准。

| 字段 | 用途 |
|---|---|
| `host` | 默认本机访问；局域网访问可设置对应网卡地址或 `0.0.0.0` |
| `port` / `custom_port` | 主端口与通用打印端口；第二端口设为 0 可关闭 |
| `custom_token` | 沿用原有 4051 鉴权方式，空字符串不校验令牌 |
| `sdk_host` / `sdk_port` | 助手地址；端口为 0 时检测 15216、35216 |
| `sdk_timeout` | 单次助手请求超时秒数；不会自动重试打印提交 |
| `font_name` | 推荐 `Noto Sans CJK SC`，同时覆盖中文、英文、数字 |
| `log_dir` | 服务和助手日志目录，自动轮转 |
| `helper_executable` / `helper_lib_dir` | 可选的已有助手程序及动态库目录 |

留空 `helper_executable` 时只连接现有助手。填写后，服务可在助手未运行或退出时启动它，
把 `helper_lib_dir` 加入 `LD_LIBRARY_PATH`。发现已有助手则直接复用；正常停止时
仅终止本服务创建的助手。不要另外启动一份抢占相同端口。

在使用相同 `LABEL_STATE_DIR`、`LABEL_PYTHON`、`LABEL_CONFIG` 的环境中执行：

```bash
bash linux/service.sh start
bash linux/service.sh status
bash linux/service.sh restart
bash linux/service.sh stop
```

脚本使用 `flock` 防止重复实例；守护进程在 Python 服务退出后重新启动它。
`status` 只报告进程，不等于打印机就绪。`/api/health` 表示网页服务存活；
`/api/readiness` 的 `ready` 表示助手可通信，`printReady` 表示发现设备，均不证明实际出纸。
缺少助手时，网页仍可提供解析与诊断，打印和预览会明确失败。

前台运行：

```bash
.venv/bin/python -m webapp.server --config /path/to/config.json
```

不要将双端口拆成独立 Python 进程或开启多个 worker。

## 自启动、升级与回退

把设置好上述环境变量的启动命令放入当前用户的 `crontab @reboot`，或交给已有进程管理器。
部署和恢复应使用同一用户，确保用户字体和 USB 权限一致。开机启动的实际效果仍需整机重启验收。

建议用 `releases/<提交号>/` 保存源码版本，`current` 指向当前版本；配置、日志和虚拟环境
放在持久共享目录。更新前记录旧提交，备份配置和依赖清单，停止服务后切换 `current`，
安装依赖并检查两个端口。回退时恢复旧版本指向及对应配置、依赖，再启动服务。

## 软件测试与实机验收

```bash
python -m unittest discover -s tests -v
python linux/smoke_test.py --output-dir /path/to/test-output
```

自动化测试使用模拟 SDK，不操作物理打印机。`smoke_test.py` 使用真实 HTTP 和 SDK，
生成四类 PNG 预览、校验解析与模板；只在设备列表为空时用不存在的打印机名称测试失败路径。
发现设备后跳过所有打印提交测试。

实测范围见 [验收记录](VALIDATION.md)。P1 接入后还需验证 40×30 mm 实际尺寸、
中文与条码、二维码、批量打印、USB 断连、取消边界以及 NAS 重启恢复。
已经进入打印机缓冲区的内容不能保证被取消。

## 官方打印助手

- 官网入口：https://www.detonger.com/#/sdk/detail?sdkID=0B856F81-AB4C-DD7B-3B09-B467E60BC48D
- 官方下载：https://dtcloud.d6688.cn/File/Zip/E25/E259183451C40D3D205FBBFDC89BBE56.zip
- 压缩包内：`lpapi-2.5.20251022-linux.tar.gz`
- AMD64 安装包：`v2.5.20251022/amd64/dtpweb-2.5.20251022-amd64.deb`
- 安装包 SHA256：`6b45b76937333bdf0ebb37e4942a4216a5d1e9ef511d4b69d33b51e21d7b60ab`

本机提取的安装包保存在 `output/official-linux-sdk/`，作为下载产物不提交到 Git。
该包与 `com.detonger.p1` CUPS 驱动是不同组件，Python SDK 依赖前者的 HTTP 服务。

本服务不依赖 CUPS；不要同时让 CUPS 队列与 dtpweb 向 P1 发送任务。
