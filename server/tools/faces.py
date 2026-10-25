# -*- coding: utf-8 -*-
"""从 DXF 线段重建平面图的面（最小格子），统计格子形状。"""
import collections
import json
import math
import os

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "..", "docs", "_dxf_data.json")
d = json.load(open(DATA, encoding="utf-8"))
pts = [tuple(p) for p in d["points"]]
polys = [[tuple(v) for v in p] for p in d["polys"]]

# ---------- 1. 收集所有边（去重，用舍入键） ----------
def key(p):
    return (round(p[0], 3), round(p[1], 3))

edges = set()
for poly in polys:
    for j in range(len(poly) - 1):
        a, b = key(poly[j]), key(poly[j + 1])
        if a != b:
            edges.add((a, b) if a < b else (b, a))
print(f"去重后边 {len(edges)} 条")

# ---------- 2. 所有顶点与邻接 ----------
adj = collections.defaultdict(set)
vpos = {}
for a, b in edges:
    adj[a].add(b)
    adj[b].add(a)
    vpos[a] = a
    vpos[b] = b
print(f"图中顶点 {len(vpos)} 个")

# 与 135 个点对照
ptset = {key(p) for p in pts}
graph_v = set(vpos)
print(f"在图中的落子点 {len(graph_v & ptset)}/135；图中非落子顶点 {len(graph_v - ptset)} 个")

# ---------- 3. 面提取（半边遍历） ----------
def ang(o, p):
    return math.atan2(p[1] - o[1], p[0] - o[0])

nxt = {}
for v in adj:
    nb = sorted(adj[v], key=lambda p: ang(v, p))
    for i, w in enumerate(nb):
        nxt[(v, w)] = nb[(i - 1) % len(nb)]      # 顺时针下一条（用于找面）

faces = []
visited = set()
for v in adj:
    for w in adj[v]:
        if (v, w) in visited:
            continue
        face = []
        cur = (v, w)
        while cur not in visited:
            visited.add(cur)
            face.append(cur[0])
            a, b = cur
            cur = (b, nxt[cur])
            if cur == (v, w):
                break
        if len(face) >= 3:
            area = 0.0
            for i in range(len(face)):
                x1, y1 = face[i]
                x2, y2 = face[(i + 1) % len(face)]
                area += x1 * y2 - x2 * y1
            faces.append((abs(area) / 2, face))

faces.sort(key=lambda f: f[0])
print(f"\n提取到面 {len(faces)} 个")
print("面面积分布:", collections.Counter(round(f[0] / 50) * 50 for f in faces[:60] if f[0] < 500))

# 最小 12 个面的形状
print("\n=== 最小 12 个面 ===")
for a, f in faces[:12]:
    n = len(f)
    # 边长
    ls = [math.hypot(f[(i + 1) % n][0] - f[i][0], f[(i + 1) % n][1] - f[i][1]) for i in range(n)]
    angs = [round(math.degrees(math.atan2(
        f[(i + 1) % n][1] - f[i][1], f[(i + 1) % n][0] - f[i][0])) % 180, 1) for i in range(n)]
    print(f"  {n}边形 面积={a:6.1f} 边长={[round(x, 1) for x in ls]} 边方向={angs}")
    print(f"       顶点={[(round(x, 1), round(y, 1)) for x, y in f]}")

# 面数统计（形状类型）
shapes = collections.Counter(len(f) for _, f in faces)
print("\n按边数的面统计:", dict(shapes))
