# -*- coding: utf-8 -*-
"""检查：三方的「底边数字线」是否真的存在（同一条棋盘线上）。

图上的数字约定（实测）：
    · 魏底线 1-1-x：图上数字 n = DXF 列 (10-n)
    · 吴底线 2-1-x：同上
    · 蜀底线 3-1-x：同上
老师规则：「自己底边的数字 n」与「对面的数字 10-n」共线。
"""
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "server"))
from engine import geometry_dxf as G          # noqa: E402
from engine import rules_dxf as R             # noqa: E402

B = G.BOARD
CN = G.ARMY_CN
D = json.load(open(os.path.join(HERE, "..", "server", "data", "board_135.json"), encoding="utf-8"))
# board_135.json 用 'a-b-c' 命名，引擎用 'abc'
LINES = [tuple(p.replace("-", "") for p in l) for l in D["lines"]]

picnum = lambda pid: 10 - int(pid[2])
base = {a: {n: f"{a}1{10 - n}" for n in range(1, 10)} for a in (1, 2, 3)}
for a in (1, 2, 3):
    print(f"方{a} {CN[a]} 图数字→点: " + "  ".join(f"{n}→{base[a][n]}" for n in range(1, 10)))
print()

# 哪些线"跨方"（两端分属不同方的底线）
print("=" * 84)
print("① 51 条线中，哪些跨方（两端在不同方底线上）")
print("=" * 84)
cross = []
for ln in LINES:
    ends = (ln[0], ln[-1])
    if all(e not in {v for d in base.values() for v in d.values()} for e in ends):
        continue
    fams = [int(e[0]) for e in ends]
    nm = [picnum(e) for e in ends]
    if fams[0] != fams[1]:
        cross.append(ln)
        s = nm[0] + nm[1]
        flag = "✅=10" if s == 10 else "❌≠10"
        print(f"  {CN[fams[0]]}图{nm[0]}({ln[0]}) → {CN[fams[1]]}图{nm[1]}({ln[-1]})  和={s} {flag}   线长{len(ln)}")
print(f"\n  跨方底线线共 {len(cross)} 条")

# ② 每条线内部结构（是否直线）
print()
print("=" * 84)
print("② 全部 51 条线的端点与「是否严格直线」")
print("=" * 84)
for i, ln in enumerate(LINES):
    pts = [(B.xy[p][0], B.xy[p][1]) for p in ln]
    dev = 0.0
    if len(pts) >= 3:
        x0, y0 = pts[0]
        x1, y1 = pts[-1]
        L = math.hypot(x1 - x0, y1 - y0)
        if L > 0:
            for (x, y) in pts[1:-1]:
                dev = max(dev, abs((x1 - x0) * (y - y0) - (y1 - y0) * (x - x0)) / L)
    print(f"  线{i:2d}  长{len(ln):2d}  最大偏离直线={dev:6.3f}   {ln[0]} .. {ln[-1]}   "
          f"[{CN.get(int(ln[0][0]), '?')}]")

# ③ 从每方底线各点出发，看能否沿单条线直达另两方底线
print()
print("=" * 84)
print("③ 直连检查：起点方数字 n → 对面方数字 m（同一条线）")
print("=" * 84)
direct = {}
for ln in LINES:
    for i, p in enumerate(ln):
        for q in ln[i + 1:]:
            direct.setdefault((p, q), []).append(ln)
            direct.setdefault((q, p), []).append(ln)

for a in (1, 2, 3):
    for b in (1, 2, 3):
        if a >= b:
            continue
        print(f"\n  ── {CN[a]}底线 ↔ {CN[b]}底线 ──")
        for n in range(1, 10):
            p = base[a][n]
            hits = []
            for m in range(1, 10):
                q = base[b][m]
                if (p, q) in direct:
                    hits.append(m)
            if hits:
                ok = [m for m in hits if m == 10 - n]
                print(f"    {CN[a]}图{n}({p}) → {CN[b]}图{hits}"
                      + ("  ✅ 含 10-n" if ok else "  ❌ 无 10-n"))
            else:
                print(f"    {CN[a]}图{n}({p}) → (无直连)  ❌ 应连 {CN[b]}图{10 - n}")
