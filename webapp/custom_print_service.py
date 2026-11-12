"""
通用自定义打印服务 —— 开放任意元素格式的标签打印/预览。

与 label_service 的固定模板不同，本模块允许调用方直接描述标签上的每个元素
（文本 / 一维码 / 二维码 / PDF417 / DataMatrix / 图片 / 矩形 / 椭圆 / 圆 / 线），
元素参数直接对应 dtpweb SDK 的 draw_* 接口（坐标单位：毫米）。

行为与现有标签打印保持一致：异步任务 + SSE 逐张进度 + 可取消。
"""

from typing import Callable, Optional

from . import printer_service, task_service

# ============================================================
# 元素类型白名单
# ============================================================

ALLOWED_TYPES = {
    "text", "barcode", "qrcode", "pdf417", "dataMatrix",
    "image", "rect", "ellipse", "circle", "line",
}

# 元素类型 -> SDK 绘制方法名
_TYPE_TO_METHOD = {
    "text": "draw_text",
    "barcode": "draw_barcode",
    "qrcode": "draw_qrcode",
    "pdf417": "draw_pdf417",
    "dataMatrix": "draw_datamatrix",
    "image": "draw_image_data",
    "rect": "draw_rect",
    "ellipse": "draw_ellipse",
    "circle": "draw_circle",
    "line": "draw_line",
}

# 一维码的类型参数名映射：SDK draw_barcode 的条码类型参数为 type，
# 为避免与元素类型字段冲突，协议层使用 barcodeType，绘制时转换。
_BARCODE_TYPE_FIELD = "barcodeType"


def cancel_task(task_id: str) -> None:
    """取消指定打印任务（与 label_service 共享取消标志）"""
    from .label_service import cancel_task as _cancel

    _cancel(task_id)


def validate_elements(elements) -> list[dict]:
    """
    校验并规范化一页的元素列表。

    Raises:
        ValueError: 元素类型不在白名单或结构非法时
    """
    if not isinstance(elements, list) or len(elements) == 0:
        raise ValueError("页面元素不能为空")
    out = []
    for elem in elements:
        if not isinstance(elem, dict):
            raise ValueError(f"元素必须是对象: {elem!r}")
        etype = elem.get("type")
        if etype not in ALLOWED_TYPES:
            raise ValueError(
                f"不支持的元素类型: {etype!r}（允许: {', '.join(sorted(ALLOWED_TYPES))}）"
            )
        if etype == "barcode" and not elem.get("text"):
            raise ValueError("barcode 元素缺少 text 字段")
        out.append(dict(elem))
    return out


# ============================================================
# 绘制（非 JSON 模式，单位毫米，与 label_service 一致）
# ============================================================

def _draw_page(api, elements: list[dict]) -> None:
    """在已 start_job 的上下文内逐元素绘制。"""
    for elem in elements:
        etype = elem["type"]
        params = {k: v for k, v in elem.items() if k != "type"}
        method = getattr(api, _TYPE_TO_METHOD[etype])
        if etype == "barcode" and _BARCODE_TYPE_FIELD in params:
            # 一维码类型：barcodeType -> SDK 的 type 参数
            params["type"] = params.pop(_BARCODE_TYPE_FIELD)
        method(**params)


def _print_page(api, page_elements: list[dict], job: dict, copies: int, task_id: str) -> None:
    """打印一页标签（含 copies 份）。"""
    width = float(job.get("width") or 40.0)
    height = float(job.get("height") or 30.0)
    orientation = int(job.get("orientation") or 0)
    for _ in range(max(1, int(copies or 1))):
        if task_service.is_cancelled(task_id):
            return
        if not api.start_job(width, height, orientation=orientation):
            raise RuntimeError("创建打印任务失败")
        _draw_page(api, page_elements)
        if not api.commit_job(
            gapType=int(job.get("gapType", 2)),
            darkness=int(job.get("darkness", 5)),
            speed=int(job.get("speed", 2)),
        ):
            raise RuntimeError("提交打印任务失败")


def execute_print(
    task_id: str,
    pages: list[list[dict]],
    printer_name: str,
    job: dict,
    copies: int = 1,
    on_progress: Optional[Callable] = None,
) -> None:
    """
    批量自定义打印（在子线程中同步执行），与现有标签打印行为一致。

    Args:
        task_id: 任务唯一标识
        pages: 每页一个元素数组
        printer_name: 目标打印机名称
        job: 标签尺寸/打印参数 {width, height, orientation, gapType, darkness, speed}
        copies: 每页打印份数
        on_progress: 进度回调 fn(current, total, status, item, error)
    """
    task_service.run_batch(
        task_id, pages, printer_name,
        lambda api, page: _print_page(api, page, job, copies, task_id),
        on_progress,
    )


# ============================================================
# 预览（JSON 模式，与 label_service.generate_preview 一致）
# ============================================================

@printer_service.serialized
def generate_preview(
    pages: list[list[dict]],
    printer_name: str = "",
    job: Optional[dict] = None,
) -> str:
    """
    生成自定义标签的 PNG 预览图，返回 base64 Data URL（仅取第一页）。

    Args:
        pages: 每页一个元素数组
        printer_name: 目标打印机名称（可选，预览模式允许未连接打印机）
        job: 标签尺寸参数 {width, height, orientation}
    """
    api = printer_service.get_raw_api()
    job = job or {}

    # 预览模式尝试打开打印机（失败继续）
    if not api.is_printer_opened():
        printers = printer_service.get_printers()
        pn = printer_name or (printers[0]["name"] if printers else "")
        if pn:
            try:
                api.open_printer(name=pn)
            except Exception:  # noqa: BLE001
                pass

    job_info = {
        "jobWidth": float(job.get("width") or 40.0),
        "jobHeight": float(job.get("height") or 30.0),
        "orientation": int(job.get("orientation") or 0),
    }

    # JSON 模式元素直接透传。打印助手的 JSON 预览模式不支持 line/circle
    # 元素（会导致整张预览失败），预览时跳过；实际打印不受影响。
    _PREVIEW_UNSUPPORTED = {"line", "dashLine", "circle"}
    job_pages = []
    for page in pages:
        cleaned = []
        for elem in page:
            e = dict(elem)
            if e.get("type") in _PREVIEW_UNSUPPORTED:
                continue
            if e.get("type") == "barcode":
                e.pop(_BARCODE_TYPE_FIELD, None)
            cleaned.append(e)
        job_pages.append(cleaned)

    return printer_service.preview(job_info, job_pages)


# ============================================================
# 原始指令通道（高级：直接透传打印机指令）
# ============================================================

@printer_service.serialized
def print_raw(data: str, printer_name: str, copies: int = 1) -> bool:
    """直接发送原始打印指令（TSPL / CPCL / ESC-POS 等）。"""
    api = printer_service.get_raw_api()
    if not api.open_printer(name=printer_name):
        raise RuntimeError(f"无法连接打印机: {printer_name}")
    try:
        return bool(api.print_raw_data(data, printerName=printer_name, copies=copies))
    finally:
        api.close_printer()
