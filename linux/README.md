# Linux 部署状态

截至 2026-11-12，NAS agent 报告已部署官方 dtpweb 2.5.20251022，
`check_plugin()` 成功，打印助手监听 15216；打印机尚未接入 NAS，
因此设备识别、真实出纸及重启恢复仍需实测。此记录不是本仓库在 NAS 上的验收结果。

## 官方打印助手

- 官网入口：https://www.detonger.com/#/sdk/detail?sdkID=0B856F81-AB4C-DD7B-3B09-B467E60BC48D
- 官方下载：https://dtcloud.d6688.cn/File/Zip/E25/E259183451C40D3D205FBBFDC89BBE56.zip
- 压缩包内：`lpapi-2.5.20251022-linux.tar.gz`
- AMD64 安装包：`v2.5.20251022/amd64/dtpweb-2.5.20251022-amd64.deb`
- 安装包 SHA256：`6b45b76937333bdf0ebb37e4942a4216a5d1e9ef511d4b69d33b51e21d7b60ab`

本机提取的安装包保存在 `output/official-linux-sdk/`，作为下载产物不提交到 Git。
该包与 `com.detonger.p1` CUPS 驱动是不同组件，Python SDK 依赖前者的 HTTP 服务。

## 后续适配范围

保留网页、地址解析、标签模板、SDK 绘制和预览，新增不依赖 Windows 托盘的
双端口启动入口；将配置、日志和打印助手地址参数化。NAS 的现有脚本应在读取
真实内容、去除机器凭据并改成可配置路径后再纳入本仓库，不能根据调研记录直接虚构脚本。

验收需覆盖中文和二维码标签、批量打印、预览、取消任务、USB 重连和重启恢复。
不要同时让 CUPS 队列与 dtpweb 向 P1 发送任务。
