# -*- coding: utf-8 -*-
"""自检工具：把模型点直接叠加到原图上，用原图六边形顶点做对齐基准。

这样能自己判断模型对不对，不用每次请老师看图。

做法：
  1. 从原图提取六边形 6 个顶点
  2. 建立「模型坐标 -> 原图像素」的最小二乘仿射变换（6 参数）
  3. 生成模型落子点，变换到原图坐标，画成红点叠上去
  4. 再叠加六边形轮廓，便于看边缘是否贴合
"""
import math
import os

import cv2
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DOCS = os.path.join(HERE, "..", "..", "docs")     # tools -> server -> 专利版根/docs
SRC = os.path.join(DOCS, "专利版棋盘原图 - 去掉字母数字 -红色区域是中间地带.jpg")
OUT = os.path.join(DOCS, "_overlay_自检_v2.png")

# ---------------------------------------------------------------- 1. 原图六边形顶点
img = cv2.imdecode(np.fromfile(SRC, dtype=np.uint8), cv2.IMREAD_COLOR)
h, w = img.shape[:2]
gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
_, bw = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY_INV)
closed = cv2.morphologyEx(bw, cv2.MORPH_CLOSE, np.ones((25, 25), np.uint8))
cnts, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
c = max(cnts, key=cv2.contourArea)
peri = cv2.arcLength(c, True)
ap = cv2.approxPolyDP(c, 0.02 * peri, True).reshape(-1, 2).astype(float)
cx, cy = ap[:, 0].mean(), ap[:, 1].mean()
src_hex = np.array(sorted(ap.tolist(), key=lambda p: math.atan2(p[1] - cy, p[0] - cx)))
print(f"原图 {w}x{h}，六边形顶点 {len(src_hex)} 个")

# ---------------------------------------------------------------- 2. 模型六边形顶点
A6 = 8.0
H6 = A6 * math.sqrt(3) / 2
C = (A6, 0.0)
model_hex = [(A6 / 2, H6), (3 * A6 / 2, H6), (2 * A6, 0.0),
             (3 * A6 / 2, -H6), (A6 / 2, -H6), (0.0, 0.0)]
# 模型六边形按极角排序，与原图顺序对齐
mcx = sum(p[0] for p in model_hex) / 6
mcy = sum(p[1] for p in model_hex) / 6
model_hex_s = np.array(sorted(model_hex, key=lambda p: math.atan2(p[1] - mcy, p[0] - mcx)))

# 原图顶点顺序：从 -121.6 度开始；模型从 90 度开始（左上）
# 用最小二乘拟合整体仿射（含旋转），不强行配对顺序：枚举循环位移取最优
best = None
for shift in range(6):
    m = np.roll(model_hex_s, shift, axis=0)
    # 解 [x y 1] * M = [X Y]
    A_ = np.hstack([m, np.ones((6, 1))])
    Mx, res_x, *_ = np.linalg.lstsq(A_, src_hex[:, 0], rcond=None)
    My, res_y, *_ = np.linalg.lstsq(A_, src_hex[:, 1], rcond=None)
    err = float(np.sum((A_ @ Mx - src_hex[:, 0]) ** 2) + np.sum((A_ @ My - src_hex[:, 1]) ** 2))
    if best is None or err < best[0]:
        best = (err, shift, Mx, My)
err, shift, Mx, My = best
rms = math.sqrt(err / 12)
print(f"最佳配对位移 {shift}，RMS 误差 {rms:.2f} px（六边形边长约 664 px）")


def to_px(pts):
    P = np.array(pts, dtype=float)
    A_ = np.hstack([P, np.ones((len(P), 1))])
    return np.stack([A_ @ Mx, A_ @ My], axis=1)


# ---------------------------------------------------------------- 3. 模型落子点
N_ROW, INSET = 7, 0.40
ROW_H = 0.764            # 行高（= 领地高 5.35 / 7 行，从原图绿点密度反推）


