# 闲鱼库存标签管理系统 —— 开发方案

> 版本: v3.0 | 日期: 2026-07-22 | 状态: 开发阶段

---

## 〇、项目实际情况

| 项目 | 路径 | 状态 |
|---|---|---|
| **电脑A** 闲鱼管理系统 | `../xianyu-auto-reply-fix/`（独立仓库） | ✅ 已部署运行 |
| **电脑B** 标签打印服务 | `webapp/` (端口 4050) | ✅ 已完成重构 |

### 电脑A 关键文件

| 文件 | 角色 | 改动 |
|---|---|---|
| `reply_server.py` | FastAPI 主服务器 | 新增库存 API |
| `db_manager.py` | SQLite 数据库管理 | 新增表 + CRUD 方法 |
| `global_config.yml` | 全局配置 | 新增打印服务地址 |
| `static/index.html` | SPA 前端主页面 | 新增库存管理 section |
| `static/js/app.js` | 前端 JS | 新增库存/分箱/发货清单逻辑 |

### 电脑A 新增文件

| 文件 | 角色 |
|---|---|
| `label_print_client.py` | HTTP 客户端，调用电脑B 打印 API |
| `auto_box_engine.py` | 分箱匹配引擎 |

---

## 一、数据库设计

### 1.1 箱子表 `inventory_boxes`

规则内嵌到箱子 — 箱子自身即是规则的载体。

```sql
CREATE TABLE inventory_boxes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    label       TEXT NOT NULL,             -- "小盒A-RE0吧唧"
    box_type    TEXT,                      -- 自由填："小盒"/"大箱"/"A4收纳盒"
    ip_tags     TEXT DEFAULT '*',          -- "re:从零,re0" 或 "*"（通配）
    cat_tags    TEXT DEFAULT '*',          -- "吧唧,徽章,badge" 或 "*"
    capacity    INTEGER,                   -- 软上限（NULL=不限制）
    is_full     INTEGER DEFAULT 0,         -- 0=可分配  1=已满（系统自动/用户手动）
    barcode     TEXT UNIQUE,
    location    TEXT,                      -- "书桌左抽屉"
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

| 字段 | 谁写 | 何时 |
|---|---|---|
| `capacity` | 用户 | 创建/编辑箱子时 |
| `is_full` | 系统自动 | 每次分配后: `if capacity IS NOT NULL AND current_count >= capacity → is_full=1` |
| `is_full` | 用户手动 | 前端按钮切换（物理上塞满了/还能塞） |

`is_full` 是分配闸门。**系统只升不降**（手动关除外），卖出一件不会自动恢复。每次分配时: 如果 `current_count >= capacity`，系统再次 `is_full=1`，保证参考线。

### 1.2 商品-箱子映射表 `inventory_product_box`

```sql
CREATE TABLE inventory_product_box (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id       TEXT NOT NULL,           -- 闲鱼商品 ID (关联 item_info 表)
    box_id        INTEGER NOT NULL REFERENCES inventory_boxes(id),
    label_printed INTEGER DEFAULT 0,
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(item_id, box_id)
);
```

### 1.3 箱子模板表 `box_templates`

```sql
CREATE TABLE box_templates (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL,              -- "吧唧小盒" / "IP专用盒" / "大收纳箱"
    ip_tags    TEXT DEFAULT '*',
    cat_tags   TEXT DEFAULT '*',
    box_type   TEXT DEFAULT '收纳箱',
    capacity   INTEGER,
    sort_order INTEGER DEFAULT 0
);
```

预置模板：

| name | ip_tags | cat_tags | box_type | capacity |
|---|---|---|---|---|
| 吧唧小盒 | * | 吧唧,徽章,badge | 小盒 | 40 |
| IP吧唧盒 | 待填 | 吧唧,徽章 | 小盒 | 40 |
| 大收纳箱 | * | * | 大箱 | NULL |
| A4文件夹盒 | * | 文件夹,资料夹 | 文件夹盒 | 30 |

`ip_tags='待填'` 的模板在创建时必须填写，否则拒绝保存。

### 1.4 现有表复用

- `item_info` 表 — 已有，闲鱼商品信息缓存（`item_id / item_title / item_price / images`）
- `orders` 表 — 已有，订单信息（`order_id / item_id / order_status`）
- **不新建独立规则表**，规则字段已在 `inventory_boxes` 中

---

## 二、自动分箱引擎

### 2.1 匹配逻辑

```
对于每个待分配商品 (item_info 中的 item):

1. 取 title（已包含 IP + 品类关键词："Re:从零 雷姆 吧唧"）

