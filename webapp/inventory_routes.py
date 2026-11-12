"""
库存标签 API 路由 —— 箱子标签 / 商品标签的预览、打印、模板管理。

供闲鱼库存管理系统（电脑A）通过局域网 HTTP 调用。
"""


from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from . import label_service
from . import task_service

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
    copies: int = Field(1, ge=1, le=100)


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
    if not req.items:
        raise HTTPException(400, "没有要打印的数据")

    base = req.labelType if req.labelType in ("box", "product") else "product"

    items = [{"name": it.name, "phone": it.phone, "address": it.address}
             for it in req.items]
    task_id = task_service.submit(
        label_service.execute_print, len(items),
        items, req.printerName, req.template, base, req.copies,
    )
    return {"taskId": task_id, "total": len(req.items)}


@router.get("/print/{task_id}/status")
async def print_status(task_id: str):
    return task_service.stream(task_id)


@router.post("/print/{task_id}/cancel")
def cancel_print(task_id: str):
    label_service.cancel_task(task_id)
    return {"status": "cancelled"}
