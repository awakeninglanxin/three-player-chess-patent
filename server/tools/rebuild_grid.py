# -*- coding: utf-8 -*-
"""重建完整网格：把落在每条折线段上的所有落子点插入，得到被落子点分割的线网。"""
import collections
import json
import math
import os

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "..", "docs", "_dxf_data.json")
d = json.load(open(DATA, encoding="utf-8"))
pts = [tuple(p) for p in d["points"]]
polys = [[tuple(v) for v in p] for p in d["polys"]]

TOL = 0.6


def seg_param(p, a, b):
    """p 在 a-b 段上的参数 t（0..1）与垂直距离；不在段内返回 None"""
    dx, dy = b[0] - a[0], b[1] - a[1]
    L2 = dx * dx + dy * dy
    if L2 < 1e-9:
        return None
    t = ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / L2
    qx, qy = a[0] + t * dx, a[1] + t * dy
    dist = math.hypot(p[0] - qx, p[1] - qy)
    if dist < TOL and -1e-6 <= t <= 1 + 1e-6:
        return t, dist
    return None


# 每条 POLYLINE 变成一串"节点"（顶点 + 段中落子点）
segs_pts = []          # [ (poly_idx, [ (t_global, point) ... ] ) ]
used = collections.Counter()
for pi, poly in enumerate(polys):
    nodes = []
    for j in range(len(poly) - 1):
        a, b = poly[j], poly[j + 1]
        inside = []
        for p in pts:
            r = seg_param(p, a, b)
            if r:
                inside.append((r[0], p))
        inside.sort(key=lambda x: x[0])
        for t, p in inside:
            nodes.append((j + t, p))
            used[p] += 1
    # 去重（相邻重复）
    clean = []
    for n in nodes:
        if not clean or math.hypot(n[1][0] - clean[-1][1][0], n[1][1] - clean[-1][1][1]) > 0.4:
            clean.append(n)
    segs_pts.append(clean)

print("=== 每条线的落子点数 ===")
for pi, nodes in enumerate(segs_pts):
    if len(nodes) >= 2:
        print(f"  #{pi:>2d}: {len(nodes)} 点")

# 统计每个点被几条线覆盖
mult = collections.Counter()
for pi, nodes in enumerate(segs_pts):
    seen = set()
    for t, p in nodes:
        key = (round(p[0], 2), round(p[1], 2))
        if key not in seen:
            seen.add(key)
            mult[key] += 1

print("\n=== 每个落子点被几条线经过 ===")
dist = collections.Counter(mult.values())
print("分布:", dict(sorted(dist.items())))
missing = [p for p in pts if (round(p[0], 2), round(p[1], 2)) not in mult]
print(f"未被任何线覆盖的落子点: {len(missing)} 个")
for p in missing[:10]:
    print("   ", p)

# 保存重建后的线（每条 = 一串点）
outp = os.path.join(HERE, "..", "..", "docs", "_dxf_lines.json")
with open(outp, "w", encoding="utf-8") as f:
    json.dump([[list(p) for _, p in nodes] for nodes in segs_pts], f)
print(f"\n已保存 {outp}")

# 看看最多（4/5条）线的点在哪
print("\n=== 多线交点（4-5 条线经过）===")
for p in pts:
    key = (round(p[0], 2), round(p[1], 2))
    if mult.get(key, 0) >= 4:
        r = math.hypot(p[0], p[1])
        a = math.degrees(math.atan2(p[1], p[0])) % 360
        print(f"   ({p[0]:+8.2f},{p[1]:+8.2f})  r={r:6.2f}  θ={a:6.1f}°  线数={mult[key]}")