2. 按 priority DESC 遍历所有 is_full=0 的箱子:

   ip_ok  = '*' in ip_tags OR any(tag in title for tag in split(ip_tags))
   cat_ok = '*' in cat_tags OR any(tag in title for tag in split(cat_tags))

   if ip_ok AND cat_ok AND is_full=0:
       → 分配到该箱子
       → 检查 current_count >= capacity → is_full=1
       → 停止，不继续匹配

3. 如果遍历完所有箱子都没有匹配:
   → 标记为"未分配"

4. 如果所有匹配的箱子都已满:
   → 标记为"已满-需扩容"，附带信息: "已满箱子: 小盒A, 小盒B"
```

### 2.2 关键边界行为

| 边界 | 行为 |
|---|---|
| 商品同时匹配多个箱子 | 按 priority 降序，第一个有空位的箱子取走 |
| 所有匹配箱子已满 | **不**自动兜底到通配箱。提示用户:"已满箱子: 小盒A(40/40), 小盒B(40/40)。建议新建小盒C或扩容。" |
| 跨 IP 联动商品 | 自动匹配，在分箱结果页单独标注"联动商品"标签 |
| 通配箱 `ip_tags='*', cat_tags='*'` | 仅在没有 IP/品类专用箱时才会被匹配到。匹配顺序始终优先于"未分配" |

### 2.3 编辑箱子的字段限制

| 字段 | 允许随时修改 | 校验规则 |
|---|---|---|
| `name` | ✅ | 无限制 |
| `box_type` | ✅ | 无限制 |
| `capacity` | ✅ | 修改后立即重新判定: `if current_count >= capacity → is_full=1`；如果降低到小于当前数量，仅标记已满，不移走已有商品 |
| `ip_tags` | ⚠️ | 箱子为空 或 全部已有商品通过新规则匹配 |
| `cat_tags` | ⚠️ | 同上 |

`capacity` 修改的典型场景:

| 场景 | 行为 |
|---|---|
| 容量 40→30，当前有 35 件 | `is_full=1`（35≥30），已有商品保留，新商品不再分配 |
| 容量 40→60，当前有 35 件且之前是满的 | `is_full=0`（35<60），箱子重新开放分配 |
| 容量 40→NULL（不限） | `is_full` 不变，交给用户手动判断 |

修改 `ip_tags` 或 `cat_tags` 时：

```
if 箱子为空:
    → 允许修改

if 箱子非空:
    遍历箱内所有商品，用新规则重新匹配:

    if 全部通过:
        → 允许修改

    if 存在不匹配:
        → 拒绝修改，弹窗:
           "无法修改：箱内有 3 件商品不符合新规则。
            请先移走以下商品再试。"
           ┌──────────────────────────────────────┐
           │ ☑ 雷姆 吧唧 (ip=re:从零,cat=吧唧)     │
           │ ☑ 艾米莉亚 亚克力 (cat=亚克力→不匹配) │
           └──────────────────────────────────────┘
           [一键移入通配箱]  [手动逐个处理]
```

### 2.4 通配箱保障

系统中**必须始终存在至少一个** `ip_tags='*' AND cat_tags='*'` 的箱子。删除最后一个通配箱时拒绝操作，提示先创建新的。

---

## 三、重新分箱

### 触发方式

前端"库存管理"页面 → 点击 🔄 重新分箱 → 弹 GitHub 式确认：

```
┌─────────────────────────────────────────────────┐
│  ⚠️ 危险操作：重新分箱                           │
│                                                 │
│  此操作将清空所有商品-箱子映射，并按当前规则      │
│  重新匹配全部 150 件商品。                       │
│                                                 │
│  此操作不可撤销。                                │
│                                                 │
│  请输入「我确认删除所有映射」以确认：             │
│  ┌─────────────────────────────────────────┐    │
│  │                                         │    │
│  └─────────────────────────────────────────┘    │
│                                                 │
│  ───────────────────────────────────────        │
│         [取消]          [我确认重新分箱]         │
└─────────────────────────────────────────────────┘
```

### 后端行为

```
POST /api/inventory/rebox-all

1. 验证确认文本 = "我确认删除所有映射"
2. DELETE FROM inventory_product_box
3. 调用 AutoBoxEngine.run_all()
4. 返回报告:
   {
     "total": 150,
     "assigned": 142,
     "unmatched": 5,
     "overflow": 3,
     "overflow_detail": [
       {"item": "雷姆 吧唧", "matched_boxes": ["小盒A(满)", "小盒B(满)"]}
     ]
   }
