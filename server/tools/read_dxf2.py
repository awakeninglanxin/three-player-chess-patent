# -*- coding: utf-8 -*-
"""解析老师的 DXF：提取 135 个落子点 + 51 条网格线，分析几何结构。"""
import collections
import json
import math
import os

DXF = r"D:\AAA我的文件\中国三人象棋_专利版\三人版中国象棋.dxf"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "docs", "_dxf_data.json")


def read_dxf(path):
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        raw = f.read().splitlines()
    ents, i, n = [], 0, len(raw)
    while i < n:
        if raw[i].strip() == "ENTITIES":
            i += 1
            break
        i += 1
    cur = None
    while i < n - 1:
        code, val = raw[i].strip(), raw[i + 1].strip()
        i += 2
        if code == "0":
            if cur:
                ents.append(cur)
            if val == "ENDSEC":
                break
            cur = (val, [])
        elif cur is not None:
            cur[1].append((code, val))
    if cur:
        ents.append(cur)
    return ents


ents = read_dxf(DXF)
pts, polys, cur_poly = [], [], None
for t, attrs in ents:
    d = {c: v for c, v in attrs}
    if t == "POINT":
        pts.append((float(d["10"]), float(d["20"])))
    elif t == "POLYLINE":
        cur_poly = {"h": d.get("5", ""), "pts": []}
        polys.append(cur_poly)
    elif t == "VERTEX" and cur_poly is not None:
        cur_poly["pts"].append((float(d["10"]), float(d["20"])))

print(f"落子点 {len(pts)} 个   网格线 {len(polys)} 条   顶点数 {[len(p['pts']) for p in polys]}")

# ---------- 1. 点的整体范围与质心 ----------
xs = [p[0] for p in pts]
ys = [p[1] for p in pts]
print(f"\n点范围: x [{min(xs):.2f}, {max(xs):.2f}]   y [{min(ys):.2f}, {max(ys):.2f}]")
cx0, cy0 = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
print(f"包围盒中心 ({cx0:.2f},{cy0:.2f})")

# ---------- 2. 按角度聚类分组（三方） ----------
R = [math.hypot(p[0] - cx0, p[1] - cy0) for p in pts]
A = [math.degrees(math.atan2(p[1] - cy0, p[0] - cx0)) % 360 for p in pts]
print(f"\n到中心距离: min={min(R):.2f} max={max(R):.2f}")

# 按 120° 分三组的极角直方图
hist = collections.Counter(int(a // 10) * 10 for a in A)
print("极角直方图(10度):", dict(sorted(hist.items())))

# ---------- 3. 找最小重复间距（网格单元大小） ----------
srt = sorted(pts)
nn = []
for i, p in enumerate(pts):
    best = 1e9
    for j, q in enumerate(pts):
        if i == j:
            continue
        d = math.hypot(p[0] - q[0], p[1] - q[1])
        if d < best:
            best = d
    nn.append(best)
nn.sort()
print(f"\n最近邻距离: 最小={nn[0]:.3f} 中位={nn[len(nn) // 2]:.3f} 最大={nn[-1]:.3f}")

# 所有点对距离的直方图（找网格常数）
dists = []
for i in range(len(pts)):
    for j in range(i + 1, len(pts)):
        dists.append(math.hypot(pts[i][0] - pts[j][0], pts[i][1] - pts[j][1]))
dists.sort()
bins = collections.Counter(round(d * 2) / 2 for d in dists if d < 40)
print("点对距离直方图(0.5 分箱, <40):", dict(sorted(bins.items())))

# ---------- 4. 线的方向分布 ----------
print("\n=== 网格线方向分布 ===")
dirs = collections.Counter()
for p in polys:
    for i in range(len(p["pts"]) - 1):
        a, b = p["pts"][i], p["pts"][i + 1]
        ang = math.degrees(math.atan2(b[1] - a[1], b[0] - a[0])) % 180
        dirs[round(ang / 5) * 5] += 1
print("线段方向(5度分箱):", dict(sorted(dirs.items())))

# ---------- 5. 每条线的长度与位置 ----------
print("\n=== 线详情（前 25 条）===")
for i, p in enumerate(polys[:25]):
    v = p["pts"]
    L = sum(math.hypot(v[j + 1][0] - v[j][0], v[j + 1][1] - v[j][1]) for j in range(len(v) - 1))
    a0 = math.degrees(math.atan2(v[1][1] - v[0][1], v[1][0] - v[0][0])) % 180 if len(v) > 1 else 0
    print(f"  #{i:>2d} {len(v)}点 长{L:6.2f} 首向{a0:6.1f}°  {v[:4]}")

# 保存
os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, "w", encoding="utf-8") as f:
    json.dump({"points": pts, "polys": [p["pts"] for p in polys]}, f, ensure_ascii=False)
print(f"\n已保存 {OUT}")
