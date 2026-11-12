"""
地址标签 API 路由 —— 收货地址解析、预览、打印、模板管理。
"""

import asyncio
import json
import threading
import uuid

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from . import address_parser
from . import label_service

router = APIRouter(prefix="/api/address", tags=["地址标签"])


# ---- 模型 ----

class ParseRequest(BaseModel):
    text: str = Field(..., description="多行收货地址文本")


class AddressItemOut(BaseModel):
    index: int
    name: str
    phone: str
    address: str
    fullAddress: str
    parseError: str | None = None


class ParseResponse(BaseModel):
    items: list[AddressItemOut]
    strategy: str


class PreviewRequest(BaseModel):
    name: str
    phone: str
    address: str
    printerName: str = ""
    template: dict | None = None


class PreviewResponse(BaseModel):
    image: str


class PrintRequest(BaseModel):
    items: list[dict] = Field(..., description="要打印的地址项列表")
    printerName: str
    template: dict | None = None
    copies: int = 1


class TemplateResponse(BaseModel):
    template: dict


# ---- SSE 进度队列（与 inventory 路由共用） ----

_progress_queues: dict[str, asyncio.Queue] = {}
_queues_lock = threading.Lock()


def _get_or_create_queue(task_id: str) -> asyncio.Queue:
    with _queues_lock:
        if task_id not in _progress_queues:
            _progress_queues[task_id] = asyncio.Queue()
        return _progress_queues[task_id]


def _remove_queue(task_id: str):
    with _queues_lock:
        _progress_queues.pop(task_id, None)


def _progress_item(task_id: str, current: int, total: int,
                   status: str, item: dict | None, error: str | None):
    q = _get_or_create_queue(task_id)
    try:
        q.put_nowait({
            "taskId": task_id, "current": current, "total": total,
            "status": status, "item": item, "error": error,
        })
    except asyncio.QueueFull:
        pass


# ---- 地址解析 ----

@router.post("/parse", response_model=ParseResponse)
def parse_addresses(req: ParseRequest):
    items = address_parser.parse_batch(req.text)
    return ParseResponse(
        items=[
            AddressItemOut(
                index=it.index, name=it.name, phone=it.phone,
                address=it.address, fullAddress=it.full_address,
                parseError=it.parse_error,
            )
            for it in items
        ],
        strategy=address_parser.get_strategy_name(),
    )


# ---- 预览 ----

@router.post("/preview", response_model=PreviewResponse)
def preview_label(req: PreviewRequest):
    try:
        img = label_service.generate_preview(
            name=req.name, phone=req.phone, address=req.address,
            printer_name=req.printerName,
            template_overrides=req.template,
            base_template="address",
        )
        return PreviewResponse(image=img or "")
    except Exception as e:
        raise HTTPException(500, f"预览生成失败: {e}")


# ---- 模板 ----

@router.get("/template/default", response_model=TemplateResponse)
def get_default_template():
    return TemplateResponse(
        template=label_service.get_default_template_dict("address")
    )


# ---- 打印 ----

@router.post("/print")
async def start_print(req: PrintRequest):
    task_id = str(uuid.uuid4())[:8]
    if not req.items:
        raise HTTPException(400, "没有要打印的数据")

    _get_or_create_queue(task_id)

    def on_progress(current, total, status, item, error):
        _progress_item(task_id, current, total, status, item, error)

    thread = threading.Thread(
        target=label_service.execute_print,
        args=(task_id, req.items, req.printerName, req.template, "address", req.copies),
        kwargs={"on_progress": on_progress},
        daemon=True,
    )
    thread.start()
    return {"taskId": task_id, "total": len(req.items)}


@router.get("/print/{task_id}/status")
async def print_status(task_id: str):
    q = _get_or_create_queue(task_id)

    async def event_stream():
        while True:
            try:
                msg = await asyncio.wait_for(q.get(), timeout=30)
                yield f"data: {json.dumps(msg, ensure_ascii=False)}\n\n"
                if msg["status"] in ("finished", "cancelled"):
                    break
            except asyncio.TimeoutError:
                yield f"data: {json.dumps({'status': 'timeout'})}\n\n"
                break
        _remove_queue(task_id)

    return StreamingResponse(
        event_stream(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/print/{task_id}/cancel")
def cancel_print(task_id: str):
    label_service.cancel_task(task_id)
    return {"status": "cancelled"}