```

---

## 四、发货清单

### 两个视图

**视图 1 — 订单视图（主要使用）**：

```
待发货订单：
├─ 订单 #1: 雷姆 吧唧 ¥39
│   → 📦 小盒A-RE0吧唧
├─ 订单 #2: 爱丽丝 文件夹 ¥25
│   → 📦 大箱X
└─ 订单 #3: 亚丝娜 吧唧 ¥45
    → 📦 小盒B-SAO吧唧
```

**视图 2 — 箱子核对视图（打包时用）**：

```
📦 小盒A-RE0吧唧 → 今天拿: 雷姆吧唧、拉姆吧唧
📦 小盒B-SAO吧唧 → 今天拿: 亚丝娜吧唧
📦 大箱X        → 今天拿: 爱丽丝文件夹
```

发货清单中每个商品展示缩略图（从 `item_info.images` 取第一张 URL）。

---

## 五、API 路由

### 5.1 电脑A 新增接口

基础路径: `/api/inventory`

| 方法 | 路径 | 说明 | Phase |
|---|---|---|---|
| `GET` | `/templates` | 箱子模板列表 | P2 |
| `GET` | `/boxes` | 箱子列表（含商品数、满状态） | P3 |
| `POST` | `/boxes` | 创建箱子（可选 from_template_id） | P3 |
| `POST` | `/boxes/{id}/clone` | 复制箱子（仅复制规则，不复制商品） | P3 |
| `PUT` | `/boxes/{id}` | 编辑箱子（name/box_type/capacity 可随时改；ip_tags/cat_tags 有校验） | P3 |
| `DELETE` | `/boxes/{id}` | 删除箱子（含通配箱保障校验） | P3 |
| `GET` | `/boxes/{id}/products` | 查看箱子内商品 | P3 |
| `POST` | `/auto-box` | 触发自动分箱（仅处理未分配商品） | P4 |
| `POST` | `/rebox-all` | 重新分箱（需确认文本） | P4 |
| `GET` | `/unmatched` | 未分配 + 溢出商品列表 | P4 |
| `PUT` | `/products/{item_id}/box` | 手动修改商品所属箱子 | P4 |
| `GET` | `/shipping-list` | 发货清单（订单视图 + 箱子视图） | P5 |
| `POST` | `/print-labels/{box_id}` | 打印指定箱子标签 | P6 |

### 5.2 电脑B 调用接口

| 接口 | 用途 |
|---|---|
| `POST /api/inventory-label/preview` | 预览箱子/商品标签 |
| `POST /api/inventory-label/print` | 批量打印标签 |
| `GET /api/inventory-label/print/{id}/status` | SSE 打印进度 |

### 5.3 电脑A 配置

`global_config.yml` 新增：

```yaml
label_printer:
  host: "192.168.1.20"
  port: 4050

auto_boxing:
  trigger_on_new_product: false   # 先手动触发，稳定后再开自动
  auto_print_labels: false
