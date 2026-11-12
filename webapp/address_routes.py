"""
地址标签 API 路由 —— 收货地址解析、预览、打印、模板管理。
"""


from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from . import address_parser
from . import label_service, task_service

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
    copies: int = Field(1, ge=1, le=100)


class TemplateResponse(BaseModel):
    template: dict


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
    if not req.items:
        raise HTTPException(400, "没有要打印的数据")


    task_id = task_service.submit(
        label_service.execute_print, len(req.items),
        req.items, req.printerName, req.template, "address", req.copies,
    )
    return {"taskId": task_id, "total": len(req.items)}


@router.get("/print/{task_id}/status")
async def print_status(task_id: str):
    return task_service.stream(task_id)


@router.post("/print/{task_id}/cancel")
def cancel_print(task_id: str):
    label_service.cancel_task(task_id)
    return {"status": "cancelled"}
