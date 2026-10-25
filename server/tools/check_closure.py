# -*- coding: utf-8 -*-
"""查证：最内层首尾是否相连（row5 是否闭合环），以及哪些线经过 row5 端点。"""
import json
import math
import os

HERE = os.path.dirname(os.path.abspath(__file__))
DOCS = os.path.join(HERE, "..", "..", "docs")
lines = [[tuple(p) for p in L] for L in json.load(open(os.path.join(DOCS, "_dxf_lines.json"),
                                                       encoding="utf-8"))]

TARGETS = {
    "魏5-1": (75.143, -50.058),
    "魏5-9": (-75.143, -50.058),
    "魏5-5": (0.0, -16.934),
}


def near(p, q, tol=0.6):
    return math.hypot(p[0] - q[0], p[1] - q[1]) < tol


for name, t in TARGETS.items():
    print(f"\n=== 经过 {name} {t} 的线及其相邻点 ===")
    for i, L in enumerate(lines):
        for j, p in enumerate(L):
            if near(p, t):
                prev = L[j - 1] if j > 0 else None
                nxt = L[j + 1] if j < len(L) - 1 else None
                pt = f"({prev[0]:.1f},{prev[1]:.1f})" if prev else "—"
                nt = f"({nxt[0]:.1f},{nxt[1]:.1f})" if nxt else "—"
                print(f"  #{i:>2d} 位置{j}/{len(L) - 1}  前={pt}  后={nt}")

# 检查是否存在 y≈-50.06 的水平长线
print("\n=== 检查水平线 y≈-50.06 ===")
for i, L in enumerate(lines):
    for j in range(len(L) - 1):
        a, b = L[j], L[j + 1]
        if abs(a[1] - b[1]) < 0.2 and abs(a[1] + 50.06) < 1.0:
            print(f"  #{i} 段{j}: ({a[0]:.2f},{a[1]:.2f}) -> ({b[0]:.2f},{b[1]:.2f})")

# 全棋盘：找横向（近水平）的长段
print("\n=== 全部近水平长段（|dy|<0.5, 长>20）===")
for i, L in enumerate(lines):
    for j in range(len(L) - 1):
        a, b = L[j], L[j + 1]
        Ln = math.hypot(b[0] - a[0], b[1] - a[1])
        if abs(a[1] - b[1]) < 0.5 and Ln > 20:
            print(f"  #{i} 段{j}: ({a[0]:.2f},{a[1]:.2f}) -> ({b[0]:.2f},{b[1]:.2f}) 长{Ln:.1f}")