```

---

## 六、前端页面

侧边栏新增"库存管理"菜单，展开子项：

```
📦 库存管理
├── 箱子管理
├── 自动分箱
├── 未匹配商品
└── 发货清单
```

### 6.1 箱子管理页

- 表格: 标签 | 类型 | IP | 品类 | 容量 | 状态(🟢/🔴满) | 商品数 | 位置 | 操作
- [+ 新建箱子] → 弹出表单 → 顶部"从模板创建"下拉框
- 编辑 ip_tags/cat_tags 时触发后端校验，不通过则弹窗显示冲突商品
- 删除箱子时触发通配箱保障校验

### 6.2 自动分箱页

- 显示所有箱子规则概览（ip_tags | cat_tags | priority | 状态）
- [▶ 执行自动分箱] → 处理未分配商品
- [🔄 重新分箱] → GitHub 式确认弹窗
- 结果展示: 成功 N 件 / 未分配 M 件 / 溢出 K 件（列出详情）
- 联动商品单独标注

### 6.3 未匹配商品页

- 列表: 商品图片 | 标题 | 原因（无匹配规则 / 目标箱已满）
- 每行右侧: [手动分配] 下拉选择箱子

### 6.4 发货清单页

- 默认展示"订单视图"（按订单列出 → 指向哪个箱子）
- 切换按钮 → "箱子核对视图"（按箱子聚合 → 列出该箱今天要拿的商品）
- 商品缩略图 + [补打标签] 按钮
- 顶部统计: X箱 / Y件商品 / Z件标签未打印

---

## 七、开发阶段

### Phase 1：配置 + 打印客户端（0.5天）

| 文件 | 操作 |
|---|---|
| `global_config.yml` | 新增 `label_printer` 配置 |
| `label_print_client.py` | 新建 — 封装对电脑B `/api/inventory-label/*` 的 HTTP 调用 |

**验证**：`python label_print_client.py` → 电脑B 打印机出纸。

### Phase 2：数据库 + 模板（0.5天）

| 文件 | 操作 |
|---|---|
| `db_manager.py` | 新增 `_ensure_inventory_tables()` + Box/ProductBox/Template CRUD |
| `db_manager.py` | 初始化流程中建表 + 插入预置模板 |

**验证**：`sqlite3 data/app.db ".tables inventory%"` 看到 3 张表。

### Phase 3：箱子管理 API + 前端（1天）

| 文件 | 操作 |
|---|---|
| `reply_server.py` | 新增 `/api/inventory/templates` + `/api/inventory/boxes/*` |
| `static/index.html` | 侧边栏新增"库存管理"菜单 + 箱子管理 section |
| `static/js/app.js` | 箱子列表/新建(含模板)/编辑(含 ip_tags 校验)/删除逻辑 |

**验证**：从模板创建箱子 → 编辑 ip_tags → 删除箱子。

### Phase 4：自动分箱引擎 + API + 前端（1天）

| 文件 | 操作 |
|---|---|
| `auto_box_engine.py` | 新建 — `AutoBoxEngine` 类，实现匹配逻辑 + 边界行为 |
| `reply_server.py` | 新增 `/api/inventory/auto-box` + `/rebox-all` + `/unmatched` |
| `static/index.html` | 自动分箱 section + 未匹配 section |
| `static/js/app.js` | 触发分箱 / GitHub 确认弹窗 / 结果展示 / 手动改绑 |

**验证**：选一个 IP 专用箱 → 执行自动分箱 → 未匹配列表出现跨 IP 商品。

### Phase 5：发货清单（1天）

| 文件 | 操作 |
|---|---|
| `db_manager.py` | 新增 `get_shipping_list()` 聚合查询 |
| `reply_server.py` | 新增 `GET /api/inventory/shipping-list` |
| `static/index.html` | 发货清单 section（订单视图 + 箱子核对视图） |
| `static/js/app.js` | 视图切换 / 缩略图渲染 / [补打标签] 按钮 |

**验证**：有待发货订单 → 订单视图显示 → 切换箱子视图。

### Phase 6：标签打印集成（0.5天）

| 文件 | 操作 |
|---|---|
| `reply_server.py` | 新增 `POST /api/inventory/print-labels/{box_id}` |
| `label_print_client.py` | 在 `reply_server.py` 中 import 使用 |
| `static/js/app.js` | 发货清单页 [打印全部] 按钮 + SSE 进度 |

**验证**：点 [打印全部] → 打印机出纸 → `label_printed` 状态更新。

### Phase 7：多规格 SKU 适配（可选，1.5天）

| 文件 | 操作 |
|---|---|
| `db_manager.py` | 新建 `item_parents` + `item_skus`；迁移数据 |
| `XianyuAutoAsync.py` | 解析 `skuBase` 字段 |
| `static/js/app.js` | 商品列表折叠展开（父商品 + SKU 明细） |

---

## 八、改动总览

| 文件 | P1 | P2 | P3 | P4 | P5 | P6 | P7 |
|---|---|---|---|---|---|---|---|
| `global_config.yml` | 🟢 | | | | | | |
| `label_print_client.py` | 🆕 | | | | | 🟢 | |
| `db_manager.py` | | 🟢 | 🟢 | 🟢 | 🟢 | 🟢 | 🟢 |
| `auto_box_engine.py` | | | | 🆕 | | | |
| `reply_server.py` | | | 🟢 | 🟢 | 🟢 | 🟢 | 🟢 |
| `static/index.html` | | | 🟢 | 🟢 | 🟢 | | 🟢 |
| `static/js/app.js` | | | 🟢 | 🟢 | 🟢 | 🟢 | 🟢 |
| `XianyuAutoAsync.py` | | | | | | | 🟢 |

🟢=编辑 　 🆕=新建

---

## 九、工时估算

| Phase | 工时 | 依赖 |
|---|---|---|
| P1 打印客户端 | 0.5天 | 电脑B 已运行 |
| P2 数据库+模板 | 0.5天 | — |
| P3 箱子管理 UI | 1天 | P2 |
| P4 自动分箱 | 1天 | P3 |
| P5 发货清单 | 1天 | P2 |
| P6 标签打印集成 | 0.5天 | P1+P5 |
| P7 多规格 SKU | 1.5天 | P2 |
| **总计** | **~5天** | |
