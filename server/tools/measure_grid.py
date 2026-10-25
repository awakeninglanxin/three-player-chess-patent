# -*- coding: utf-8 -*-
"""自检工具：从原图直接测量网格的行距与列距（用于校准行高/格宽）。

思路：对某一方区域做投影分析
  · 沿 x 投影 -> 竖直网格线的 x 坐标（间距 = 列距）
  · 沿 y 投影 -> 水平网格线的 y 坐标（间距 = 行高）
只取该方区域内、避开文字的位置。
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
ink = (gray < 170).astype(np.uint8)          # 墨迹（含网格线和文字）
print(f"图片 {w}x{h}")

# 六边形顶点（用来定位魏方区域）
bwc = cv2.morphologyEx(ink * 255, cv2.MORPH_CLOSE, np.ones((25, 25), np.uint8))
cnts, _ = cv2.findContours(bwc, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
c = max(cnts, key=cv2.contourArea)
ap = cv2.approxPolyDP(c, 0.02 * cv2.arcLength(c, True), True).reshape(-1, 2)
cx, cy = ap[:, 0].mean(), ap[:, 1].mean()
hexv = np.array(sorted(ap.tolist(), key=lambda p: math.atan2(p[1] - cy, p[0] - cx)))
V4, V5 = hexv[3], hexv[4]                     # 下边两端（魏方底线）
print(f"六边形中心 ({cx:.0f},{cy:.0f})  魏方底线 y≈{(V4[1]+V5[1])/2:.0f}")


def find_lines(profile, thr_ratio=0.45, min_gap=12):
    """在投影曲线上找峰值位置"""
    thr = profile.max() * thr_ratio
    idx = np.where(profile > thr)[0]
    if len(idx) == 0:
        return []
    groups, cur = [], [idx[0]]
    for i in idx[1:]:
        if i - cur[-1] <= 2:
            cur.append(i)
        else:
            groups.append(cur)
            cur = [i]
    groups.append(cur)
    pos = [int(np.mean(g)) for g in groups]
    # 合并过近的
    out = []
    for p in pos:
        if not out or p - out[-1] >= min_gap:
            out.append(p)
    return out


# ---------------------------------------------------------------- 魏方：列距
# 取魏方中部一带（底线往上 120~260 px），避开底部的「魏」字
y1, y2 = int((V4[1] + V5[1]) / 2) - 300, int((V4[1] + V5[1]) / 2) - 150
band = ink[y1:y2, :]
colprof = band.sum(axis=0).astype(float)
# 只保留底线范围内的 x
xa, xb = int(min(V4[0], V5[0])), int(max(V4[0], V5[0]))
colprof[:xa + 10] = 0
colprof[xb - 10:] = 0
cols = [p for p in find_lines(colprof, 0.35) if xa < p < xb]
print()
print("=== 魏方竖向网格线 x 坐标（列）===")
print(f"  {cols}")
if len(cols) >= 3:
    d = np.diff(cols)
    print(f"  相邻间距 {list(d)}")
    print(f"  列距均值 {d.mean():.1f} px  中位 {np.median(d):.1f} px")

# ---------------------------------------------------------------- 魏方：行高
# 取魏方偏左的一条竖带，避开「魏」字
xc = int((V4[0] + V5[0]) / 2)
band2 = ink[:, xc - 300:xc - 240]
rowprof = band2.sum(axis=1).astype(float)
ytop = int(cy)
rowprof[:ytop - 20] = 0
rowprof[int((V4[1] + V5[1]) / 2) + 10:] = 0
rows = find_lines(rowprof, 0.30)
print()
print("=== 魏方水平网格线 y 坐标（行）===")
print(f"  {rows}")
if len(rows) >= 3:
    d2 = np.diff(rows)
    print(f"  相邻间距 {list(d2)}")
    print(f"  行距均值 {d2.mean():.1f} px  中位 {np.median(d2):.1f} px")

if len(cols) >= 3 and len(rows) >= 3:
    cw = float(np.median(np.diff(cols)))
    rh = float(np.median(np.diff(rows)))
    print()
    print("=== 结论 ===")
    print(f"  列距 {cw:.1f} px   行距 {rh:.1f} px   行距/列距 = {rh / cw:.3f}")
    print(f"  sin60 = 0.866，sin30 = 0.5")
    print(f"  -> {'菱格投影 (行距 = 列距 x sin60)' if abs(rh / cw - 0.866) < 0.06 else '其它比例'}")
