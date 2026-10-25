# -*- coding: utf-8 -*-
"""用 easyocr（本地中文模型）识别三处地带的文字。"""
import os
import sys

import cv2
import numpy as np
import easyocr

HERE = os.path.dirname(os.path.abspath(__file__))
DOCS = os.path.join(HERE, "..", "..", "docs")

reader = easyocr.Reader(["ch_sim", "en"], gpu=False, verbose=False)
print("easyocr 就绪\n")

files = [
    ("DXF荆州(上方)  -> 原图208.7°", "_crop_DXF荆州落点.png"),
    ("DXF赤壁(左下)  -> 原图90.1°", "_crop_DXF赤壁落点.png"),
    ("DXF祁山(右下)  -> 原图332.5°", "_crop_DXF祁山落点.png"),
    ("原图红色标注处", "_crop_红色块.png"),
]
for label, f in files:
    p = os.path.join(DOCS, f)
    if not os.path.exists(p):
        print(f"### {label}: 文件不存在 {f}")
        continue
    img = cv2.imdecode(np.fromfile(p, dtype=np.uint8), cv2.IMREAD_COLOR)
    # 放大 1.5 倍利于识别
    img = cv2.resize(img, None, fx=1.5, fy=1.5, interpolation=cv2.INTER_CUBIC)
    res = reader.readtext(img, detail=1, paragraph=False)
    print(f"### {label}  ({f})")
    if not res:
        print("    （无文本）")
    for bbox, text, conf in res:
        if conf < 0.25 or not text.strip():
            continue
        cx = sum(p[0] for p in bbox) / 4
        cy = sum(p[1] for p in bbox) / 4
        print(f"    「{text}」 conf={conf:.2f}  位置({cx:.0f},{cy:.0f})")
    print()
