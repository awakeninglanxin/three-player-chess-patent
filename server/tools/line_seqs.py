# -*- coding: utf-8 -*-
"""输出 51 条线的完整点序列 + 关键节点的连线关系。"""
import collections
import json
import math
import os

HERE = os.path.dirname(os.path.abspath(__file__))
DOCS = os.path.join(HERE, "..", "..", "docs")
lines = json.load(open(os.path.join(DOCS, "_dxf_lines.json"), encoding="utf-8"))
lines = [[tuple(p) for p in L] for L in lines]

# 关键节点
KEYS = {
    "三角区下顶点": (0.0, -16.93),
    "三角区右顶点": (14.67, 8.47),
    "三角区左顶点": (-14.67, 8.47),
    "底边中点": (0.0, -90.10),
    "右上顶点": (104.04, 0.0),
    "右下顶点": (52.02, -90.10),
}


def near(p, q, tol=1.0):
    return math.hypot(p[0] - q[0], p[1] - q[1]) < tol


print("=== 经过关键节点的线 ===")
for name, kp in KEYS.items():
    hit = []
    for i, L in enumerate(lines):
        if any(near(p, kp) for p in L):
            hit.append(i)
    print(f"\n{name} {kp} 被 {len(hit)} 条线经过: {hit}")
    for i in hit:
        seq = " → ".join(f"({p[0]:.1f},{p[1]:.1f})" for p in lines[i])
        print(f"   #{i}: {seq}")

# 找出贯穿中轴向上的线（荆州方向）
print("\n\n=== 全部 51 条线的序列（按线号）===")
for i, L in enumerate(lines):
    seq = " ".join(f"({p[0]:.1f},{p[1]:.1f})" for p in L)
    print(f"#{i:>2d} [{len(L)}]: {seq}")
