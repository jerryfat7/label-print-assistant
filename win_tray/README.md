# 标签打印助手 —— Windows 托盘版

把「标签打印助手」打包成 Windows 桌面应用：**后台运行 + 右下角托盘图标**，无控制台窗口。

> 不修改 `webapp/main.py` 的原有启动逻辑。托盘入口 `tray_app.py` 通过
> `from webapp.main import app` 复用现有 FastAPI 应用对象，仅负责承载服务与托盘 UI。

---

## 成品

- `dist\LabelPrintAssistant-x64.exe`（约 40MB，单文件，64 位）
  - 双击运行 → 后台启动服务，右下角出现打印机托盘图标
  - 启动后自动打开打印页面
  - 双端口：
    - `http://<本机IP>:4050` —— 主服务（打印页面 / 闲鱼系统）
    - `http://<本机IP>:4051` —— 通用打印接口（第三方系统任意格式打印）

## 托盘菜单

| 菜单项 | 功能 |
|---|---|
| 打开打印页面 | 在浏览器打开前端页面（左键单击图标同样生效） |
| 重启服务 | 停止并重新启动打印服务 |
| 开机自启动 | 勾选 = 登录 Windows 后自动运行（写入注册表 `HKCU\...\Run`） |
| 退出 | 停止服务并退出托盘程序 |

## 配置

配置文件：`%APPDATA%\LabelPrintAssistant\config.json`

```json
{
  "host": "0.0.0.0",
  "port": 4050,
  "custom_port": 4051,
  "custom_token": "",
  "auto_start": false,
  "auto_open_browser": true,
  "log_level": "info"
}
```

- `custom_port`：通用打印接口端口，`0` 表示关闭
- `custom_token`：通用打印接口鉴权令牌（预留）。为空不鉴权；非空时请求需携带 `X-API-Token` 请求头

日志文件：`%APPDATA%\LabelPrintAssistant\logs\app.log`（UTF-8，自动轮转）

## 开发调试（无需打包）

```bat
python win_tray\tray_app.py
```

## 打包（64 位）

首次需要准备干净构建环境（避免把开发机上的无关大依赖打进 exe）：

```bat
python -m venv .venv-build
.venv-build\Scripts\python -m pip install -r win_tray\requirements-win.txt
```

然后一键打包：

```bat
win_tray\build_64.bat
```

产物输出到 `dist\LabelPrintAssistant-x64.exe`。

## 通用打印接口（端口 4051）

供第三方系统通过 HTTP 描述任意格式的标签元素进行打印 / 预览，与主服务共用同一打印机。

### 接口列表

| 接口 | 方法 | 说明 |
|---|---|---|
| `/health` | GET | 端口存活检查 |
| `/printers` | GET | 可用打印机列表 |
| `/preview` | POST | 生成标签预览图（base64 PNG，仅第一页） |
| `/print` | POST | 启动打印任务，返回 `taskId` |
| `/print/{taskId}/status` | GET | SSE 订阅打印进度 |
| `/print/{taskId}/cancel` | POST | 取消打印任务 |
| `/print/raw` | POST | 直接发送原始打印指令（TSPL/CPCL/ESC-POS） |

### 元素类型（`pages` 中每个元素）

| type | 说明 | 关键字段 |
|---|---|---|
| `text` | 文本 | `text, x, y, width, height, fontHeight, fontStyle, horizontalAlignment, verticalAlignment` |
| `barcode` | 一维码 | `text, x, y, width, height, textHeight, barcodeType` |
| `qrcode` | 二维码 | `text, x, y, width, height, eccLevel` |
| `pdf417` | PDF417 | `text, x, y, width, height` |
| `dataMatrix` | DataMatrix | `text, x, y, width, height` |
| `image` | 图片 | `data(仅打印时取 imageFile), x, y, width, height` |
| `rect` | 矩形 | `x, y, width, height, lineWidth` |
| `ellipse` | 椭圆 | `x, y, width, height, lineWidth` |
| `circle` | 圆形 | `x, y, radius, lineWidth` |
| `line` | 直线 | `x1, y1, x2, y2, lineWidth` |

> 坐标单位全部为毫米；`barcodeType` 对应 SDK 一维码类型（0=自动）。
> 预览模式不支持 `line` / `circle` 元素（会被跳过），实际打印不受影响。

### 打印示例

```bash
curl -X POST http://127.0.0.1:4051/print \
  -H "Content-Type: application/json" \
  -d '{
    "printerName": "P1-60753961",
    "copies": 1,
    "job": {"width": 40, "height": 30, "darkness": 5, "speed": 2},
    "pages": [[
      {"type": "text", "text": "张三", "x": 0, "y": 0, "width": 40, "height": 8, "fontHeight": 5},
      {"type": "barcode", "text": "6901234567890", "x": 0, "y": 12, "width": 30, "height": 8},
      {"type": "qrcode", "text": "https://example.com", "x": 30, "y": 12, "width": 10, "height": 10}
    ]]
  }'
```

打印为异步任务：`/print` 返回 `{taskId, total}`，再用 SSE 订阅 `/print/{taskId}/status` 获取逐张进度。

## 目录结构

```
win_tray/
├── tray_app.py               # 托盘 + 双端口服务入口（打包目标）
├── build.py                  # PyInstaller 打包脚本（--arch x64）
├── build_64.bat              # 一键打包 64 位
├── build_icons.py            # 由 icon/打印机.png 生成 app.ico
├── rthook_cpca.py            # runtime hook：修复 cpca 数据加载
└── requirements-win.txt      # 运行/打包依赖
webapp/
├── custom_print_service.py   # 通用打印核心逻辑（元素绘制/预览/原始指令）
├── custom_print_routes.py   # 通用打印 API 路由
└── custom_print_app.py       # 通用打印子应用（create_custom_app）
icon/
├── 打印机.png                # 源图标
└── app.ico                   # 生成的多尺寸 ICO
```

## 备注

- 依赖 `dtpweb`（纯 Python wheel，无外部依赖）已随 exe 打包。
- 地址解析使用 `cpca`（已打包数据文件）；若 cpca 不可用会自动降级为正则解析。
- 单实例：重复运行 exe 会弹出提示并让已有实例打开打印页面。
- 通用打印接口端口（4051）默认开启，可通过配置 `custom_port: 0` 关闭。
