# -*- coding: utf-8 -*-
"""列出所有「跨方直达」关系：一条射线上同时含两方的点。

按「起点(方,行,列) → 终点(方,行,列)」汇总，看是否有「数字和=10」的规律。
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "server"))
from engine import geometry_dxf as G          # noqa: E402
from engine import rules_dxf as R             # noqa: E402

B = G.BOARD
CN = G.ARMY_CN

pairs = {}
for p, paths in R.RAYS.items():
    a1, r1, c1 = G.parse(p)
    for path in paths:
        for q in path:
            a2, r2, c2 = G.parse(q)
            if a1 == a2:
                continue
            key = (p, q)
            pairs.setdefault(a1, {}).setdefault(a2, set()).add((r1, c1, r2, c2))

print("=" * 88)
print("跨方直达（起点方 → 终点方）：按 (起行,起列) → (终行,终列) 汇总")
print("=" * 88)
for a1 in (1, 2, 3):
    for a2 in sorted(pairs.get(a1, {})):
        rel = sorted(pairs[a1][a2])
        print(f"\n── {CN[a1]} → {CN[a2]}  共 {len(rel)} 组 ──")
        for r1, c1, r2, c2 in rel:
            tag = ""
            if r1 == 1 and r2 == 1:                 # 双方都在底线
                tag = f"  底线对：图{10 - c1} ↔ 图{10 - c2}  " + \
                      ("✅=10" if (10 - c1) + (10 - c2) == 10 else "❌")
            print(f"   {a1}{r1}{c1} → {a2}{r2}{c2}{tag}")

print()
print("=" * 88)
print("汇总：双方都在底线（行1）的直达对")
print("=" * 88)
seen = set()
for a1 in (1, 2, 3):
    for a2 in sorted(pairs.get(a1, {})):
        if a1 >= a2:
            continue
        for r1, c1, r2, c2 in sorted(pairs[a1][a2]):
            if r1 == 1 and r2 == 1:
                s = (10 - c1) + (10 - c2)
                key = tuple(sorted([f"{CN[a1]}{c1}", f"{CN[a2]}{c2}"]))
                if key in seen:
                    continue
                seen.add(key)
                print(f"  {CN[a1]}图{10 - c1}({a1}{r1}{c1}) ↔ {CN[a2]}图{10 - c2}({a2}{r2}{c2})"
                      f"   数字和={s} {'✅' if s == 10 else '❌'}")
