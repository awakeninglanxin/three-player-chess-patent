# -*- coding: utf-8 -*-
"""按"线的中点所在扇区"给 51 条线分组，重建三方网格结构。

扇区（以中心为原点）：
  底线中点方向：魏 270° / 吴 30° / 蜀 150°
  地带中点方向：荆州 90° / 赤壁 210° / 祁山 330°
  扇区边界取 60°/120°/180°/240°/300°/0°（即三条地带的两侧边界的角平分）
"""
import collections
import json
import math
import os

HERE = os.path.dirname(os.path.abspath(__file__))
DOCS = os.path.join(HERE, "..", "..", "docs")
lines = json.load(open(os.path.join(DOCS, "_dxf_lines.json"), encoding="utf-8"))
lines = [[tuple(p) for p in L] for L in lines]


def ang(p):
    return math.degrees(math.atan2(p[1], p[0])) % 360


def sector(theta):
    """返回 (方名, 角色)"""
    # 底线中点方向
    if 240 <= theta < 300:
        return "魏"
    if theta >= 300 or theta < 0:
        return "吴"
    if theta < 60:
        return "吴"
    if 60 <= theta < 120:
        return "荆州"
    if 120 <= theta < 180:
        return "蜀"
    if 180 <= theta < 240:
        return "赤壁"
    return "?"


# 对每条线：按每个顶点判断，如果全部顶点在同一扇区则规整；否则标为"跨界线"
print("=== 51 条线按扇区分类 ===")
classes = collections.defaultdict(list)
for i, L in enumerate(lines):
    secs = collections.Counter(sector(ang(p)) for p in L)
    main = secs.most_common(1)[0][0]
    net = "/".join(f"{k}×{v}" for k, v in secs.most_common())
    classes[main].append(i)
    print(f"  #{i:>2d} [{len(L):>2d}点] 主扇区={main:<4s}  分布={net:<24s} 首尾=({L[0][0]:.1f},{L[0][1]:.1f})→({L[-1][0]:.1f},{L[-1][1]:.1f})")

print("\n=== 分组合计 ===")
for k, v in classes.items():
    print(f"  {k}: {len(v)} 条 -> {v}")
