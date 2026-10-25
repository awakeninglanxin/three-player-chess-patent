# -*- coding: utf-8 -*-
"""径向测量：验证「极坐标网格」假设。

假设：每方 = 一个 60° 扇区，
  - 竖线 = 从六边形中心发出的放射线（9 条/方，含边界 2 条）
  - 横线 = 以六边形中心为圆心的同心圆弧
若假设成立，则：
  1) 沿任一方向从中心向外扫描，墨线半径位置应与方向无关（同一行 r 相同）
  2) 沿固定半径转一圈，墨线角度应正好落在放射线角度上
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

# ---------- 六边形中心（复用顶点检测） ----------
_, bw = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY_INV)
closed = cv2.morphologyEx(bw, cv2.MORPH_CLOSE, np.ones((25, 25), np.uint8))
cnts, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
c = max(cnts, key=cv2.contourArea)
peri = cv2.arcLength(c, True)
ap = cv2.approxPolyDP(c, 0.02 * peri, True).reshape(-1, 2).astype(float)
cx, cy = ap[:, 0].mean(), ap[:, 1].mean()
rs = [math.hypot(p[0] - cx, p[1] - cy) for p in ap]
print(f"图 {w}x{h}  中心=({cx:.0f},{cy:.0f})  顶点半径均值={np.mean(rs):.1f}px  边心距≈{np.mean(rs)*math.cos(math.pi/6):.1f}px")


def ink_along(theta_deg, r0, r1, step=1.0):
    """沿角度 theta（数学角，逆时针、y 向上）从 r0 到 r1 采样，返回 (r, ink) 列表"""
    t = math.radians(theta_deg)
    dx, dy = math.cos(t), -math.sin(t)          # 图像 y 向下
    out = []
    r = r0
    while r <= r1:
        x, y = cx + dx * r, cy + dy * r
        xi, yi = int(round(x)), int(round(y))
        v = 0
        if 0 <= yi < h and 0 <= xi < w:
            v = ink[max(0, yi - 1):yi + 2, max(0, xi - 1):xi + 2].max()
        out.append((r, v))
        r += step
    return out


def find_lines(samples, min_gap=12):
    """把 ink 采样聚成线位置（连续墨段的中心）"""
    lines, run = [], []
    for r, v in samples:
        if v:
            run.append(r)
        else:
            if run:
                lines.append(sum(run) / len(run))
                run = []
    if run:
        lines.append(sum(run) / len(run))
    # 合并过近的
    merged = []
    for L in lines:
        if merged and L - merged[-1] < min_gap:
            merged[-1] = (merged[-1] + L) / 2
        else:
            merged.append(L)
    return merged


# ---------- 1. 魏方（下方扇区 240~300 度）沿多个角度找横线半径 ----------
print("\n=== 1) 魏方各角度的横线半径（若为同心圆弧，各行 r 应与角度无关）===")
angles = [262, 270, 278]          # 避开 7.5° 整数倍的角度是找不到的——放射线在 240+7.5k
# 放射线角度：240, 247.5, 255, 262.5, 270, 277.5, 285, 292.5, 300
# 所以采样角取 266, 270, 274（避开放射线）
for th in (266, 270, 274):
    rows = find_lines(ink_along(th, 30, 700))
    print(f"  theta={th:>3d}°: " + "  ".join(f"{r:.0f}" for r in rows))

# ---------- 2. 荆州地带（上方 90 度）也测一遍 ----------
print("\n=== 2) 荆州地带（theta=90°）横线半径（地带内无网格，应几乎没有线）===")
rows = find_lines(ink_along(90, 30, 700))
print("   " + "  ".join(f"{r:.0f}" for r in rows) if rows else "   无")

# ---------- 3. 固定半径转一圈，找放射线角度 ----------
print("\n=== 3) 固定半径扫一圈，墨迹集中的角度（应为放射线，间隔 7.5°）===")
for R in (300, 450, 600):
    hits = []
    for i in range(0, 3600):
        th = i * 0.1
        t = math.radians(th)
        x, y = int(round(cx + math.cos(t) * R)), int(round(cy - math.sin(t) * R))
        if 0 <= y < h and 0 <= x < w and ink[max(0, y - 1):y + 2, max(0, x - 1):x + 2].max():
            hits.append(th)
    # 聚类
    groups, cur = [], [hits[0]] if hits else []
    for a in hits[1:]:
        if a - cur[-1] <= 1.5:
            cur.append(a)
        else:
            groups.append(sum(cur) / len(cur))
            cur = [a]
    if cur:
        groups.append(sum(cur) / len(cur))
    # 处理 0/360 环绕
    if len(groups) > 1 and groups[0] < 1 and groups[-1] > 359:
        groups[0] = (groups[0] + groups[-1] - 360) / 2
        groups.pop()
    print(f"  R={R}px: {len(groups)} 条  " + "  ".join(f"{g:.1f}" for g in groups))
