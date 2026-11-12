"""
标签打印助手 —— Web 服务入口

启动: python main.py
访问: http://localhost:4050/static/index.html
局域网: http://<本机IP>:4050/static/index.html
"""

import sys
import os

# 将上级目录加入 sys.path，以便导入同级的 dtpweb 包
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from webapp.api_routes import router as common_router
from webapp.address_routes import router as address_router
from webapp.inventory_routes import router as inventory_router

app = FastAPI(
    title="标签打印助手",
    description="德佟标签打印机 Web 打印服务",
    version="1.0.0",
)

# 挂载 API 路由
app.include_router(common_router)       # /api/health  /api/printers*
app.include_router(address_router)      # /api/address/*
app.include_router(inventory_router)    # /api/inventory-label/*

# 挂载静态文件（前端页面）
static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
app.mount("/static", StaticFiles(directory=static_dir, html=True), name="static")


@app.get("/")
def root():
    """根路径重定向到前端页面"""
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/static/index.html")


# ============================================================
# 直接运行入口
# ============================================================
if __name__ == "__main__":
    import uvicorn

    print("=" * 50)
    print("  🖨️  标签打印助手 启动中...")
    print("=" * 50)
    print(f"  本地访问: http://127.0.0.1:4050")
    print(f"  局域网访问: http://<本机IP>:4050")
    print("=" * 50)

    uvicorn.run(
        app,
        host="0.0.0.0",   # 绑定所有网卡，允许局域网访问
        port=4050,
        log_level="info",
    )
