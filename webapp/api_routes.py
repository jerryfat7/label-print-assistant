"""
公共 API 路由 —— 健康检查、打印机管理。
"""

from fastapi import APIRouter, HTTPException

from . import address_parser
from . import printer_service

router = APIRouter(prefix="/api", tags=["公共"])


# ---- 健康检查 ----

@router.get("/health")
def health():
    return {"status": "ok", "strategy": address_parser.get_strategy_name()}


# ---- 打印机管理 ----

@router.get("/printers")
def get_printers():
    """获取打印机列表"""
    try:
        return {"printers": printer_service.get_printers()}
    except Exception as e:
        return {"printers": [], "error": str(e)}


@router.post("/printers/refresh")
def refresh_printers():
    """刷新打印机"""
    try:
        return {"printers": printer_service.refresh_printers()}
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/printers/info")
def get_printer_info():
    """获取已连接打印机详情"""
    return printer_service.get_printer_info()
