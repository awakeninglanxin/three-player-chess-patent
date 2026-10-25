# -*- coding: utf-8 -*-
"""自动校准：遍历「行高 / 内移量」参数，用命中率打分找最优。

打分原理：
  网格交点在图上表现为「十字」—— 4 个方向都有墨迹。
  对每个模型点，检查其周围 3~16 px 的 8 个方向是否有墨迹：
    · 上下左右 4 向都有  -> 命中交点（+2 分）
    · 仅 2 个对向方向有  -> 落在网格线上（+1 分）
    · 其他               -> 未对齐（0 分）
  命中率最高的参数即为最优。
"""
import math
import os

import cv2
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DOCS = os.path.join(HERE, "..", "..", "docs")
SRC = os.path.join(DOCS, "专利版棋盘原图 - 去掉字母数字 -红色区域是中间地带.jpg")

img = cv2.imdecode(np.fromfile(SRC, dtype=np.uint8), cv2.IMREAD_COLOR)
h, w = img.shape[:2]
gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
ink = (gray < 175).astype(np.uint8)

# 六边形顶点 + 仿射对齐
bwc = cv2.morphologyEx(ink * 255, cv2.MORPH_CLOSE, np.ones((25, 25), np.uint8))
cnts, _ = cv2.findContours(bwc, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
cc = max(cnts, key=cv2.contourArea)
ap = cv2.approxPolyDP(cc, 0.02 * cv2.arcLength(cc, True), True).reshape(-1, 2).astype(float)
cx0, cy0 = ap[:, 0].mean(), ap[:, 1].mean()
src_hex = np.array(sorted(ap.tolist(), key=lambda p: math.atan2(p[1] - cy0, p[0] - cx0)))

A6 = 8.0
H6 = A6 * math.sqrt(3) / 2
C = (A6, 0.0)
model_hex = [(A6 / 2, H6), (3 * A6 / 2, H6), (2 * A6, 0.0),
             (3 * A6 / 2, -H6), (A6 / 2, -H6), (0.0, 0.0)]
mh_s = np.array(sorted(model_hex, key=lambda p: math.atan2(p[1], p[0] - A6)))
best = None
for shift in range(6):
    m = np.roll(mh_s, shift, axis=0)
    A_ = np.hstack([m, np.ones((6, 1))])
    Mx, *_ = np.linalg.lstsq(A_, src_hex[:, 0], rcond=None)
    My, *_ = np.linalg.lstsq(A_, src_hex[:, 1], rcond=None)
    err = float(np.sum((A_ @ Mx - src_hex[:, 0]) ** 2) + np.sum((A_ @ My - src_hex[:, 1]) ** 2))
    if best is None or err < best[0]:
        best = (err, Mx, My)
_, Mx, My = best


def to_px(x, y):
    a = np.array([[x, y, 1.0]])
    return (float((a @ Mx).item()), float((a @ My).item()))


def unit(v):
    L = math.hypot(*v) or 1.0
    return (v[0] / L, v[1] / L)


HEXP = model_hex


def frame(army):
    idx = {1: 3, 2: 5, 3: 1}[army]
    p1, p2 = HEXP[idx], HEXP[(idx + 1) % 6]
    o = ((p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2)
    ex = unit((p2[0] - p1[0], p2[1] - p1[1]))
    ey = unit((C[0] - o[0], C[1] - o[1]))
    return o, ex, ey


def gen_points(n_row, inset, row_h):
    pts = []
    for army in (1, 2, 3):
        o, ex, ey = frame(army)
        for k in range(n_row):
            sh = 0.5 * k
            left = -A6 / 2 + inset * k
            right = A6 / 2 - inset * k
            for i in range(math.ceil(left - sh - 1e-9), math.floor(right - sh + 1e-9) + 1):
                x, y = sh + i, k * row_h
                pts.append((o[0] + x * ex[0] + y * ey[0], o[1] + x * ex[1] + y * ey[1]))
    return pts


DIRS8 = [(1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1)]

# 到最近墨迹的距离场（红点应落在墨迹上 -> 距离接近 0）
DIST = cv2.distanceTransform((1 - ink).astype(np.uint8), cv2.DIST_L2, 3)


def score_points(pts_px, tol=4.0):
    """返回 (贴合点数, 平均距离, 中位距离, 总数)

    贴合 = 到最近墨迹的距离 <= tol（像素）
    """
    ds = []
    for X, Y in pts_px:
        xi, yi = int(round(X)), int(round(Y))
        if 0 <= xi < w and 0 <= yi < h:
            ds.append(float(DIST[yi, xi]))
    if not ds:
        return 0, 999.0, 999.0, 0
    arr = np.array(ds)
    return int((arr <= tol).sum()), float(arr.mean()), float(np.median(arr)), len(arr)


print("=== 参数扫描（贴合率 = 到最近墨迹 <= 4px 的点占比）===")
print(f"{'行数':>4s} {'内移':>6s} {'行高':>6s} {'点数':>5s} {'贴合':>5s} {'均距':>7s} {'中位':>6s} {'贴合率':>7s}")
results = []
for n_row in (5, 6, 7):
    for inset in (0.30, 0.35, 0.40, 0.45, 0.50):
        for row_h in (0.75, 0.80, 0.866, 0.92, 1.0):
            pts = gen_points(n_row, inset, row_h)
            pts_px = [to_px(x, y) for x, y in pts]
            fit, mean_d, med_d, tot = score_points(pts_px)
            rate = fit / tot if tot else 0
            results.append((rate, mean_d, fit, tot, n_row, inset, row_h))
            print(f"{n_row:>4d} {inset:>6.2f} {row_h:>6.3f} {tot:>5d} "
                  f"{fit:>5d} {mean_d:>7.2f} {med_d:>6.2f} {rate * 100:>6.1f}%")

results.sort(key=lambda r: (-r[0], r[1]))
print()
print("=== 最优 10 组 ===")
for rate, mean_d, fit, tot, n_row, inset, row_h in results[:10]:
    print(f"  行数={n_row} 内移={inset:.2f} 行高={row_h:.3f}  点数={tot} "
          f"贴合={fit} 均距={mean_d:.2f}px  贴合率={rate * 100:.1f}%")
