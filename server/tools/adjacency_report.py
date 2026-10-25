# -*- coding: utf-8 -*-
"""输出每方 45 点的邻居列表（按 行-列 编号），揭示网格连接模式。"""
import collections
import json
import math
import os

HERE = os.path.dirname(os.path.abspath(__file__))
DOCS = os.path.join(HERE, "..", "..", "docs")
pts = [tuple(p) for p in json.load(open(os.path.join(DOCS, "_dxf_data.json"),
                                        encoding="utf-8"))["points"]]
lines = [[tuple(p) for p in L] for L in json.load(open(os.path.join(DOCS, "_dxf_lines.json"),
                                                       encoding="utf-8"))]

LAYER_LINES = {1: [22, 12, 11, 10, 9], 3: [36, 26, 25, 24, 23], 2: [50, 40, 39, 38, 37]}
ARMY_CN = {1: "魏", 2: "蜀", 3: "吴"}


def key(p):
    return (round(p[0], 2), round(p[1], 2))


# 编号：每方 行 1..5，列 1..9。列 1 = 右端。
# 用"该方底线中点"和"底线方向"定义"右"：
#   魏: 底线 y=-90.1，右=+x
#   吴: 底线从 (104,0) 到 (52,90)：右 = ?  统一用"面向中心时右手边"
#      吴 面向中心 210°，右手 = 210-90 = 120° 方向 → (-0.5, 0.866)
#   蜀 面向中心 330°，右手 = 240° → (-0.5,-0.866)
RIGHT = {1: (1.0, 0.0), 3: (-0.5, math.sqrt(3) / 2), 2: (-0.5, -math.sqrt(3) / 2)}

label = {}          # key -> "A-R-C"
for army, ids in LAYER_LINES.items():
    rx, ry = RIGHT[army]
    for row, lid in enumerate(ids, start=1):
        L = lines[lid]
        pr = sorted(L, key=lambda p: -(p[0] * rx + p[1] * ry))
        for col, p in enumerate(pr, start=1):
            label[key(p)] = (army, row, col)

# 邻接
adj = collections.defaultdict(set)
for L in lines:
    for i in range(len(L) - 1):
        a, b = key(L[i]), key(L[i + 1])
        if a != b:
            adj[a].add(b)
            adj[b].add(a)

# 输出三方各自的连接表
for army in (1, 3, 2):
    print(f"\n{'=' * 60}\n{ARMY_CN[army]}方邻接表（行-列 → 邻居的行-列）\n{'=' * 60}")
    rows_of = collections.defaultdict(list)
    for k, v in label.items():
        if v[0] == army:
            rows_of[v[1]].append((v[2], k))
    for row in sorted(rows_of):
        for col, k in sorted(rows_of[row]):
            nbs = sorted(label[n] for n in adj[k] if n in label)
            nbs_txt = " ".join(f"{r}-{c}" for _, r, c in nbs)
            other = [n for n in adj[k] if n not in label]
            ot = f"  +跨方点×{len(other)}" if other else ""
            print(f"  {row}-{col}: [{nbs_txt}]{ot}")
        print()

# 度分布按方
print("\n=== 度分布（按方）===")
for army in (1, 3, 2):
    dd = collections.Counter()
    for k, v in label.items():
        if v[0] == army:
            dd[len(adj[k])] += 1
    print(f"  {ARMY_CN[army]}: {dict(sorted(dd.items()))}")
