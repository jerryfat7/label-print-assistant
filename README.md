# 标签打印助手

德佟 P1 标签打印服务，提供网页、地址标签、库存标签和通用自定义打印接口。
Python 代码通过 HTTP 调用厂商的 dtpweb 打印助手；安装 Python wheel 不会安装打印助手本体。

## 项目边界

本目录是打印服务的独立 Git 仓库。上一级是项目容器目录，同级的
`../xianyu-auto-reply-fix/` 是另一个独立仓库，两者通过 HTTP 接口通信。
不要把同级项目、运行数据或凭据复制进本仓库。

```text
label-print-assistant/
├── webapp/                     # 共用业务接口、标签绘制和网页
├── win_tray/                   # Windows 托盘入口和 EXE 打包
├── linux/                      # Linux 部署状态与后续适配说明
├── demo/                       # 厂商 SDK 演示；运行可能实际打印
├── icon/
├── dtpweb-*.whl                # 项目当前使用的厂商 Python SDK
├── requirements-common.txt
└── requirements-linux.txt
```

根目录的两份厂商 PDF 随仓库保存，供核对 SDK 接口。
`dist/`、`output/`、虚拟环境和本机编辑器设置保留在磁盘，但不提交。
厂商安装包来源及 Linux 部署状态见 [Linux 说明](linux/README.md)。

## Windows

从仓库根目录执行，使用 Python 3.10 或更新版本：

```powershell
python -m venv .venv-build
.\.venv-build\Scripts\python.exe -m pip install -r win_tray/requirements-win.txt
.\.venv-build\Scripts\python.exe win_tray/tray_app.py
```

先安装 P1 官方 Windows 驱动及其附带的 dtpweb 打印助手。
托盘入口启动 4050 和 4051 两个端口，配置和日志位于
`%APPDATA%\LabelPrintAssistant\`。

打包命令：

```powershell
.\.venv-build\Scripts\python.exe win_tray/build.py --arch x64
```

也可运行 `win_tray/build_64.bat`。详细说明见 [Windows 文档](win_tray/README.md)。

## Linux

Linux 与 Windows 使用同一份业务代码，已有单进程双端口入口、普通用户安装和进程守护脚本。
Python 3.11 依赖版本已在飞牛 x86_64 验证。从仓库根目录执行：

```bash
bash linux/install.sh
# 编辑生成的配置，指定助手地址和需要监听的网卡
bash linux/service.sh start
```

前台调试：

```bash
.venv/bin/python -m webapp.server --config /path/to/config.json
```

配置、字体、自启动和回退见 [Linux 说明](linux/README.md)。
软件测试通过不代表物理出纸通过，实测范围见 [验收记录](linux/VALIDATION.md)。

## 代码协作与发布

`main` 保存同时服务 Windows 和 Linux 的共用代码；平台差异放入各自目录。
Linux 适配使用短期任务分支，例如 `feat/linux-support`，验收后合回 `main`。
修复和新功能也使用任务分支，不长期维护两份按操作系统分叉的业务代码。

Windows 和 NAS 各自克隆同一个仓库，通过提交、推送和拉取同步。
每次部署记录提交号；正式版本使用标签，例如 `v1.1.0`，
同一标签可以发布 Windows EXE 和 Linux 部署包。

自动检查可以验证导入、接口和标签参数；实际出纸、尺寸、扫码、USB 重连和
NAS 重启恢复必须在连接 P1 的设备上验收。

公共依赖用于 Windows/Linux 共用代码；Linux Python 3.11 另有实测版本约束。
对外接口见 [API 文档](webapp/API.md)。
