# -*- coding: utf-8 -*-
"""追踪魏方每条竖线的走向：拟合 x(y) 直线，找汇聚点；测环上交点分布。"""
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

BOTTOM = 1121
RA_PX = (1402 - 31) / 2 * math.cos(math.pi / 6)     # 边心距 593.7px
CX = (31 + 1402) / 2
CY = BOTTOM - RA_PX
GRID = RA_PX / 6.93                                  # 1 格 = 85.7px
print(f"中心=({CX:.0f},{CY:.0f})  R_apo={RA_PX:.0f}px  1格={GRID:.1f}px")


def scan_h(y, x0, x1):
    y = int(round(y))
    line = ink[y, max(0, int(x0)):min(w, int(x1))]
    hits = np.where(line > 0)[0] + int(x0)
    groups = []
    for x in hits:
        if groups and x - groups[-1][-1] <= 3:
            groups[-1].append(x)
        else:
            groups.append([x])
    return [sum(g) / len(g) for g in groups]


# ---------- 1. 多个 y 高度扫描竖线位置 ----------
print("\n=== 1) 竖线 x 位置随高度变化（魏方，避环线与文字）===")
levels = [745, 760, 855, 870, 960, 975, 1065]
tracks = {}
for y in levels:
    hh = scan_h(y, CX - 360, CX + 360)
    offs = [f"{(x - CX) / GRID:+.2f}" for x in hh]
    print(f"  y={y} (距底{(BOTTOM - y) / GRID:.2f}格): {len(hh)}条  x(格)={offs}")
    tracks[y] = hh

# ---------- 2. 匹配竖线求斜率 ----------
print("\n=== 2) 竖线斜率与汇聚点 ===")
# 用相邻两层（同一竖线）匹配：y=745 与 760 的对应关系
ys_sorted = sorted(tracks)
pairs = {}
for i in range(len(ys_sorted) - 1):
    y1, y2 = ys_sorted[i], ys_sorted[i + 1]
    if y2 - y1 > 40:
        continue
    for x1 in tracks[y1]:
        # 找 y2 中最近的
        if tracks[y2]:
            x2 = min(tracks[y2], key=lambda v: abs(v - x1))
            if abs(x2 - x1) < 25:
                slope = (x2 - x1) / (y2 - y1)          # dx/dy
                # 汇聚点：x(zero) = x1 - slope*(y1 - y_zero)
                y_at_c = x1 + slope * (CY - y1)        # 该线在中心高度处的 x
                pairs.setdefault(round((x1 - CX) / GRID), []).append(
                    (slope, y_at_c))

for key in sorted(pairs):
    ss = [p[0] for p in pairs[key]]
    yc = [p[1] for p in pairs[key]]
    print(f"  底线x≈{key:+d}格: 斜率均值={np.mean(ss):+.3f}  "
          f"在中心高度处 x={np.mean(yc):+.0f}px ({np.mean(yc) / GRID:+.2f}格)  n={len(ss)}")

# ---------- 3. 真实环位置重扫 ----------
print("\n=== 3) 真环（间距104px）上的交点分布 ===")
for d in (705, 809, 913, 1017):
    hh = scan_h(d, CX - 370, CX + 370)
    offs = [f"{(x - CX) / GRID:+.2f}" for x in hh]
    print(f"  y={d} (距底{(BOTTOM - d) / GRID:.2f}格): {len(hh)}点  x(格)={offs}")

# ---------- 4. 环内间距检查：中央三角区尺寸 ----------
print("\n=== 4) 中央三角区：中线向上扫描（从 cy 向上找第一条线）===")
colv = ink[0:int(CY), int(CX) - 1:int(CX) + 2].max(axis=1)
ys_up = np.where(colv > 0)[0]
# 从 cy 向上最近墨
above = [y for y in ys_up if y < CY - 30]
print(f"  中心上方最近墨线 y={max(above) if above else '无'}  距中心 {CY - max(above) if above else 0:.0f}px = {(CY - max(above)) / GRID:.2f}格")

# 左右方向（水平扫描中心线）
rowc = ink[int(CY), :]
xs_c = np.where(rowc > 0)[0]
left = [x for x in xs_c if x < CX - 30]
right = [x for x in xs_c if x > CX + 30]
if left and right:
    print(f"  中心左侧最近墨 x={max(left)} ({(CX - max(left)) / GRID:.2f}格)  "
          f"右侧 x={min(right)} ({(min(right) - CX) / GRID:.2f}格)")
