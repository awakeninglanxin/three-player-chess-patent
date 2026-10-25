# -*- coding: utf-8 -*-
"""对原图整图 OCR，找出所有文字及其方位（确定三方圆点、三条地带的名称与位置）。"""
import json
import math
import os

import cv2
import numpy as np
import easyocr

HERE = os.path.dirname(os.path.abspath(__file__))
DOCS = os.path.join(HERE, "..", "..", "docs")
# 用带标注的原始版（文字最全）
CANDIDATES = [
    "专利版棋盘原图.jpg",
    "专利版棋盘原图 - 去掉字母数字 -红色区域是中间地带.jpg",
]

reader = easyocr.Reader(["ch_sim", "en"], gpu=False, verbose=False)

out = {}
for fn in CANDIDATES:
    p = os.path.join(DOCS, fn)
    if not os.path.exists(p):
        print(f"（跳过不存在的 {fn}）")
        continue
    img = cv2.imdecode(np.fromfile(p, dtype=np.uint8), cv2.IMREAD_COLOR)
    h, w = img.shape[:2]
    print(f"\n{'=' * 70}\n{fn}  ({w}x{h})\n{'=' * 70}")
    res = reader.readtext(img, detail=1, paragraph=False, text_threshold=0.5, low_text=0.25)
    items = []
    for bbox, text, conf in res:
        t = text.strip()
        if not t or conf < 0.3:
            continue
        xs = [q[0] for q in bbox]
        ys = [q[1] for q in bbox]
        cx, cy = sum(xs) / 4, sum(ys) / 4
        items.append((cx, cy, t, conf, max(xs) - min(xs), max(ys) - min(ys)))
    items.sort(key=lambda x: -x[5] * x[4])          # 面积大在前
    print(f"识别到 {len(items)} 条文本，按字块大小排序：")
    for cx, cy, t, conf, bw, bh in items[:40]:
        print(f"  「{t}」 conf={conf:.2f} 中心({cx:.0f},{cy:.0f}) 块 {bw:.0f}x{bh:.0f}")
    out[fn] = items

json.dump({k: [[float(a), float(b), t, float(c), float(d), float(e)] for a, b, t, c, d, e in v]
           for k, v in out.items()},
          open(os.path.join(DOCS, "_ocr_full.json"), "w", encoding="utf-8"), ensure_ascii=False)
print(f"\n已保存 {os.path.join(DOCS, '_ocr_full.json')}")
