# -*- coding: utf-8 -*-
"""一键打包 标签打印助手 为 Windows 托盘应用（单文件 exe）。

用法:
    python win_tray/build.py --arch x64      # 64 位
    python win_tray/build.py --arch x86      # 32 位（需在 32 位 Python 下运行）

说明:
    * 必须在项目根目录 label-print-assistant 中运行，保证相对路径正确。
    * 32 位打包请使用 32 位 Python 解释器运行本脚本（见 build_32.bat）。
    * 输出: dist\\LabelPrintAssistant-x64.exe / dist\\LabelPrintAssistant-x86.exe
"""
import argparse
import os
import subprocess
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WIN_TRAY = os.path.join(PROJECT_ROOT, "win_tray")
ICON_DIR = os.path.join(PROJECT_ROOT, "icon")

ICON_ICO = os.path.join(ICON_DIR, "app.ico")
ICON_PNG = os.path.join(ICON_DIR, "打印机.png")

HIDDEN_IMPORTS = [
    "uvicorn.logging",
    "uvicorn.loops.auto",
    "uvicorn.loops.asyncio",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.protocols.websockets.wsproto_impl",
    "uvicorn.lifespan.on",
    "pystray._win32",
]


def ensure_icon() -> None:
    """确保存在 app.ico（由 PNG 生成）。"""
    if os.path.exists(ICON_ICO):
        return
    print("[build] 未找到 app.ico，正在从 PNG 生成...")
    subprocess.check_call(
        [sys.executable, os.path.join(WIN_TRAY, "build_icons.py")]
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Build LabelPrintAssistant exe")
    parser.add_argument("--arch", choices=["x64", "x86"], default="x64")
    args = parser.parse_args()

    os.chdir(PROJECT_ROOT)
    ensure_icon()

    name = f"LabelPrintAssistant-{args.arch}"
    dist_dir = os.path.join(PROJECT_ROOT, "dist")

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--windowed",                      # 无控制台窗口
        "--name", name,
        "--icon", ICON_ICO,
        "--distpath", dist_dir,
        "--workpath", os.path.join(PROJECT_ROOT, "build"),
        "--specpath", WIN_TRAY,
        # Windows 下 --add-data 语法为 source;dest（分号分隔）。
        # source 用绝对路径，避免受 --specpath 影响；dest 为相对 _MEIPASS 的目录。
        "--add-data", f"{os.path.join(PROJECT_ROOT, 'webapp', 'static')};webapp/static",
        "--add-data", f"{os.path.join(PROJECT_ROOT, 'icon', 'app.ico')};icon",
    ]
    for imp in HIDDEN_IMPORTS:
        cmd += ["--hidden-import", imp]

    # cpca（地址解析）依赖运行时数据文件（省市区映射表）；
    # rthook 修复 pkg_resources 在 PyInstaller 下无法定位 cpca 数据目录的问题
    cmd += ["--collect-data", "cpca"]
    cmd += ["--runtime-hook", os.path.join(WIN_TRAY, "rthook_cpca.py")]

    cmd.append(os.path.join(WIN_TRAY, "tray_app.py"))

    print("[build] 打包命令:")
    print("   ", " ".join(cmd))
    print(f"[build] 当前解释器: {sys.executable} ({'32' if sys.maxsize < 2**32 else '64'} 位)")
    print(f"[build] 输出: {os.path.join(dist_dir, name + '.exe')}")

    return subprocess.call(cmd)


if __name__ == "__main__":
    sys.exit(main())
