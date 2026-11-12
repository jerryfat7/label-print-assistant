"""
打印机管理服务 —— 封装 DTP SDK 的打印机搜索、连接、参数读写等操作。

线程安全：使用 threading.Lock 保护 SDK 实例的并发访问。
"""

import threading
import time
from typing import Optional

from dtpweb import DTPWeb

# SDK 实例（模块级单例，需加锁访问）
_api = DTPWeb()
_lock = threading.Lock()
_initialized = False


def _ensure_initialized() -> None:
    """确保 SDK 已初始化（check_plugin）"""
    global _initialized
    if not _initialized:
        with _lock:
            if not _initialized:
                _api.check_plugin()
                time.sleep(3)  # 等待搜索设备
                _initialized = True


def get_printers() -> list[dict]:
    """获取所有可用的打印机列表"""
    _ensure_initialized()
    with _lock:
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
    _initialized = False
    return get_printers()


def open_printer(name: str, ip: str = '', ptype: int = 1) -> bool:
    """打开指定打印机"""
    _ensure_initialized()
    kwargs = {"name": name, "type": ptype}
    if ip:
        kwargs["ip"] = ip
    with _lock:
        return bool(_api.open_printer(**kwargs))


def close_printer() -> None:
    """关闭当前打印机"""
    with _lock:
        _api.close_printer()


def get_printer_info() -> dict:
    """获取已连接打印机的详细信息"""
    with _lock:
        return {
            "name": _api.get_printer_name() or "",
            "dpi": _api.get_printer_dpi() or 0,
            "darkness": _api.get_print_darkness() or 5,
            "speed": _api.get_print_speed() or 2,
            "gapType": _api.get_gap_type() or 2,
            "opened": bool(_api.is_printer_opened()),
        }


def get_raw_api() -> DTPWeb:
    """获取原始 DTPWeb 实例（供 label_service 使用）"""
    _ensure_initialized()
    return _api
