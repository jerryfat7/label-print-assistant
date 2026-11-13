"""
打印机管理服务 —— 封装 DTP SDK 的打印机搜索、连接、参数读写等操作。

线程安全：使用 threading.Lock 保护 SDK 实例的并发访问。
"""

import threading
import math
from contextlib import contextmanager
from functools import wraps
from typing import Optional

from dtpweb import DTPWeb, utils
from .settings import Settings

# SDK 实例（模块级单例，需加锁访问）
_api = DTPWeb()
_lock = threading.RLock()
_initialized = False
_settings = Settings()
_vendor_http_request = utils.http_request


def _bounded_request(*args, **kwargs):
    # The wheel supplies millisecond defaults to urllib's timeout in seconds.
    kwargs["timeout"] = _settings.sdk_timeout
    return _vendor_http_request(*args, **kwargs)


utils.http_request = _bounded_request


def configure(settings: Settings) -> None:
    global _settings, _api, _initialized
    with _lock:
        _settings = settings
        _api = DTPWeb(ip=settings.sdk_host, fontName=settings.font_name)
        _initialized = False


def _ensure_initialized(force: bool = False) -> None:
    """确保 SDK 已初始化（check_plugin）"""
    global _initialized
    if force or not _initialized:
        _initialized = False
        if _settings.sdk_port:
            ok = _api.check_port(_settings.sdk_port, _settings.sdk_host)
        else:
            ok = _api.check_plugin(ip=_settings.sdk_host)
        if not ok:
            raise RuntimeError("打印助手不可用，请检查 dtpweb 服务及配置地址")
        _initialized = True


@contextmanager
def session():
    """Keep a complete preview or open/draw/commit/close operation indivisible."""
    global _initialized
    with _lock:
        _ensure_initialized(force=True)
        try:
            yield _api
        except Exception:
            _initialized = False
            raise


def serialized(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        with session():
            return function(*args, **kwargs)
    return wrapped


def get_printers() -> list[dict]:
    """获取所有可用的打印机列表"""
    with _lock:
        _ensure_initialized(force=True)
        items = _api.get_printers()
    result = []
    if items:
        for item in items:
            if isinstance(item, dict):
                result.append({
                    "name": item.get("name", ""),
                    "type": item.get("type", 1),
                    "ip": item.get("ip", ""),
                    "hostname": item.get("hostname", ""),
                })
    return result


def refresh_printers() -> list[dict]:
    """强制刷新打印机列表"""
    global _initialized
    with _lock:
        _initialized = False
        return get_printers()


def open_printer(name: str, ip: str = '', ptype: int = 1) -> bool:
    """打开指定打印机"""
    kwargs = {"name": name, "type": ptype}
    if ip:
        kwargs["ip"] = ip
    with _lock:
        _ensure_initialized(force=True)
        return bool(_api.open_printer(**kwargs))


def close_printer() -> None:
    """关闭当前打印机"""
    with _lock:
        _api.close_printer()


def _dpi_value(value, default: int = 0) -> int:
    """Normalize vendor numbers, axis objects, and full HTTP response objects."""
    if isinstance(value, dict) and "statusCode" in value:
        if value.get("statusCode") != 0:
            return default
        value = value.get("resultInfo")
    if isinstance(value, dict):
        value = value.get("dpiX", value.get("dpi", value.get("dpiY")))
    if isinstance(value, bool):
        return default
    try:
        number = float(value)
        return int(number) if math.isfinite(number) and number >= 1 else default
    except (TypeError, ValueError, OverflowError):
        return default


def get_printer_info() -> dict:
    """获取已连接打印机的详细信息"""
    with _lock:
        _ensure_initialized()
        return {
            "name": _api.get_printer_name() or "",
            "dpi": _dpi_value(_api.get_printer_dpi()),
            "darkness": _api.get_print_darkness() or 5,
            "speed": _api.get_print_speed() or 2,
            "gapType": _api.get_gap_type() or 2,
            "opened": bool(_api.is_printer_opened()),
        }


def get_raw_api() -> DTPWeb:
    """获取原始 DTPWeb 实例（供 label_service 使用）"""
    with _lock:
        _ensure_initialized()
        return _api


def status() -> dict:
    try:
        with _lock:
            _ensure_initialized(force=True)
            return {"ready": True, "host": _settings.sdk_host,
                    "port": _api.get_port(None)}
    except Exception as exc:
        return {"ready": False, "error": str(exc), "host": _settings.sdk_host}


def preview(job_info: dict, pages: list[list[dict]]) -> str:
    """An empty printerName crashes Linux 2.5 when no USB printer is attached."""
    info = {"printerDPI": 203, "printerWidth": 384}
    if _api.is_printer_opened():
        name = _api.get_printer_name()
        if name:
            info["printerName"] = name
        info["printerDPI"] = _dpi_value(_api.get_printer_dpi(), default=203)
    normalized = []
    for page in pages:
        elements = []
        for item in page:
            element = dict(item)
            if element.get("type") == "text":
                element.setdefault("fontName", _api.get_font_name(None))
            elements.append(element)
        normalized.append(elements)
    result = _api.print(0x0082, printerInfo=info, jobInfo=job_info, jobPages=normalized)
    if isinstance(result, dict) and result.get("previewData"):
        data = result["previewData"][0]
        image = data if isinstance(data, str) else "".join(data)
        if image:
            return image
    raise RuntimeError("打印助手未生成预览图片，请检查助手状态和标签参数")
