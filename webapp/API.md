# 标签打印助手 API 文档

> 姓名、手机号和详细地址均为脱敏格式示例；含 `*` 的输入仅用于展示结构，实际测试请替换为测试数据。

> 版本: v2.1 | 主服务: `http://<host>:4050` | 通用打印接口: `http://<host>:4051` | 协议: HTTP/1.1 REST + SSE

---

## API 路径概览

```
/api/                        公共接口
├── health                    健康检查
├── readiness                 助手与设备就绪状态
├── printers                  打印机列表
├── printers/refresh          刷新打印机
└── printers/info             打印机详情

/api/address/                 地址标签（收货人）
├── parse                     地址解析
├── preview                   标签预览
├── print                     批量打印
├── print/{id}/status (SSE)   打印进度
├── print/{id}/cancel         取消打印
└── template/default          默认模板

/api/inventory-label/         库存标签（箱子/商品）
├── preview                   标签预览
├── print                     批量打印
├── print/{id}/status (SSE)   打印进度
├── print/{id}/cancel         取消打印
└── template/{type}/default   默认模板

通用打印接口（独立端口 4051，默认开启）
/health                       存活检查
/printers                     打印机列表
/preview                      自定义标签预览
/print                        自定义打印任务
/print/{id}/status (SSE)      打印进度
/print/{id}/cancel            取消打印
/print/raw                    原始指令打印
```

---

## 1. 公共接口

### 1.1 健康检查

```
GET /api/health
```

**响应:**
```json
{"status": "ok", "strategy": "CpcaStrategy"}
```

`GET /api/readiness` 额外检查助手连接，返回 `ready`、`printers`、`printReady`。
`ready` 表示助手可通信，`printReady` 表示发现了设备，均不保证实际出纸。

### 任务状态约定（Windows / Linux 共用）

三个异步打印接口共用 FIFO 队列。`taskId` 是不应自行解析或截断的字符串。
状态订阅会回放已有事件，再等待新事件；空闲时发送 SSE 注释心跳，不再因 30 秒无进度自动终止。
每个订阅独立读取，断线重连可能再次收到旧事件，应按 `current` 更新显示，不能把事件当成新的打印请求。

`done` 表示该项提交给 SDK 成功，不是传感器确认出纸。遇到错误后停止当前任务，
发送 `error` 并以带有 `error` 信息的 `finished` 结束；不能只看到 `finished` 就判断全部成功。
未连接打印机时也会结束事件流，不会无限等待。

任务状态只保存在当前进程内，重启后丢失；已完成任务保留最多一小时，队列容量上限
200 个任务，达到上限时优先清理已完成任务，没有可清理任务则返回 429。
未知或已清理的任务查询、取消返回 404。`copies` 限制为 1～100。
取消对排队任务和正在打印任务都有效，但不能撤回已进入打印机缓冲区的内容。

### 1.2 打印机列表

```
GET /api/printers
```

