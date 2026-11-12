"""
通用自定义打印 API 路由 —— 运行在独立端口（默认 4051）。

供第三方系统通过 HTTP 描述任意格式的标签元素进行打印 / 预览。
"""

import asyncio
import json
import threading
import uuid

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from . import custom_print_service
from . import printer_service
from .address_routes import _get_or_create_queue, _remove_queue, _progress_item

router = APIRouter(tags=["通用打印"])


# ---- 模型 ----

class JobInfo(BaseModel):
    """标签尺寸与打印参数（单位：毫米）"""
    width: float = 40.0
    height: float = 30.0
    orientation: int = 0
    gapType: int = 2        # 纸张类型 2=间隙纸
    darkness: int = 5       # 打印浓度 0-14
    speed: int = 2          # 打印速度 0-4


class PrintRequest(BaseModel):
    printerName: str
    pages: list[list[dict]] = Field(
        ..., description="每页一个元素数组，元素格式见 API 文档"
    )
    job: JobInfo = Field(default_factory=JobInfo)
    copies: int = Field(1, ge=1, le=100, description="每页打印份数")


class PreviewRequest(BaseModel):
    printerName: str = ""
    pages: list[list[dict]] = Field(..., description="每页一个元素数组")
    job: JobInfo = Field(default_factory=JobInfo)


class RawPrintRequest(BaseModel):
    printerName: str
    data: str = Field(..., description="原始打印指令（hex / base64 / 纯文本）")
    copies: int = Field(1, ge=1, le=100)


# ---- 基础 ----

@router.get("/health")
def health():
    return {"status": "ok", "service": "custom-print"}


@router.get("/printers")
def get_printers():
    """获取可用打印机列表"""
    try:
        return {"printers": printer_service.get_printers()}
    except Exception as e:  # noqa: BLE001
        return {"printers": [], "error": str(e)}


# ---- 预览 ----

@router.post("/preview")
def preview(req: PreviewRequest):
    """生成自定义标签预览图（base64 PNG，仅第一页）"""
    try:
        pages = [custom_print_service.validate_elements(p) for p in req.pages]
    except ValueError as e:
        raise HTTPException(400, str(e))
    try:
        img = custom_print_service.generate_preview(
            pages, req.printerName, req.job.model_dump()
        )
        return {"image": img or ""}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"预览生成失败: {e}")


# ---- 打印（异步任务 + SSE 进度，与现有行为一致） ----

@router.post("/print")
async def start_print(req: PrintRequest):
    """启动自定义打印任务，返回 taskId；进度通过 /print/{task_id}/status 订阅"""
    try:
        pages = [custom_print_service.validate_elements(p) for p in req.pages]
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not pages:
        raise HTTPException(400, "没有要打印的数据")

    task_id = str(uuid.uuid4())[:8]
    _get_or_create_queue(task_id)

    def on_progress(current, total, status, item, error):
        _progress_item(task_id, current, total, status, item, error)

    thread = threading.Thread(
        target=custom_print_service.execute_print,
        args=(task_id, pages, req.printerName, req.job.model_dump(), req.copies),
        kwargs={"on_progress": on_progress},
        daemon=True,
    )
    thread.start()
    return {"taskId": task_id, "total": len(pages)}


@router.get("/print/{task_id}/status")
async def print_status(task_id: str):
    """SSE 订阅打印任务进度"""
    q = _get_or_create_queue(task_id)

    async def event_stream():
        while True:
            try:
                msg = await asyncio.wait_for(q.get(), timeout=30)
                yield f"data: {json.dumps(msg, ensure_ascii=False)}\n\n"
                if msg["status"] in ("finished", "cancelled"):
                    break
            except asyncio.TimeoutError:
                yield "data: {\"status\": \"timeout\"}\n\n"
                break
        _remove_queue(task_id)

    return StreamingResponse(
        event_stream(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/print/{task_id}/cancel")
def cancel_print(task_id: str):
    """取消指定打印任务"""
    custom_print_service.cancel_task(task_id)
    return {"status": "cancelled"}


# ---- 原始指令通道 ----

@router.post("/print/raw")
def print_raw(req: RawPrintRequest):
    """直接发送原始打印指令（最大自由度）"""
    if not req.data:
        raise HTTPException(400, "打印数据不能为空")
    try:
        ok = custom_print_service.print_raw(req.data, req.printerName, req.copies)
        return {"status": "ok" if ok else "failed"}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"原始指令打印失败: {e}")