def unit(v):
    L = math.hypot(*v) or 1.0
    return (v[0] / L, v[1] / L)


HEXP = model_hex


def frame(army):
    # 底线所在六边形边的索引：魏=下(V4V5)->3  蜀=左上(V6V1)->5  吴=右上(V2V3)->1
    idx = {1: 3, 2: 5, 3: 1}[army]
    p1, p2 = HEXP[idx], HEXP[(idx + 1) % 6]
    o = ((p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2)
    ex = unit((p2[0] - p1[0], p2[1] - p1[1]))
    ey = unit((C[0] - o[0], C[1] - o[1]))
    return o, ex, ey


def to_world(army, x, y):
    o, ex, ey = frame(army)
    return (o[0] + x * ex[0] + y * ey[0], o[1] + x * ex[1] + y * ey[1])


pts = []
for army in (1, 2, 3):
    for k in range(N_ROW):
        shift = 0.0      # 正交网格：上下对齐（绿点显示原图交点是对齐的，不是交错）
        left = -A6 / 2 + INSET * k
        right = A6 / 2 - INSET * k
        i0 = math.ceil(left - shift - 1e-9)
        i1 = math.floor(right - shift + 1e-9)
        for i in range(i0, i1 + 1):
            pts.append(to_world(army, shift + i, k * ROW_H))
print(f"模型落子点 {len(pts)}")

# ---------------------------------------------------------------- 4. 叠加绘制
vis = img.copy()
pix = to_px(pts)
for (X, Y) in pix:
    if -50 < X < w + 50 and -50 < Y < h + 50:
        cv2.circle(vis, (int(round(X)), int(round(Y))), 7, (0, 0, 255), 2)

hexpix = to_px(model_hex_s)
cv2.polylines(vis, [hexpix.astype(np.int32)], True, (255, 0, 0), 3)

# 参数标签（同时用于强制刷新图片内容）
tag = f"rows={N_ROW} inset={INSET} rowh={ROW_H} idx=3/5/1 pts={len(pts)}"
cv2.rectangle(vis, (10, 10), (10 + 22 * len(tag) // 2, 46), (30, 30, 30), -1)
cv2.putText(vis, tag, (18, 36), cv2.FONT_HERSHEY_SIMPLEX, 0.62, (255, 255, 255), 2)

# ---- 从原图直接提取真实网格交点（绿色实心点），用于对照
ink = (gray < 175).astype(np.uint8) * 255
corners = cv2.goodFeaturesToTrack(ink, maxCorners=3000, qualityLevel=0.12,
                                  minDistance=26, blockSize=7)
n_corner = 0
if corners is not None:
    for cn in corners.reshape(-1, 2):
        x, y = int(cn[0]), int(cn[1])
        cv2.circle(vis, (x, y), 5, (0, 160, 0), -1)
        n_corner += 1
print(f"原图检出候选交点 {n_corner} 个（绿点，含文字干扰）")

# 六边形顶点标号
for i, (X, Y) in enumerate(hexpix):
    cv2.putText(vis, f"M{i}", (int(X) - 20, int(Y)), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 0, 0), 2)
for i, (X, Y) in enumerate(src_hex):
    cv2.putText(vis, f"S{i}", (int(X) - 20, int(Y) + 22), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 128, 0), 2)

cv2.imencode(".png", vis)[1].tofile(OUT)
print(f"已生成叠加自检图 {OUT}")

# 顺便报一下每行点数，便于核对密度
for army in (1, 2, 3):
    cnts_row = []
    for k in range(N_ROW):
        shift = 0.5 * k
        left = -A6 / 2 + INSET * k
        right = A6 / 2 - INSET * k
        n = math.floor(right - shift + 1e-9) - math.ceil(left - shift - 1e-9) + 1
        cnts_row.append(n)
    print(f"  方{army} 每行点数: {cnts_row}  合计 {sum(cnts_row)}")
