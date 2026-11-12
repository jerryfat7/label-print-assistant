# -*- coding: utf-8 -*-
"""从 icon/打印机.png 生成多尺寸 app.ico（构建时使用）。

用法:
    python win_tray/build_icons.py
输出:
    icon/app.ico   (16,24,32,48,64,128,256 多尺寸)
"""
import os
import sys

from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "icon", "打印机.png")
OUT = os.path.join(ROOT, "icon", "app.ico")

SIZES = [16, 24, 32, 48, 64, 128, 256]


def main() -> None:
    if not os.path.exists(SRC):
        print(f"[build_icons] 未找到源图片: {SRC}")
        sys.exit(1)

    img = Image.open(SRC).convert("RGBA")
    print(f"[build_icons] 源图片: {img.size} {img.mode}")

    img.save(OUT, format="ICO", sizes=[(s, s) for s in SIZES])
    print(f"[build_icons] 已生成: {OUT}")


if __name__ == "__main__":
    main()
