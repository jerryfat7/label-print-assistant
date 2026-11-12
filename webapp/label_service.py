"""
标签渲染与打印服务 —— 负责 40×30mm 标签的版面绘制和打印调度。

模板参数（LabelTemplate）控制每个元素的字号和位置，
可通过 API 传入自定义参数覆盖默认值。
"""

from dataclasses import dataclass, field, asdict
from typing import Callable, Optional

from . import printer_service, task_service


# ============================================================
# 单个元素的排版参数
# ============================================================

@dataclass
class ElementStyle:
    """标签上单个文本元素的样式"""
    text: str = ""              # 显示文本（可为空，由数据填充）
    x: float = 0
    y: float = 0
    width: float = 40
    height: float = 5
    fontHeight: float = 3
    fontStyle: int = 0          # 0常规 1粗体 2斜体 3粗斜体
    horizontalAlignment: int = 1  # 0左 1中 2右 3拉伸
    verticalAlignment: int = 1


# ============================================================
# 整张标签的模板参数
# ============================================================

@dataclass
class LabelTemplate:
    """40×30mm 标签模板，每项可单独调整"""
    labelWidth: float = 40.0
    labelHeight: float = 30.0
    gapType: int = 2             # 纸张类型 2=间隙纸
    darkness: int = 5            # 打印浓度 0-14
    speed: int = 2               # 打印速度 0-4
    showPhoneIcon: bool = True   # 是否在 phone 前显示 ☎ 图标

    # 四个文字元素的样式
    title: ElementStyle = field(default_factory=lambda: ElementStyle(
        text="* 收货人 *", y=1, height=5, fontHeight=2.5,
        fontStyle=1, horizontalAlignment=1, verticalAlignment=1,
    ))
    name: ElementStyle = field(default_factory=lambda: ElementStyle(
        y=6, height=7, fontHeight=5.0,
        fontStyle=0, horizontalAlignment=1, verticalAlignment=1,
    ))
    phone: ElementStyle = field(default_factory=lambda: ElementStyle(
        y=14, height=5, fontHeight=3.2,
        fontStyle=0, horizontalAlignment=1, verticalAlignment=1,
    ))
    address: ElementStyle = field(default_factory=lambda: ElementStyle(
        y=20, height=7, fontHeight=3.2,
        fontStyle=0, horizontalAlignment=1, verticalAlignment=1,
    ))


# ---- 预定义模板 ----

# 地址标签（收货人）
ADDRESS_TEMPLATE = LabelTemplate()

# 兼容旧代码
DEFAULT_TEMPLATE = ADDRESS_TEMPLATE

# 箱子标签
BOX_TEMPLATE = LabelTemplate(
    labelWidth=40.0,
    labelHeight=30.0,
    showPhoneIcon=False,
    title=ElementStyle(
        text="箱子", y=1, height=5, fontHeight=3.0,
        fontStyle=1, horizontalAlignment=1, verticalAlignment=1,
    ),
    name=ElementStyle(
        y=7, height=12, fontHeight=5.5,
        fontStyle=1, horizontalAlignment=1, verticalAlignment=1,
    ),
    phone=ElementStyle(
        y=30, height=0, fontHeight=0,  # 无条码，隐藏
        fontStyle=0, horizontalAlignment=1, verticalAlignment=1,
    ),
    address=ElementStyle(
        y=20, height=8, fontHeight=2.8,
        fontStyle=0, horizontalAlignment=1, verticalAlignment=1,
    ),
)

# 商品标签
PRODUCT_TEMPLATE = LabelTemplate(
    labelWidth=40.0,
    labelHeight=30.0,
    showPhoneIcon=False,
    title=ElementStyle(
        text="", y=1, height=6, fontHeight=3.2,
        fontStyle=0, horizontalAlignment=1, verticalAlignment=1,
    ),
    name=ElementStyle(
        y=7, height=7, fontHeight=4.0,
        fontStyle=0, horizontalAlignment=1, verticalAlignment=1,
    ),
    phone=ElementStyle(
        y=15, height=5, fontHeight=2.8,
        fontStyle=0, horizontalAlignment=1, verticalAlignment=1,
    ),
    address=ElementStyle(
        y=21, height=7, fontHeight=2.5,
        fontStyle=0, horizontalAlignment=1, verticalAlignment=1,
    ),
)


# 模板注册表
TEMPLATES = {
    "address": ADDRESS_TEMPLATE,
    "box":     BOX_TEMPLATE,
    "product": PRODUCT_TEMPLATE,
}


# ============================================================
# 模板合并：用前端传入的 dict 覆盖默认值
# ============================================================

def _deep_update(base: dict, override: dict) -> dict:
    """递归合并两个 dict"""
    result = base.copy()
    for k, v in override.items():
        if isinstance(v, dict) and k in result and isinstance(result[k], dict):
            result[k] = _deep_update(result[k], v)
        else:
            result[k] = v
    return result


