# -*- coding: utf-8 -*-
"""决定性验证：把 DXF 解析结果叠加到老师的原图上，检查是否重合。

若重合 -> 证明 DXF 与图片是同一套坐标（识别成功）；
   且以后可以用 DXF 作为权威坐标，图片仅作参考。
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

# ---------- 原图六边形顶点 ----------
_, bw = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY_INV)
closed = cv2.morphologyEx(bw, cv2.MORPH_CLOSE, np.ones((25, 25), np.uint8))
cnts, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
c = max(cnts, key=cv2.contourArea)
aps = {}
for eps in (0.01, 0.02, 0.03):
    ap = cv2.approxPolyDP(c, eps * cv2.arcLength(c, True), True).reshape(-1, 2).astype(float)
    aps[eps] = ap
src_hex = aps[0.02]
cx, cy = src_hex[:, 0].mean(), src_hex[:, 1].mean()
src_hex = np.array(sorted(src_hex.tolist(), key=lambda p: math.atan2(p[1] - cy, p[0] - cx)))
print(f"原图 {w}x{h}，六边形顶点 {len(src_hex)} 个")

# ---------- 模型六边形（DXF 坐标，平顶） ----------
A6 = 104.0439
H6 = A6 * math.sqrt(3) / 2
model_hex = [(A6, 0.0), (A6 / 2, H6), (-A6 / 2, H6), (-A6, 0.0), (-A6 / 2, -H6), (A6 / 2, -H6)]
model_hex = np.array(sorted(model_hex, key=lambda p: math.atan2(p[1], p[0])))

# 求仿射变换（枚举循环位移取最优）
best = None
for shift in range(6):
    m = np.roll(model_hex, shift, axis=0)
    A_ = np.hstack([m, np.ones((6, 1))])
    Mx, *_ = np.linalg.lstsq(A_, src_hex[:, 0], rcond=None)
    My, *_ = np.linalg.lstsq(A_, src_hex[:, 1], rcond=None)
    err = float(np.sum((A_ @ Mx - src_hex[:, 0]) ** 2) + np.sum((A_ @ My - src_hex[:, 1]) ** 2))
    if best is None or err < best[0]:
        best = (err, shift, Mx, My)
err, shift, Mx, My = best
rms = math.sqrt(err / 12)
print(f"最佳配对位移 {shift}，RMS = {rms:.2f} px（边长 {A6 / 104.04 * 664:.0f}px 量级）")


def to_px(x, y):
    return (Mx[0] * x + Mx[1] * y + Mx[2], My[0] * x + My[1] * y + My[2])


# ---------- 叠加绘制 ----------
vis = img.copy()

# 网格线（半透明青色）
ov = vis.copy()
for chain in LN:
    if len(chain) < 2:
        continue
    for i in range(len(chain) - 1):
        p1 = to_px(*P[chain[i]])
        p2 = to_px(*P[chain[i + 1]])
        cv2.line(ov, (int(round(p1[0])), int(round(p1[1]))),
                 (int(round(p2[0])), int(round(p2[1]))), (255, 160, 0), 3, cv2.LINE_AA)
vis = cv2.addWeighted(ov, 0.65, vis, 0.35, 0)

# 点（红色实心）
for k, (x, y) in P.items():
    X, Y = to_px(x, y)
    cv2.circle(vis, (int(round(X)), int(round(Y))), 6, (0, 0, 255), -1, cv2.LINE_AA)
    cv2.circle(vis, (int(round(X)), int(round(Y))), 6, (255, 255, 255), 1, cv2.LINE_AA)

# 六边形（蓝色）
for i in range(6):
    p1 = (int(round(src_hex[i][0])), int(round(src_hex[i][1])))
    p2 = (int(round(src_hex[(i + 1) % 6][0])), int(round(src_hex[(i + 1) % 6][1])))
    cv2.line(vis, p1, p2, (255, 0, 0), 2, cv2.LINE_AA)

outp = os.path.join(DOCS, "_DXF叠加验证.png")
cv2.imencode(".png", vis)[1].tofile(outp)
print(f"已生成 {outp}")

# 量化：每个 DXF 点到"原图最近墨迹"的距离（判断是否贴合原图网格）
ink = (gray < 175).astype(np.uint8)
dt = cv2.distanceTransform(1 - ink, cv2.DIST_L2, 5)
dlist = []
for k, (x, y) in P.items():
    X, Y = to_px(x, y)
    xi, yi = int(round(X)), int(round(Y))
    if 2 < xi < w - 2 and 2 < yi < h - 2:
        dlist.append(dt[yi, xi])
dlist = np.array(dlist)
print(f"\n135 点到原图最近墨线的距离：均值 {dlist.mean():.2f}px，中位 {np.median(dlist):.2f}px，"
      f"最大 {dlist.max():.2f}px")
print(f"  <3px 的点: {(dlist < 3).sum()}/135    <5px: {(dlist < 5).sum()}/135   <8px: {(dlist < 8).sum()}/135")
