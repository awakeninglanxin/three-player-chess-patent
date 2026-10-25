# -*- coding: utf-8 -*-
"""验证「数字和=10 共线」的物理实现：

猜想：自己「行5列k」点，沿【自己列1方向】走 → 命中某方「行5列(10-k)」；
      沿【自己列9方向】走      → 命中另一方「行5列(10-k)」。
若全部精确命中，则「共线规则」不是玄学，而是这个网格的构造性质。
"""
import sys
import os
import math

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "server"))
from engine.geometry_dxf import Board, parse  # noqa: E402

B = Board()
CN = {1: "魏", 2: "吴", 3: "蜀"}


def uvec(p, q):
    d = np.array([B.xy[q][0] - B.xy[p][0], B.xy[q][1] - B.xy[p][1]], float)
    return d / np.linalg.norm(d)


def hit_along(p, u, exclude_army):
    """从 p 沿 u 走，返回精确命中的（其它方）格点列表"""
    px, py = B.xy[p]
    res = []
    for q in B.ids:
        if parse(q)[0] == exclude_army:
            continue
        qx, qy = B.xy[q]
        d = np.array([qx - px, qy - py], float)
        L = np.linalg.norm(d)
        if L < 1e-9:
            continue
        cross = abs(d[0] * u[1] - d[1] * u[0])          # 叉积 = 偏离直线距离
        dot = d @ u
        if abs(cross) < 0.02 and dot > 0:
            res.append((round(L, 4), q))
    res.sort()
    return res


print("=== 每一方「行5列k」沿【本方列1方向 / 列9方向】的过河命中 ===\n")
ok = fail = 0
for a in (1, 2, 3):
    d1 = uvec(f"{a}11", f"{a}51")      # 本方列1方向（由底线指向前沿）
    d9 = uvec(f"{a}19", f"{a}59")      # 本方列9方向
    print(f"--- {CN[a]}方   列1方向={math.degrees(math.atan2(d1[1], d1[0])):7.2f}°"
          f"   列9方向={math.degrees(math.atan2(d9[1], d9[0])):7.2f}°")
    for k in range(1, 10):
        p = f"{a}5{k}"
        want = 10 - k                    # 期望命中「列(10-k)」
        for tag, u in (("列1向", d1), ("列9向", d9)):
            hits = hit_along(p, u, a)
            if not hits:
                print(f"   {p}(行5列{k}) {tag}: 无命中")
                fail += 1
                continue
            L, q = hits[0]
            qa, qr, qc = parse(q)
            flag = "✔" if qc == want else "✘"
            if qc == want:
                ok += 1
            else:
                fail += 1
            print(f"   {p}(行5列{k}) {tag}: {q}({CN[qa]}行{qr}列{qc})"
                  f"  距离{L:8.3f}  {flag} 期望列{want}")
    print()

print(f"\n合计:  精确命中 = {ok}   未命中/不符 = {fail}")
