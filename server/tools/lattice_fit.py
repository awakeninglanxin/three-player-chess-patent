# -*- coding: utf-8 -*-
"""邻接向量分析：从 135 个点反解格基，验证整数格坐标。"""
import collections
import json
import math
import os

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "..", "docs", "_dxf_data.json")
d = json.load(open(DATA, encoding="utf-8"))
pts = [tuple(p) for p in d["points"]]

# ---------- 1. 所有短边向量（< 15） ----------
vecs = []
for i in range(len(pts)):
    for j in range(i + 1, len(pts)):
        dx, dy = pts[j][0] - pts[i][0], pts[j][1] - pts[i][1]
        L = math.hypot(dx, dy)
        if L < 15:
            ang = round(math.degrees(math.atan2(dy, dx)) % 180, 1)
            vecs.append((L, ang, i, j, (dx, dy)))

print(f"短边（<15）共 {len(vecs)} 条")
by_len = collections.Counter(round(v[0], 2) for v in vecs)
print("长度分布:", dict(sorted(by_len.items())))

print("\n各长度对应的方向：")
by_len2 = collections.defaultdict(list)
for L, ang, i, j, dv in vecs:
    by_len2[round(L, 2)].append(ang)
for L in sorted(by_len2):
    angs = sorted(set(by_len2[L]))
    print(f"  L={L:>6.2f} ({L / 13.005:>5.3f}格)  n={len(by_len2[L]):>3d}  方向={angs[:12]}")

# ---------- 2. 用最规则的两种短向量当格基，验证整数格坐标 ----------
# 取最长出现的那两种
cnt = collections.Counter(round(v[0], 2) for v in vecs)
top = [L for L, _ in cnt.most_common(2)]
print(f"\n最频繁两种边长: {top}")

# 收集这两种长度的向量（按方向聚类）
basis_pool = []
for L, ang, i, j, dv in vecs:
    if round(L, 2) in top:
        basis_pool.append((L, ang, dv, pts[i], pts[j]))
print(f"候选基向量 {len(basis_pool)} 条")

# 方向聚类（1 度间隔）
groups = collections.defaultdict(list)
for L, ang, dv, a, b in basis_pool:
    groups[(round(L, 2), round(ang))].append((dv, a, b))
print("\n方向聚类（前 12 组）:")
for k in sorted(groups, key=lambda k: -len(groups[k]))[:12]:
    g = groups[k]
    dx = sum(x[0][0] for x in g) / len(g)
    dy = sum(x[0][1] for x in g) / len(g)
    print(f"  L={k[0]:>6.2f} 角度={k[1]:>5}° n={len(g):>4d}  平均向量=({dx:+.3f},{dy:+.3f})")

# ---------- 3. 试拟合格基：用两种最频繁的方向 ----------
cand = sorted(groups, key=lambda k: -len(groups[k]))[:6]
print("\n=== 用前两个方向做格基，检验整数格 ===")
for trial in [(0, 1), (0, 2), (0, 3), (1, 2)]:
    if trial[0] >= len(cand) or trial[1] >= len(cand):
        continue
    k1, k2 = cand[trial[0]], cand[trial[1]]
    v1 = (sum(x[0][0] for x in groups[k1]) / len(groups[k1]),
          sum(x[0][1] for x in groups[k1]) / len(groups[k1]))
    v2 = (sum(x[0][0] for x in groups[k2]) / len(groups[k2]),
          sum(x[0][1] for x in groups[k2]) / len(groups[k2]))
    det = v1[0] * v2[1] - v1[1] * v2[0]
    if abs(det) < 1e-6:
        continue
    bad, maxerr = 0, 0.0
    for (x, y) in pts:
        # 解 a*v1 + b*v2 = (x,y)
        a = (x * v2[1] - y * v2[0]) / det
        b = (v1[0] * y - v1[1] * x) / det
        ea, eb = abs(a - round(a)), abs(b - round(b))
        e = math.hypot((a - round(a)) * v1[0], (a - round(a)) * v1[1]) + \
            math.hypot((b - round(b)) * v2[0], (b - round(b)) * v2[1])
        maxerr = max(maxerr, e)
        if ea > 0.05 or eb > 0.05:
            bad += 1
    print(f"  基1(L={k1[0]}, {k1[1]}°) + 基2(L={k2[0]}, {k2[1]}°): 非整数点 {bad}/135  最大误差 {maxerr:.3f}px"
          f"  |v1|={math.hypot(*v1):.2f} |v2|={math.hypot(*v2):.2f}")