def build_template(
    overrides: Optional[dict] = None,
    base_template: str = "address",
) -> LabelTemplate:
    """
    根据前端传入的覆盖参数构建模板。

    Args:
        overrides: 覆盖参数 dict
        base_template: 基础模板名 ("address" | "box" | "product")
    """
    default_tmpl = TEMPLATES.get(base_template, ADDRESS_TEMPLATE)
    base = asdict(default_tmpl)
    if overrides:
        base = _deep_update(base, overrides)

    # 构建 LabelTemplate 实例
    tmpl = LabelTemplate(
        labelWidth=base.get("labelWidth", 40),
        labelHeight=base.get("labelHeight", 30),
        gapType=base.get("gapType", 2),
        darkness=base.get("darkness", 5),
        speed=base.get("speed", 2),
        showPhoneIcon=base.get("showPhoneIcon", True),
        title=ElementStyle(**base["title"]),
        name=ElementStyle(**base["name"]),
        phone=ElementStyle(**base["phone"]),
        address=ElementStyle(**base["address"]),
    )
    return tmpl


# ============================================================
# 绘制单张标签（核心逻辑）
# ============================================================

def _label_elements(name: str, phone: str, address: str, template: LabelTemplate) -> list[dict]:
    phone_text = f"☎ {phone}" if phone and template.showPhoneIcon else phone
    elements = []
    for style, text in [(template.title, template.title.text), (template.name, name),
                        (template.phone, phone_text), (template.address, address)]:
        # Empty text becomes "no content!" in the Linux helper. Hidden fields stay hidden.
        if not text or style.height <= 0 or style.fontHeight <= 0:
            continue
        element = asdict(style)
        element.update(type="text", text=text)
        elements.append(element)
    return elements


def _draw_label(api, name: str, phone: str, address: str, template: LabelTemplate,
                for_preview: bool = False) -> None:
    for element in _label_elements(name, phone, address, template):
        api.draw_text(**{key: value for key, value in element.items() if key != "type"})


# ============================================================
# 生成预览图
# ============================================================

@printer_service.serialized
def generate_preview(
    name: str,
    phone: str,
    address: str,
    printer_name: str = "",
    template_overrides: Optional[dict] = None,
    base_template: str = "address",
) -> str:
    """
    生成一张标签的 PNG 预览图，返回 base64 Data URL。

    Args:
        name/phone/address: 标签上三个数据字段
        printer_name: 目标打印机名称
        template_overrides: 模板覆盖参数
        base_template: 基础模板 ("address" | "box" | "product")
    """
    template = build_template(template_overrides, base_template)
    api = printer_service.get_raw_api()

    # 预览：尝试用第一个打印机打开，失败也继续（使用 JSON 模式不需要真实打印机）
    printers = printer_service.get_printers()
    if not api.is_printer_opened():
        pn = printer_name or (printers[0]["name"] if printers else "")
        if pn:
            try:
                api.open_printer(name=pn)
            except Exception:
                pass  # 预览模式允许未连接打印机

    elements = _label_elements(name, phone, address, template)

    return printer_service.preview(
        {"jobWidth": template.labelWidth, "jobHeight": template.labelHeight, "orientation": 0},
        [elements],
    )


# ============================================================
# 批量打印（同步，在子线程中调用）
# ============================================================

# 取消标志
def cancel_task(task_id: str) -> None:
    """取消指定打印任务"""
    task_service.cancel(task_id)


def _is_cancelled(task_id: str) -> bool:
    return task_service.is_cancelled(task_id)


def execute_print(
    task_id: str,
    items: list[dict],
    printer_name: str,
    template_overrides: Optional[dict] = None,
    base_template: str = "address",
    copies: int = 1,
    on_progress: Optional[Callable] = None,
) -> None:
    """
    批量打印（在子线程中同步执行）。

    Args:
        task_id: 任务唯一标识
        items: [{"name":..., "phone":..., "address":...}, ...]
        printer_name: 目标打印机名称
        template_overrides: 模板参数覆盖
        base_template: 基础模板名
        copies: 每张打印份数
        on_progress: 进度回调 fn(current, total, status, item, error)
    """
    template = build_template(template_overrides, base_template)
    task_service.run_batch(
        task_id, items, printer_name,
        lambda api, item: _print_single(api, item, template, copies, task_id),
        on_progress,
    )


def _print_single(api, item: dict, template: LabelTemplate, copies: int, task_id: str) -> None:
    """打印单张标签"""
    name = item.get("name", "") or ""
    phone = item.get("phone", "") or ""
    address = item.get("address", "") or ""

    for _ in range(max(1, copies)):
        if task_service.is_cancelled(task_id):
            return
        if not api.start_job(template.labelWidth, template.labelHeight):
            raise RuntimeError("创建打印任务失败")

        _draw_label(api, name, phone, address, template)

        if not api.commit_job(
            gapType=template.gapType,
            darkness=template.darkness,
            speed=template.speed,
        ):
            raise RuntimeError("提交打印任务失败")


# ============================================================
# 获取默认模板（供前端初始化）
# ============================================================

def get_default_template_dict(name: str = "address") -> dict:
    """返回指定模板的 dict 形式，供前端获取初始值"""
    tmpl = TEMPLATES.get(name, ADDRESS_TEMPLATE)
    return asdict(tmpl)
