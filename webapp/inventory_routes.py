"""
库存标签 API 路由 —— 箱子标签 / 商品标签的预览、打印、模板管理。

供闲鱼库存管理系统（电脑A）通过局域网 HTTP 调用。
"""

import asyncio
import json
import threading
import uuid

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from . import label_service
from .address_routes import _get_or_create_queue, _remove_queue, _progress_item

router = APIRouter(prefix="/api/inventory-label", tags=["库存标签"])


# ---- 模型 ----

class PreviewRequest(BaseModel):
    """库存标签预览请求。

    name  → 商品名称 / 箱子名称
    phone → SKU 编号 / 箱子条码
    address → 规格描述 / 箱子描述
    """
    name: str
    phone: str = ""
    address: str = ""
    labelType: str = Field("product", description="'box' | 'product'")
    printerName: str = ""
    template: dict | None = None


class PreviewResponse(BaseModel):
    image: str


class PrintItem(BaseModel):
    name: str
    phone: str = ""
    address: str = ""


class PrintRequest(BaseModel):
    items: list[PrintItem] = Field(..., description="要打印的标签项列表")
    labelType: str = Field("product", description="'box' | 'product'")
    printerName: str
    template: dict | None = None
    copies: int = 1


class TemplateResponse(BaseModel):
    template: dict


# ---- 预览 ----

@router.post("/preview", response_model=PreviewResponse)
def preview_label(req: PreviewRequest):
    base = req.labelType if req.labelType in ("box", "product") else "product"
    try:
        img = label_service.generate_preview(
            name=req.name, phone=req.phone, address=req.address,
            printer_name=req.printerName,
            template_overrides=req.template,
            base_template=base,
        )
        return PreviewResponse(image=img or "")
    except Exception as e:
        raise HTTPException(500, f"预览生成失败: {e}")


# ---- 模板 ----

@router.get("/template/{label_type}/default", response_model=TemplateResponse)
def get_default_template(label_type: str):
    base = label_type if label_type in ("box", "product") else "product"
    return TemplateResponse(
        template=label_service.get_default_template_dict(base)
    )


# ---- 打印 ----

@router.post("/print")
async def start_print(req: PrintRequest):
    task_id = str(uuid.uuid4())[:8]
    if not req.items:
        raise HTTPException(400, "没有要打印的数据")

    base = req.labelType if req.labelType in ("box", "product") else "product"
    _get_or_create_queue(task_id)

    items = [{"name": it.name, "phone": it.phone, "address": it.address}
             for it in req.items]

    def on_progress(current, total, status, item, error):
        _progress_item(task_id, current, total, status, item, error)

    thread = threading.Thread(
        target=label_service.execute_print,
        args=(task_id, items, req.printerName, req.template, base, req.copies),
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