**响应:**
```json
{
    "printers": [
        {"name": "DTP-LP300", "type": 1, "ip": "", "hostname": ""}
    ]
}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `name` | string | 打印机名称 |
| `type` | int | 1=本地USB, 2=局域网共享, 3=自带网络 |
| `ip` | string | 主机IP |
| `hostname` | string | 主机名 |

### 1.3 刷新打印机

```
POST /api/printers/refresh
```

### 1.4 打印机详情

```
GET /api/printers/info
```

**响应:**
```json
{"name":"DTP-LP300","dpi":203,"darkness":5,"speed":2,"gapType":2,"opened":true}
```

---

## 2. 地址标签 `/api/address`

### 2.1 地址解析

```
POST /api/address/parse
```

**请求:**
```json
{
    "text": "张** 138****0000 浙江省杭州市某区某路***号\n李** 139****0000 北京市某区某路***号"
}
```

**响应:**
```json
{
    "items": [
        {"index":0,"name":"张**","phone":"138****0000","address":"浙江省杭州市","fullAddress":"浙江省杭州市某区某路***号","parseError":null}
    ],
    "strategy": "CpcaStrategy"
}
```

### 2.2 标签预览

```
POST /api/address/preview
```

**请求:**
```json
{
    "name": "张**",
    "phone": "138****0000",
    "address": "浙江省杭州市",
    "printerName": "DTP-LP300",
    "template": {"name": {"fontHeight": 5.0}}
}
```

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `name` | string | 是 | 收件人姓名 |
| `phone` | string | 是 | 电话 |
| `address` | string | 是 | 地址（到市级） |
| `printerName` | string | 是 | 打印机名称 |
| `template` | object | 否 | 模板覆盖 |

**响应:** `{"image": "data:image/png;base64,..."}`

### 2.3 默认模板

```
GET /api/address/template/default
```

### 2.4 批量打印

```
POST /api/address/print
```

**请求:**
```json
{
    "items": [
        {"name":"张**","phone":"138****0000","address":"浙江省杭州市"}
    ],
    "printerName": "DTP-LP300",
    "template": {"darkness":5},
    "copies": 1
}
```

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `items` | array | 是 | 打印项列表 |
| `printerName` | string | 是 | 打印机名称 |
| `template` | object | 否 | 模板覆盖 |
| `copies` | int | 否 | 每张份数，默认1 |

**响应:** `{"taskId":"a1b2c3d4","total":2}`

### 2.5 打印进度 (SSE)

```
GET /api/address/print/{taskId}/status
```

SSE 事件:
```json
{"taskId":"a1b2c3d4","current":1,"total":2,"status":"printing","item":{"name":"张**","phone":"138****0000","address":"浙江省杭州市"},"error":null}
```

status 值: `printing` | `done` | `error` | `cancelled` | `finished`

### 2.6 取消打印

```
POST /api/address/print/{taskId}/cancel
```

---

## 3. 库存标签 `/api/inventory-label`

> 供闲鱼库存管理系统通过局域网 HTTP 调用。

### 3.1 标签预览

```
POST /api/inventory-label/preview
```

**请求:**
```json
{
    "name": "蓝牙耳机 (白色·标准版)",
    "phone": "SKU-001",
    "address": "箱A · 电子产品",
    "labelType": "product",
    "printerName": "DTP-LP300",
    "template": {}
}
```

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `name` | string | 是 | 商品名 / 箱子名 |
| `phone` | string | 否 | SKU编号 / 箱子条码 |
| `address` | string | 否 | 规格描述 / 箱子描述 |
| `labelType` | string | 是 | `"box"` 或 `"product"` |
| `printerName` | string | 是 | 打印机名称 |
| `template` | object | 否 | 模板覆盖 |

### 3.2 默认模板

```
GET /api/inventory-label/template/{labelType}/default
```

`{labelType}` = `box` | `product`

### 3.3 批量打印

```
POST /api/inventory-label/print
```

**请求:**
```json
{
    "items": [
        {"name":"蓝牙耳机 (白色·标准版)","phone":"SKU-001","address":"箱A · 电子产品"}
    ],
    "labelType": "product",
    "printerName": "DTP-LP300",
    "template": {},
    "copies": 1
}
```

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `items` | array | 是 | 打印项列表 |
| `labelType` | string | 是 | `"box"` 或 `"product"` |
| `printerName` | string | 是 | 打印机名称 |
| `template` | object | 否 | 模板覆盖 |
| `copies` | int | 否 | 每张份数，默认1 |

**响应:** `{"taskId":"b2c3d4e5","total":2}`

### 3.4 打印进度 (SSE)

```
GET /api/inventory-label/print/{taskId}/status
```

格式同 2.5。

### 3.5 取消打印

```
POST /api/inventory-label/print/{taskId}/cancel
```

---

## 4. 通用打印接口（端口 4051）

> 独立服务端口（默认 4051，可通过配置 `custom_port` 修改，设为 `0` 关闭）。
> 供第三方系统通过 HTTP 描述任意格式的标签元素进行打印 / 预览，与主服务共用同一打印机。

### 4.1 健康检查

```
GET /health
```

**响应:**
```json
{"status": "ok", "service": "custom-print"}
```

### 4.2 打印机列表

```
GET /printers
```

**响应:**
```json
{"printers": [{"name": "P1-60753961", "type": 9, "ip": "172.25.0.1", "hostname": "DESKTOP-TS4FCLD"}]}
```

### 4.3 标签预览

```
POST /preview
```

**请求:**
```json
{
    "printerName": "P1-60753961",
    "job": {"width": 40, "height": 30, "gapType": 2, "darkness": 5, "speed": 2},
    "pages": [
        [
            {"type": "text", "text": "张**", "x": 0, "y": 0, "width": 40, "height": 8, "fontHeight": 5, "horizontalAlignment": 1},
            {"type": "barcode", "text": "6901234567890", "x": 0, "y": 12, "width": 28, "height": 8}
        ]
    ]
}
```

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `printerName` | string | 否 | 打印机名称（空则自动选择） |
| `job` | object | 否 | 标签尺寸与打印参数 |
| `pages` | array | 是 | 每页一个元素数组（多页批量） |

`job` 字段: `width`(mm, 默认40) / `height`(mm, 默认30) / `orientation`(0~270, 默认0) / `gapType`(2=间隙纸) / `darkness`(0~14, 默认5) / `speed`(0~4, 默认2)

**响应:** `{"image": "data:image/png;base64,..."}`（仅第一页）

> 预览模式不支持 `line` / `circle` 元素（会被自动跳过），实际打印不受影响。

### 4.4 打印

```
POST /print
```

**请求:** 结构同 4.3，另加 `copies`：
```json
{
    "printerName": "P1-60753961",
    "copies": 1,
    "job": {"width": 40, "height": 30},
    "pages": [[
        {"type": "text", "text": "张**", "x": 0, "y": 0, "width": 40, "height": 8, "fontHeight": 5},
        {"type": "qrcode", "text": "https://example.com", "x": 28, "y": 12, "width": 12, "height": 12}
    ]]
}
```

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `printerName` | string | 是 | 打印机名称 |
| `pages` | array | 是 | 每页一个元素数组 |
| `job` | object | 否 | 标签尺寸与打印参数 |
| `copies` | int | 否 | 每页打印份数，默认1（1~100） |

**响应:** `{"taskId":"a1b2c3d4","total":1}`

### 4.5 打印进度 (SSE)

```
GET /print/{taskId}/status
```

SSE 事件:
```json
{"taskId":"a1b2c3d4","current":1,"total":1,"status":"done","item":null,"error":null}
```

status 值: `printing` | `done` | `error` | `cancelled` | `finished`

### 4.6 取消打印

```
POST /print/{taskId}/cancel
```

### 4.7 原始指令打印（高级）

```
POST /print/raw
```

直接透传打印机原始指令（TSPL / CPCL / ESC-POS 等），自由度最大化。

**请求:**
```json
{
    "printerName": "P1-60753961",
    "copies": 1,
    "data": "<hex / base64 / 纯指令文本>"
}
```

**响应:** `{"status": "ok"}`

### 4.8 元素类型

| type | 说明 | 关键字段（单位 mm） |
|---|---|---|
| `text` | 文本 | `text, x, y, width, height, fontHeight, fontStyle, horizontalAlignment, verticalAlignment` |
| `barcode` | 一维码 | `text, x, y, width, height, textHeight, barcodeType` |
| `qrcode` | 二维码 | `text, x, y, width, height, eccLevel` |
| `pdf417` | PDF417 | `text, x, y, width, height` |
| `dataMatrix` | DataMatrix | `text, x, y, width, height` |
| `image` | 图片 | `data(base64), x, y, width, height` |
| `rect` | 矩形 | `x, y, width, height, lineWidth` |
| `ellipse` | 椭圆 | `x, y, width, height, lineWidth` |
| `circle` | 圆形 | `x, y, radius, lineWidth` |
| `line` | 直线 | `x1, y1, x2, y2, lineWidth` |

> 坐标与尺寸单位全部为毫米。`barcodeType` 为一维码类型（0=自动），与元素类型字段 `type` 不冲突。

### 4.9 鉴权（预留）

配置 `custom_token` 为空时不鉴权（默认）；非空时所有请求需携带请求头 `X-API-Token: <token>`，否则返回 401。

### 4.10 完整示例（curl）

```bash
# 打印：文本 + 一维码 + 二维码
curl -X POST http://127.0.0.1:4051/print \
  -H "Content-Type: application/json" \
  -d '{
    "printerName": "P1-60753961",
    "copies": 1,
    "job": {"width": 40, "height": 30},
    "pages": [[
      {"type": "text", "text": "张**", "x": 0, "y": 0, "width": 40, "height": 8, "fontHeight": 5},
      {"type": "barcode", "text": "6901234567890", "x": 0, "y": 12, "width": 28, "height": 8},
      {"type": "qrcode", "text": "https://example.com", "x": 30, "y": 12, "width": 10, "height": 10}
    ]]
  }'
