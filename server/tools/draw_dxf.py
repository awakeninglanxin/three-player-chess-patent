# -*- coding: utf-8 -*-
"""把 DXF 完整画出来（线灰色、点红/蓝），并输出拓扑统计。"""
import collections
import json
import math
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
DOCS = os.path.join(HERE, "..", "..", "docs")
DATA = os.path.join(HERE, "..", "..", "docs", "_dxf_data.json")

d = json.load(open(DATA, encoding="utf-8"))
pts = [tuple(p) for p in d["points"]]
polys = [[tuple(v) for v in p] for p in d["polys"]]

plt.rcParams["font.sans-serif"] = ["SimHei", "Microsoft YaHei"]
plt.rcParams["axes.unicode_minus"] = False

fig, ax = plt.subplots(figsize=(12, 10))
for p in polys:
    xs = [v[0] for v in p]
    ys = [v[1] for v in p]
    ax.plot(xs, ys, "-", color="#888", lw=1.2)

# 点按到中心距离着色
cx0, cy0 = 0.0, 0.0
R = [math.hypot(p[0] - cx0, p[1] - cy0) for p in pts]
ax.scatter([p[0] for p in pts], [p[1] for p in pts], s=28, c=R, cmap="coolwarm",
           zorder=5, edgecolors="k", linewidths=0.4)

# 标注序号（前 40 个）
for i, p in enumerate(pts[:40]):
    ax.annotate(str(i), p, fontsize=6, color="#004488")

ax.set_aspect("equal")
ax.grid(True, alpha=0.25)
ax.set_title(f"DXF 原图：{len(pts)} 点 / {len(polys)} 线（点色=到中心距离）")
out1 = os.path.join(DOCS, "_dxf_全图.png")
plt.savefig(out1, dpi=110, bbox_inches="tight")
print("已生成", out1)

# ---------- 拓扑：点是否落在线上 ----------
def on_seg(p, a, b, tol=0.5):
    ax_, ay = a
    bx, by = b
    px, py = p
    dx, dy = bx - ax_, by - ay
    L2 = dx * dx + dy * dy
    if L2 == 0:
        return math.hypot(px - ax_, py - ay) < tol
    t = max(0.0, min(1.0, ((px - ax_) * dx + (py - ay) * dy) / L2))
    qx, qy = ax_ + t * dx, ay + t * dy
    return math.hypot(px - qx, py - qy) < tol


deg = collections.Counter()
for i, p in enumerate(pts):
    cnt = 0
    for poly in polys:
        for j in range(len(poly) - 1):
            if on_seg(p, poly[j], poly[j + 1], 0.8):
                cnt += 1
                break
    deg[cnt] += 1
print("\n每个点被多少条线穿过:", dict(sorted(deg.items())))

# ---------- 点按半径分层 ----------
print("\n=== 点按到中心距离分层 ===")
byr = collections.defaultdict(list)
for i, p in enumerate(pts):
    r = math.hypot(p[0], p[1])
    byr[round(r, 1)].append(i)
for r in sorted(byr):
    print(f"  r={r:>7.2f}: {len(byr[r]):>3d} 点  角度={sorted(round(math.degrees(math.atan2(pts[i][1], pts[i][0])) % 360, 1) for i in byr[r])[:14]}")
