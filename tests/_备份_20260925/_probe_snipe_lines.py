# -*- coding: utf-8 -*-
"""探针：射杀规则要用到的「贯通纵线」在 RAYS 里的真实形态

要回答三个问题：
  ① 「同列 + 跨方」这个纯拓扑判据，能选出哪些列？（应恰好覆盖 4/5/6）
  ② 每条贯通线覆盖哪些方？（列4/6 只连两方？列5 三方两两？）
  ③ 军帐 27 个点，各自有几条贯通射线可走？
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "server"))

from engine import geometry_dxf as D          # noqa: E402
from engine import rules_dxf as R             # noqa: E402

B = D.BOARD
ARMY_CN = {1: "魏", 2: "吴", 3: "蜀"}


def through_rays(p, min_sides=2):
    """从 p 出发、属于「贯通纵线」的射线：所有点同列，且涉及 ≥min_sides 个方"""
    c0 = D.parse(p)[2]
    out = []
    for w in R.RAYS.get(p) or ():
        if not w:
            continue
        cols = {D.parse(q)[2] for q in w}
        if cols != {c0}:
            continue
        sides = {D.parse(q)[0] for q in w}
        if len(sides) >= min_sides:
            out.append(w)
    return out


print("=" * 78)
print("① 全盘「同列 + 跨方」射线覆盖到哪些列？")
print("=" * 78)
bycol = {}
for p in B.ids:
    for w in through_rays(p):
        c = D.parse(p)[2]
        bycol.setdefault(c, set()).update(w)
for c in sorted(bycol):
    print(f"  列{c}: 命中点 {len(bycol[c])} 个  "
          f"方集合 {sorted({D.parse(q)[0] for q in bycol[c]})}")
print()
print("  ↑ 只有列4/5/6 会被军帐里的帅用到（帅只能在军帐 r1-3 × c4-6 活动）")

print()
print("=" * 78)
print("② 军帐各点的贯通射线：条数 + 方向上的方集合 + 长度")
print("=" * 78)
for a in (1, 2, 3):
    for r in (1, 2, 3):
        for c in (4, 5, 6):
            p = D.pid(a, r, c)
            rs = through_rays(p)
            if not rs:
                print(f"  {p} {ARMY_CN[a]}方 行{r} 列{c}: 【无贯通射线】")
                continue
            desc = []
            for w in rs:
                sides = sorted({D.parse(q)[0] for q in w})
                desc.append(f"len{len(w)}→方{sides}末端{w[-1]}")
            print(f"  {p} {ARMY_CN[a]}方 行{r} 列{c}: {len(rs)} 条 | " + " ; ".join(desc))

print()
print("=" * 78)
print("③ 军帐 27 点两两：沿贯通纵线「视线内可达」（空盘、无阻挡）")
print("=" * 78)


def reachable(p, q):
    """空盘（无子）时，p 能否沿贯通纵线看到 q"""
    for w in through_rays(p):
        if q in w:
            return True
    return False


pts = [D.pid(a, r, c) for a in (1, 2, 3) for r in (1, 2, 3) for c in (4, 5, 6)]
cnt = 0
cross = 0
for i in range(len(pts)):
    for j in range(i + 1, len(pts)):
        if reachable(pts[i], pts[j]) and reachable(pts[j], pts[i]):
            cnt += 1
            if D.parse(pts[i])[0] != D.parse(pts[j])[0]:
                cross += 1
print(f"  互达对数 = {cnt}（其中跨方 = {cross}，同方 = {cnt - cross}）")
print(f"  C(27,2) = {27 * 26 // 2}")

print()
print("  按列细分：")
for c in (4, 5, 6):
    sub = [p for p in pts if D.parse(p)[2] == c]
    n = sum(1 for i in range(len(sub)) for j in range(i + 1, len(sub))
            if reachable(sub[i], sub[j]) and reachable(sub[j], sub[i]))
    print(f"    列{c}: {len(sub)} 点 → 互达 {n} 对 / C(9,2)={36}")

print()
print("  按列×方对细分（列5 应三方两两全通）：")
for c in (4, 5, 6):
    sub = [p for p in pts if D.parse(p)[2] == c]
    for x, y in ((1, 2), (1, 3), (2, 3)):
        ax = [p for p in sub if D.parse(p)[0] == x]
        ay = [p for p in sub if D.parse(p)[0] == y]
        n = sum(1 for p in ax for q in ay
                if reachable(p, q) and reachable(q, p))
        print(f"    列{c} {ARMY_CN[x]}-{ARMY_CN[y]}: {n} / {len(ax) * len(ay)}")