```

```bash
# 订阅打印进度（SSE）
curl -N http://127.0.0.1:4051/print/{taskId}/status
```

---

## 5. 数据结构

### ElementStyle

| 字段 | 类型 | 说明 |
|---|---|---|
| `text` | string | 显示文本 |
| `x`, `y`, `width`, `height` | float | 坐标/尺寸 (mm) |
| `fontHeight` | float | 字号 (mm) |
| `fontStyle` | int | 0=常规 1=粗体 2=斜体 3=粗斜体 |
| `horizontalAlignment` | int | 0=左 1=中 2=右 3=拉伸 |
| `verticalAlignment` | int | 同上 |

### LabelTemplate

| 字段 | 类型 | 说明 |
|---|---|---|
| `labelWidth`, `labelHeight` | float | 标签尺寸 (mm) |
| `gapType` | int | 0=连续纸 2=间隙纸 3=黑标纸 |
| `darkness` | int | 浓度 0~14 |
| `speed` | int | 速度 0~4 |
| `title`, `name`, `phone`, `address` | ElementStyle | 四个文本位 |

### 预置模板

| 模板名 | 用途 |
|---|---|
| `address` | 收货地址: name=姓名, phone=电话, address=省+市 |
| `box` | 箱子标签: name=箱名, phone=条码, address=描述 |
| `product` | 商品标签: name=商品名, phone=SKU编号, address=所属箱 |

---

## v1 → v2 路径迁移

| v1 | v2 |
|---|---|
| `POST /api/parse` | `POST /api/address/parse` |
| `POST /api/preview` | `POST /api/address/preview` |
| `POST /api/print` | `POST /api/address/print` |
| `GET /api/print/{id}/status` | `GET /api/address/print/{id}/status` |
| `POST /api/print/{id}/cancel` | `POST /api/address/print/{id}/cancel` |
| `GET /api/template/default` | `GET /api/address/template/default` |
| `GET /api/health` | 不变 |
| `GET /api/printers` | 不变 |
| `POST /api/printers/refresh` | 不变 |
| `GET /api/printers/info` | 不变 |

---

## 错误响应

```json
{"detail": "错误描述信息"}
```
