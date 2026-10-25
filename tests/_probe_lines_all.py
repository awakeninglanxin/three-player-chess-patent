# -*- coding: utf-8 -*-
"""全量 dump：51 条线 → 按「同一条无限直线」合并 → 输出直线族与线上全部点。

目的：回答「吴 M6 打魏4线」这类共线问题。只打印事实，不做推测。
"""
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "server"))
from engine import geometry_dxf as G          # noqa: E402

B = G.BOARD
NAME = {1: '魏', 2: '吴', 3: '蜀'}
LET = {1: {1: 'E', 2: 'D', 3: 'C', 4: 'B', 5: 'A'},
       2: {1: 'O', 2: 'N', 3: 'M', 4: 'L', 5: 'K'},
       3: {1: 'J', 2: 'I', 3: 'H', 4: 'G', 5: 'F'}}


def lab(p):
    a, r, c = G.parse(p)
    return "%s%s%d" % (NAME[a], LET[a][r], 10 - c)


def tag(p):
    a, r, c = G.parse(p)
    return "%s行%d列%d" % (NAME[a], r, c)


D = json.load(open(os.path.join(HERE, "..", "server", "data", "board_135.json"),
                   encoding="utf-8"))
LINES = [tuple(p.replace("-", "") for p in l) for l in D["lines"]]


def ang(a, b):
    """方向角，取模 180"""
    x1, y1 = B.xy[a]
    x2, y2 = B.xy[b]
    return math.degrees(math.atan2(y2 - y1, x2 - x1)) % 180.0


def off(a, theta):
    """点到过原点、方向 theta 的直线族的「截距」（法向投影）"""
    t = math.radians(theta)
    nx, ny = -math.sin(t), math.cos(t)
    x, y = B.xy[a]
    return x * nx + y * ny


# ---------- 1) 每条线切成极大直线段 ----------
segments = []
for i, L in enumerate(LINES):
    if len(L) < 2:
        continue
    cur = [L[0]]
    ca = None
    for j in range(len(L) - 1):
        a, b = L[j], L[j + 1]
        aa = ang(a, b)
        if ca is None or abs(((aa - ca + 90) % 180) - 90) < 0.6:
            cur.append(b)
            ca = aa if ca is None else ca
        else:
            if len(cur) >= 2:
                segments.append((i, ca, cur))
            cur = [a, b]
            ca = aa
    if len(cur) >= 2:
        segments.append((i, ca, cur))

print("=" * 96)
print("① 全部 %d 条线 → 切成 %d 段极大直线段" % (len(LINES), len(segments)))
print("=" * 96)

# ---------- 2) 按 (角度, 截距) 合并成无限直线 ----------
fams = []
for idx, theta, pts in segments:
    mid = pts[len(pts) // 2]
    d = off(mid, theta)
    hit = None
    for f in fams:
        dth = abs(((theta - f['theta'] + 90) % 180) - 90)
        if dth < 1.2 and abs(d - f['d']) < 3.0:
            hit = f
            break
    if hit is None:
        hit = {'theta': theta, 'd': d, 'segs': []}
        fams.append(hit)
    hit['segs'].append((idx, pts))

# 每条无限直线上收集所有点（按投影排序）
out = []
for f in fams:
    seen = {}
    for idx, pts in f['segs']:
        for p in pts:
            # 用起点做投影参数
            if not seen:
                seen[p] = 0.0
                continue
            x0, y0 = B.xy[next(iter(seen))]
            x, y = B.xy[p]
            t = math.radians(f['theta'])
            seen[p] = (x - x0) * math.cos(t) + (y - y0) * math.sin(t)
    ordered = sorted(seen, key=lambda p: seen[p])
    out.append((f['theta'], f['d'], ordered))

out.sort(key=lambda r: (round(r[0]), r[1]))

print()
print("② 合并后的「无限直线」共 %d 条（按角度/截距排序）" % len(out))
print("=" * 96)
for k, (theta, d, pts) in enumerate(out):
    armies = sorted(set(int(p[0]) for p in pts))
    flag = "  ← 跨方!" if len(armies) > 1 else ""
    print("\n[直线 %2d] 角度 %6.2f°  截距 %8.2f  %d 点%s" % (k, theta, d, len(pts), flag))
    print("    " + "  ".join("%s(%s)" % (lab(p), tag(p)) for p in pts))

# ---------- 3) 建立 点 -> 直线 索引 ----------
idx_of = {}
for k, (theta, d, pts) in enumerate(out):
    for p in pts:
        idx_of.setdefault(p, []).append(k)

print()
print("=" * 96)
print("③ 吴方行 M（行3）逐点：所在直线 & 能碰到哪些方的点")
print("=" * 96)
for c in range(1, 10):
    p = G.pid(2, 3, c)
    ls = idx_of.get(p, [])
    print("\n吴M%d  引擎%s  %s" % (10 - c, p, tag(p)))
    if not ls:
        print("    (不在任何直线上?!)")
    for k in ls:
        theta, d, pts = out[k]
        others = [q for q in pts if q != p]
        am = sorted(set(int(q[0]) for q in others))
        cross = " ★跨方" if len(am) > 1 or (am and am != [2]) else ""
        print("   直线%d 角度%6.2f°  %d点  其他点: %s%s"
              % (k, theta, len(pts),
                 " ".join(lab(q) for q in others), cross))
