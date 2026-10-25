# -*- coding: utf-8 -*-
"""用原图的红色标注（三条中心地带）反推旋转关系，并定位「魏/蜀/吴」文字方位。"""
import json
import math
import os

import cv2
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DOCS = os.path.join(HERE, "..", "..", "docs")
SRC = os.path.join(DOCS, "专利版棋盘原图 - 去掉字母数字 -红色区域是中间地带.jpg")

img = cv2.imdecode(np.fromfile(SRC, dtype=np.uint8), cv2.IMREAD_COLOR)
h, w = img.shape[:2]
B, G, R = img[:, :, 0].astype(int), img[:, :, 1].astype(int), img[:, :, 2].astype(int)

# 六边形中心（复用检测）
gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
_, bw = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY_INV)
closed = cv2.morphologyEx(bw, cv2.MORPH_CLOSE, np.ones((25, 25), np.uint8))
cnts, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
c = max(cnts, key=cv2.contourArea)
ap = cv2.approxPolyDP(c, 0.02 * cv2.arcLength(c, True), True).reshape(-1, 2).astype(float)
cx, cy = ap[:, 0].mean(), ap[:, 1].mean()
R_apo = np.mean([math.hypot(p[0] - cx, p[1] - cy) for p in ap]) * math.cos(math.pi / 6)
print(f"中心 ({cx:.0f},{cy:.0f})  边心距 {R_apo:.0f}px")

# ---------- 1. 红色区域检测 ----------
red = ((R > 140) & (R - G > 45) & (R - B > 45)).astype(np.uint8)
red = cv2.morphologyEx(red, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
n, lab, stats, cent = cv2.connectedComponentsWithStats(red, 8)
print(f"\n红色连通域 {n - 1} 个（面积>2000 的列出）：")
blobs = []
for i in range(1, n):
    area = stats[i, cv2.CC_STAT_AREA]
    if area < 2000:
        continue
    cxi, cyi = cent[i]
    # 屏幕方向 -> 数学角（图像 y 向下，所以数学角 = atan2(-(dy), dx)）
    dx, dy = cxi - cx, cyi - cy
    math_ang = math.degrees(math.atan2(-dy, dx)) % 360
    rr = math.hypot(dx, dy)
    blobs.append((area, cxi, cyi, math_ang, rr))
    print(f"  面积 {area:>7d}  中心 ({cxi:6.0f},{cyi:6.0f})  数学角 {math_ang:6.1f}°  距中心 {rr:6.0f}px ({rr / R_apo * 90.1:.1f} 单位)")

# 按角度聚类成三条地带
blobs.sort(key=lambda b: b[3])
print("\n按角度聚类（间隔>40° 分新簇）：")
clusters = []
for b in blobs:
    if clusters and b[3] - clusters[-1][-1][3] < 40:
        clusters[-1].append(b)
    else:
        clusters.append([b])
for cl in clusters:
    tot = sum(x[0] for x in cl)
    angs = [x[3] for x in cl]
    print(f"  簇: 总面积 {tot:>7d}  角范围 {min(angs):.1f}° ~ {max(angs):.1f}°  ({len(cl)} 块)")

# ---------- 2. 蓝色三角区（老师标注的中心区）----------
blue = ((B > 150) & (B - R > 40) & (B - G > 40)).astype(np.uint8)
nb, labb, statsb, centb = cv2.connectedComponentsWithStats(blue, 8)
print(f"\n蓝色连通域 {nb - 1} 个（面积>1000）：")
for i in range(1, nb):
    if statsb[i, cv2.CC_STAT_AREA] < 1000:
        continue
    print(f"  面积 {statsb[i, cv2.CC_STAT_AREA]:>7d}  中心 ({centb[i][0]:6.0f},{centb[i][1]:6.0f})")

# ---------- 3. 文字位置探测（找「魏」「蜀」「吴」的可能位置：黑字）----------
ink = (gray < 120).astype(np.uint8)
n3, lab3, st3, ce3 = cv2.connectedComponentsWithStats(ink, 8)
cands = []
for i in range(1, n3):
    area = st3[i, cv2.CC_STAT_AREA]
    ww, hh = st3[i, cv2.CC_STAT_WIDTH], st3[i, cv2.CC_STAT_HEIGHT]
    if 300 < area < 3000 and 15 < hh < 60 and 15 < ww < 60 and 0.5 < ww / hh < 2.0:
        cxi, cyi = ce3[i]
        dx, dy = cxi - cx, cyi - cy
        r = math.hypot(dx, dy)
        if r < R_apo * 0.85:            # 排除边框上的装饰
            cands.append((cxi, cyi, math.degrees(math.atan2(-dy, dx)) % 360, r, area, ww, hh))
print(f"\n可能的文字块（中等大小连通域）{len(cands)} 个，按角度分布：")
bins = {}
for cxi, cyi, a, r, area, ww, hh in cands:
    k = int(a // 30) * 30
    bins.setdefault(k, []).append((cxi, cyi, r, ww, hh, area))
for k in sorted(bins):
    print(f"  {k:>3d}°~{k + 30:>3d}°: {len(bins[k]):>2d} 块")
    for cxi, cyi, r, ww, hh, area in bins[k][:4]:
        print(f"        ({cxi:5.0f},{cyi:5.0f}) r={r:5.0f} 尺寸 {ww}x{hh} 面积{area}")
