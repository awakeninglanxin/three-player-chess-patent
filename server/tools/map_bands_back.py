# -*- coding: utf-8 -*-
"""把 DXF 的三条地带 + 三方圆点，按 60° 旋转映射回原图，看是否落在原图实际地带上。
   同时裁剪关键区域，便于老师肉眼核对。
"""
import json
import math
import os

import cv2
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DOCS = os.path.join(HERE, "..", "..", "docs")
SRC = os.path.join(DOCS, "专利版棋盘原图 - 去掉字母数字 -红色区域是中间地带.jpg")
data = json.load(open(os.path.join(DOCS, "_board_data.json"), encoding="utf-8"))
P = {k: (v["x"], v["y"]) for k, v in data["points"].items()}
LN = data["lines"]

img = cv2.imdecode(np.fromfile(SRC, dtype=np.uint8), cv2.IMREAD_COLOR)
h, w = img.shape[:2]
gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

_, bw = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY_INV)
closed = cv2.morphologyEx(bw, cv2.MORPH_CLOSE, np.ones((25, 25), np.uint8))
cnts, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
c = max(cnts, key=cv2.contourArea)
ap = cv2.approxPolyDP(c, 0.02 * cv2.arcLength(c, True), True).reshape(-1, 2).astype(float)
cx, cy = ap[:, 0].mean(), ap[:, 1].mean()
src_hex = np.array(sorted(ap.tolist(), key=lambda p: math.atan2(p[1] - cy, p[0] - cx)))

A6 = 104.0439
H6 = A6 * math.sqrt(3) / 2
base_hex = [(A6, 0.0), (A6 / 2, H6), (-A6 / 2, H6), (-A6, 0.0), (-A6 / 2, -H6), (A6 / 2, -H6)]
ROT = 60


def rotate(pts, deg):
    t = math.radians(deg)
    ct, st = math.cos(t), math.sin(t)
    return [(x * ct - y * st, x * st + y * ct) for x, y in pts]


mh = np.array(sorted(rotate(base_hex, ROT), key=lambda p: math.atan2(p[1], p[0])))
best = None
for shift in range(6):
    m = np.roll(mh, shift, axis=0)
    A_ = np.hstack([m, np.ones((6, 1))])
    Mx, *_ = np.linalg.lstsq(A_, src_hex[:, 0], rcond=None)
    My, *_ = np.linalg.lstsq(A_, src_hex[:, 1], rcond=None)
    err = float(np.sum((A_ @ Mx - src_hex[:, 0]) ** 2) + np.sum((A_ @ My - src_hex[:, 1]) ** 2))
    if best is None or err < best[0]:
        best = (err, shift, Mx, My)
err, shift, Mx, My = best


def to_px(p):
    x, y = rotate([p], ROT)[0]
    return (Mx[0] * x + Mx[1] * y + Mx[2], My[0] * x + My[1] * y + My[2])


# 三条地带（DXF 四边形）
BANDS = {
    "荆州(DXF:上方)": ["2-5-5", "2-5-9", "3-5-1", "3-5-5"],
    "赤壁(DXF:左下)": ["1-5-5", "1-5-9", "2-5-1", "2-5-5"],
    "祁山(DXF:右下)": ["3-5-5", "3-5-9", "1-5-1", "1-5-5"],
}
COLORS = {"荆州(DXF:上方)": (0, 200, 0), "赤壁(DXF:左下)": (200, 0, 0), "祁山(DXF:右下)": (0, 140, 255)}

vis = img.copy()
ov = vis.copy()
for name, keys in BANDS.items():
    pts = np.array([to_px(P[k]) for k in keys], dtype=np.int32)
    cv2.fillPoly(ov, [pts], COLORS[name])
    cv2.polylines(vis, [pts], True, COLORS[name], 3, cv2.LINE_AA)
vis = cv2.addWeighted(ov, 0.30, vis, 0.70, 0)

# 三方底线（粗线）
for name, keys, col in [("魏底线(DXF:下)", ["1-1-1", "1-1-9"], (255, 0, 0)),
                        ("蜀底线(DXF:左上)", ["2-1-1", "2-1-9"], (0, 0, 255)),
                        ("吴底线(DXF:右上)", ["3-1-1", "3-1-9"], (0, 160, 0))]:
    p1, p2 = to_px(P[keys[0]]), to_px(P[keys[1]])
    cv2.line(vis, (int(p1[0]), int(p1[1])), (int(p2[0]), int(p2[1])), col, 5, cv2.LINE_AA)

outp = os.path.join(DOCS, "_DXF地带方位_映射回原图.png")
cv2.imencode(".png", vis)[1].tofile(outp)
print("已生成", outp)

# 每条地带质心在原图的像素位置
print("\n=== DXF 三条地带质心 -> 原图上的位置 ===")
for name, keys in BANDS.items():
    cxp = sum(P[k][0] for k in keys) / 4
    cyp = sum(P[k][1] for k in keys) / 4
    X, Y = to_px((cxp, cyp))
    dx, dy = X - cx, Y - cy
    ang = math.degrees(math.atan2(-dy, dx)) % 360
    print(f"  {name}: 原图像素 ({X:.0f},{Y:.0f})  数学角 {ang:.1f}°  距中心 {math.hypot(dx, dy):.0f}px")

# 检测到的红色块
print(f"\n检测到的红色大块中心：(703,244)，即数学角 90.5°、距中心 325px")

# 裁剪关键区域
crops = {
    "_crop_红色块.png": (703, 244, 150),
    "_crop_DXF荆州落点.png": (None, None, 170),
    "_crop_DXF赤壁落点.png": (None, None, 170),
    "_crop_DXF祁山落点.png": (None, None, 170),
}
for name, keys in [("_crop_DXF荆州落点.png", BANDS["荆州(DXF:上方)"]),
                   ("_crop_DXF赤壁落点.png", BANDS["赤壁(DXF:左下)"]),
                   ("_crop_DXF祁山落点.png", BANDS["祁山(DXF:右下)"])]:
    cxp = sum(P[k][0] for k in keys) / 4
    cyp = sum(P[k][1] for k in keys) / 4
    X, Y = to_px((cxp, cyp))
    half = 170
    x1, y1 = max(0, int(X - half)), max(0, int(Y - half))
    x2, y2 = min(w, int(X + half)), min(h, int(Y + half))
    crop = img[y1:y2, x1:x2]
    big = cv2.resize(crop, None, fx=2.2, fy=2.2, interpolation=cv2.INTER_CUBIC)
    cv2.imencode(".png", big)[1].tofile(os.path.join(DOCS, name))
    print(f"已生成 {name}  ({x1},{y1})-({x2},{y2})")

# 红色块裁剪
x1, y1, x2, y2 = 703 - 170, max(0, 244 - 120), 703 + 170, 244 + 120
crop = img[y1:y2, x1:x2]
cv2.imencode(".png", cv2.resize(crop, None, fx=2.2, fy=2.2, interpolation=cv2.INTER_CUBIC))[1].tofile(
    os.path.join(DOCS, "_crop_红色块.png"))
print(f"已生成 _crop_红色块.png  ({x1},{y1})-({x2},{y2})")
