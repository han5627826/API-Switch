#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
make_icon.py —— 生成本工具的图标 new_icon.ico（与 repack.py 同目录，存在则被打包进 exe）。
设计：蓝底白色「双向箭头」，寓意「切换」。改颜色/形状直接编辑 make()。
"""
from PIL import Image, ImageDraw
import os

def make(sz):
    img = Image.new('RGBA', (sz, sz), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    m, r = int(sz * 0.06), int(sz * 0.22)
    d.rounded_rectangle([m, m, sz - m, sz - m], radius=r, fill=(37, 99, 235, 255))
    lw = max(2, int(sz * 0.075))
    c1 = (255, 255, 255, 255)
    cy, x0, x1, ah = sz / 2, sz * 0.24, sz * 0.76, sz * 0.10
    y1 = cy - sz * 0.14
    d.line([x0, y1, x1, y1], fill=c1, width=lw)
    d.polygon([(x1, y1), (x1 - ah * 0.9, y1 - ah * 0.55), (x1 - ah * 0.9, y1 + ah * 0.55)], fill=c1)
    y2 = cy + sz * 0.14
    d.line([x1, y2, x0, y2], fill=c1, width=lw)
    d.polygon([(x0, y2), (x0 + ah * 0.9, y2 - ah * 0.55), (x0 + ah * 0.9, y2 + ah * 0.55)], fill=c1)
    return img

if __name__ == "__main__":
    base = make(256)
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "new_icon.ico")
    base.save(out, format="ICO", sizes=[(s, s) for s in (16, 24, 32, 48, 64, 128, 256)])
    base.save(os.path.join(os.path.dirname(out), "icon.png"))
    print("saved:", out)
