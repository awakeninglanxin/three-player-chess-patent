# -*- coding: utf-8 -*-
"""精确测量：验证「放射线 × 同心六边形环」模型。

模型：
  - 同心正六边形环 k=1..K（与外六边形同向相似），第 K 环 = 棋盘外边界
  - 魏方（下扇区）竖线 = 过中心的放射线，9 条（240°~300°，间隔 7.5°）
  - 落子点 = 放射线 × 环 的交点；底边 9 点 = 9 条放射线与第 K 环下边的交点
预测（若 K=5）：
  - 底边交点 x 偏移 = tan(7.5°·|j|)·R_apo ∝ {0, .1317, .2679, .4142, .5774}
  - 环 k 的下边 y = C_y + k·(R_apo/K)
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

# ---------- 精确定中心：拟合上/下水平边 ----------
# 下水平边：在 x=706 附近找最下方的长横线
col = ink[:, 690:722].max(axis=1)          # 中间竖条
rows_with_ink = np.where(col > 0)[0]
# 底边 = 竖直扫描到的最下墨线（排除噪点：要求连续 30px 以上宽的墨）
def long_row_runs(y):
    row = ink[y]
    return row.sum()

best_bottom = 0
for y in range(h - 1, h // 2, -1):
    if long_row_runs(y) > w * 0.45:
        best_bottom = y
        break
best_top = 0
for y in range(0, h // 2):
    if long_row_runs(y) > w * 0.45:
        best_top = y
        break
cy = (best_top + best_bottom) / 2
print(f"上水平边 y={best_top}  下水平边 y={best_bottom}  ->  cy={cy:.1f}  边心距 R_apo={(best_bottom-best_top)/2:.1f}px")

# 左右顶点：在中线上找最左/最右墨
row = ink[int(cy)]
xs = np.where(row > 0)[0]
cx = (xs.min() + xs.max()) / 2
print(f"中线最左 x={xs.min()}  最右 x={xs.max()}  ->  cx={cx:.1f}  顶点半径={(xs.max()-xs.min())/2:.1f}px")

RA = (best_bottom - best_top) / 2            # 边心距（px）
RT = RA / math.cos(math.pi / 6)              # 顶点半径


def scan_h(y, x0, x1):
    """水平扫描：返回墨线段的中心 x 列表"""
    y = int(round(y))
    line = ink[y, max(0, int(x0)):int(x1)]
    hits = np.where(line > 0)[0] + int(x0)
    groups = []
    for x in hits:
        if groups and x - groups[-1][-1] <= 2:
            groups[-1].append(x)
        else:
            groups.append([x])
    return [sum(g) / len(g) for g in groups]


def scan_v(x, y0, y1):
    x = int(round(x))
    colv = ink[max(0, int(y0)):int(y1), x]
    hits = np.where(colv > 0)[0] + int(y0)
    groups = []
    for y in hits:
        if groups and y - groups[-1][-1] <= 2:
            groups[-1].append(y)
        else:
            groups.append([y])
    return [sum(g) / len(g) for g in groups]


# ---------- 1. 底边上的放射线交点 ----------
print("\n=== 1) 底边上方 4px 扫描：放射线交点 x（应为 tan 分布，中密边疏）===")
xs_hits = scan_h(best_bottom - 4, cx - RA * 0.62, cx + RA * 0.62)
offs = [(x - cx) / RA for x in xs_hits]      # 以边心距为单位
print("  x 偏移(格, R_apo=6.93):", [f"{o * 6.93:.2f}" for o in offs])
print("  理论 tan(7.5°j)·6.93:   [±4.00, ±2.87, ±1.86, ±0.91, 0]")
print("  相对误差:", [f"{abs(abs(o) - t) / t * 100:.0f}%" for o, t in
                 zip(offs, [.5774, .4142, .2679, .1317, 0, .1317, .2679, .4142, .5774])])

# ---------- 2. 中线竖直扫描：环位置 ----------
print("\n=== 2) 中线（x=cx）竖直扫描：横线 y 位置（环的下边水平段）===")
ys = scan_v(cx - 2, cy + 20, best_bottom - 2)     # x=cx 有正中放射线，往左偏 2px 避开
ys2 = scan_v(cx + 60, cy + 20, best_bottom - 2)   # 再取 x=cx+60 一条对照
print(f"  x=cx-2 : y-底部 = {[f'{best_bottom - v:.0f}' for v in ys]}")
print(f"  x=cx+60: y-底部 = {[f'{best_bottom - v:.0f}' for v in ys2]}")
pred = [f"{(best_bottom - cy) * (1 - k / 5):.0f}" for k in range(1, 6)]
print(f"  若 K=5 均匀: 环 k 距底边 = {pred}")

# ---------- 3. 各环水平段上的放射线交点（验证 tan 分布比例） ----------
print("\n=== 3) 各环上的放射线 x 偏移（应随环 k 线性缩小：x ∝ k·tan(7.5°j)）===")
for k in (2, 3, 4):
    yk = best_bottom - RA * (1 - k / 5) - 4
    hh = scan_h(yk, cx - RA * 0.62 * k / 5 - 30, cx + RA * 0.62 * k / 5 + 30)
    offs_k = [(x - cx) / RA * 6.93 for x in hh]
    print(f"  环{k}: y={yk:.0f}  x偏移(格) = {[f'{o:.2f}' for o in offs_k]}")
