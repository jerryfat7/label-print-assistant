"""
通用自定义打印子应用 —— 运行在独立端口（默认 4051）。

由 tray_app.py 启动第二个 uvicorn 实例挂载本应用，
与 4050 端口的主应用（网页 / 闲鱼系统）互不干扰，共享同一打印机服务。

鉴权（预留）：可通过 create_custom_app(token=...) 传入令牌；
为空表示不鉴权（局域网信任环境），非空时所有请求需携带 X-API-Token 请求头。
"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .custom_print_routes import router


def create_custom_app(token: str = "") -> FastAPI:
    """创建通用打印子应用。"""
    app = FastAPI(
        title="标签打印助手 - 通用打印接口",
        description="任意自定义格式打印（文本/条码/二维码/图片/形状/原始指令）",
        version="1.0.0",
    )

    if token:
        @app.middleware("http")
        async def check_token(request: Request, call_next):
            provided = request.headers.get("X-API-Token", "")
            if provided != token:
                return JSONResponse({"error": "invalid token"}, status_code=401)
            return await call_next(request)

    app.include_router(router)
    return app
