# -*- coding: utf-8 -*-
"""把所有线段按共线合并成"完整直线"，输出直线族结构与每线上的点。"""
import collections
import json
import math
import os

HERE = os.path.dirname(os.path.abspath(__file__))
DOCS = os.path.join(HERE, "..", "..", "docs")
lines = json.load(open(os.path.join(DOCS, "_dxf_lines.json"), encoding="utf-8"))
lines = [[tuple(p) for p in L] for L in lines]
pts = [tuple(p) for p in json.load(open(os.path.join(DOCS, "_dxf_data.json"),
                                          encoding="utf-8"))["points"]]

# ---------- 收集所有"极大直线段"：每条 POLYLINE 内，把共线的连续段合并 ----------
def dir_of(a, b):
    d = math.degrees(math.atan2(b[1] - a[1], b[0] - a[0])) % 180
    return d


straights = []          # (angle, point_a, point_b, all_points_on_it)
for L in lines:
    if len(L) < 2:
        continue
    cur = [L[0]]
    cur_ang = None
    for i in range(len(L) - 1):
        a, b = L[i], L[i + 1]
        ang = dir_of(a, b)
        if cur_ang is None or abs(((ang - cur_ang + 90) % 180) - 90) < 0.4:
            cur.append(b)
            if cur_ang is None:
                cur_ang = ang
        else:
            straights.append((cur_ang, cur[0], cur[-1], list(cur)))
            cur = [a, b]
            cur_ang = ang
    straights.append((cur_ang, cur[0], cur[-1], list(cur)))

print(f"合并后共线直线段 {len(straights)} 条")
cnt = collections.Counter(round(s[0]) for s in straights)
print("方向分布（整度）:", dict(sorted(cnt.items())))

# ---------- 按方向聚类（容差 0.5 度） ----------
groups = []
for s in sorted(straights, key=lambda x: x[0]):
    if groups and abs(s[0] - groups[-1][0]) < 0.5:
        groups[-1][1].append(s)
    else:
        groups.append([s[0], [s]])
print(f"\n方向族 {len(groups)} 个：")
for ang, ss in groups:
    print(f"  方向 {ang:6.2f}°  段数 {len(ss):>3d}  总长 {sum(math.hypot(s[2][0]-s[1][0], s[2][1]-s[1][1]) for s in ss):7.1f}")

# ---------- 每个方向族的"平行线"（按截距分组） ----------
print("\n=== 各方向族的平行线数（按截距聚类）===")
for ang, ss in groups:
    t = math.radians(ang)
    nx, ny = -math.sin(t), math.cos(t)      # 法向
    info = []
    for a0, p1, p2, pl in ss:
        c = p1[0] * nx + p1[1] * ny
        info.append((c, p1, p2, pl))
    info.sort()
    # 聚类截距
    clus = []
    for c, p1, p2, pl in info:
        if clus and abs(c - clus[-1][-1][0]) < 1.5:
            clus[-1].append((c, p1, p2, pl))
        else:
            clus.append([(c, p1, p2, pl)])
    print(f"\n  方向 {ang:.2f}°：{len(clus)} 条平行线")
    for cl in clus:
        c = sum(x[0] for x in cl) / len(cl)
        # 该线上全部点
        allp = []
        for _, p1, p2, pl in cl:
            allp.extend(pl)
        # 去重排序
        uniq = []
        for p in allp:
            if not any(math.hypot(p[0] - q[0], p[1] - q[1]) < 0.5 for q in uniq):
                uniq.append(p)
        # 沿线排序
        if len(uniq) > 1:
            uniq.sort(key=lambda p: p[0] * math.cos(t) + p[1] * math.sin(t))
        print(f"    c={c:>8.2f}  点数={len(uniq):>2d}  " +
              " ".join(f"({p[0]:.1f},{p[1]:.1f})" for p in uniq))
