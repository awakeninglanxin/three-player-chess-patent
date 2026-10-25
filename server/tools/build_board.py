# -*- coding: utf-8 -*-
"""生成完整棋盘数据：
  1. 三方 × 45 点，3 位编号（方1/2/3，行1..5=底线..最内，列1..9）
  2. 从 DXF 线网提取邻接边
  3. 统计层间连接规律（是否存在斜边）
  4. 输出 board_data.json
"""
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

# ---------- 1. 用"层线"确定每方的 5 层 × 9 列 ----------
# 层线（按半径/中轴距离识别）：每条层线经过中轴，且有 9 个点
MID = (0.0, 0.0)


def ang(p):
    return math.degrees(math.atan2(p[1], p[0])) % 360


def r_of(p):
    return math.hypot(p[0], p[1])


# 已知各方的 5 条层线（从前面分析得到）
LAYER_LINES = {
    1: [22, 12, 11, 10, 9],       # 魏: 底线 .. 最内
    3: [36, 26, 25, 24, 23],      # 吴: 底线 .. 最内
    2: [50, 40, 39, 38, 37],      # 蜀: 底线 .. 最内
}
ARMY_CN = {1: "魏", 2: "蜀", 3: "吴"}

# 各线的点序列（L=1 是底线）
board = {}
for army, ids in LAYER_LINES.items():
    for row, lid in enumerate(ids, start=1):          # row 1..5
        L = lines[lid]
        # 底线（row1）点序是从 x 负到正；其余层线两端对称
        # 统一成"列 1 = 右端"：魏底线右端 x=+52.02
        pts_row = list(L)
        # 判断该线是不是包含中轴点
        print(f"  [{ARMY_CN[army]} row{row}] 线#{lid} {len(pts_row)} 点: " +
              " ".join(f"({p[0]:.1f},{p[1]:.1f})" for p in pts_row))

# ---------- 2. 邻接边 ----------
def key(p):
    return (round(p[0], 2), round(p[1], 2))


edges = set()
for L in lines:
    for i in range(len(L) - 1):
        a, b = key(L[i]), key(L[i + 1])
        if a != b:
            edges.add((a, b) if a < b else (b, a))
print(f"\n邻接边 {len(edges)} 条")

adj = collections.defaultdict(set)
for a, b in edges:
    adj[a].add(b)
    adj[b].add(a)

deg = collections.Counter(len(adj[key(p)]) for p in pts)
print("点度数分布:", dict(sorted(deg.items())))

# ---------- 3. 层间连接统计 ----------
# 对每个点，看它的邻居相对自己的"层差/列差"
# 需要先给每个点分配 (army,row,col)；用"到各层线的距离"判定
def nearest_layer(p):
    best = None
    for army, ids in LAYER_LINES.items():
        for row, lid in enumerate(ids, start=1):
            for q in lines[lid]:
                dd = math.hypot(p[0] - q[0], p[1] - q[1])
                if best is None or dd < best[0]:
                    best = (dd, army, row)
    return best


info = {}
for p in pts:
    d, army, row = nearest_layer(p)
    info[key(p)] = (army, row, d)

# 每层线上点的列号（按沿线排序）
colmap = {}
for army, ids in LAYER_LINES.items():
    for row, lid in enumerate(ids, start=1):
        L = lines[lid]
        # 计算基准方向：从该方底线中点到中心
        base = None
        if army == 1:
            base = (0, 1)      # 向上
        elif army == 3:
            base = (-math.cos(math.radians(30)), -math.sin(math.radians(30)))
        else:
            base = (math.cos(math.radians(30)), -math.sin(math.radians(30)))
        # 用"到中轴的距离"排序：其实用与底线方向的叉积排序更稳
        # 底线方向（右方向）：
        if army == 1:
            right = (1, 0)
        elif army == 3:
            right = (-math.cos(math.radians(-60)), -math.sin(math.radians(-60)))   # 待定
        else:
            right = (math.cos(math.radians(-60)), -math.sin(math.radians(-60)))
        # 简单起见：用连线展开方向的投影排序
        if len(L) == 9:
            proj = [(p[0] * right[0] + p[1] * right[1], p) for p in L]
            proj.sort(reverse=True)
            for col, (_, p) in enumerate(proj, start=1):
                colmap[key(p)] = (army, row, col)

print(f"\n分配了 (方,行,列) 的点: {len(colmap)}/135")
miss = [p for p in pts if key(p) not in colmap]
print(f"未分配: {len(miss)} -> {[(round(p[0],1), round(p[1],1)) for p in miss[:12]]}")

# 保存中间结果
json.dump({"colmap": {f"{k[0]},{k[1]}": v for k, v in colmap.items()}},
          open(os.path.join(DOCS, "_colmap.json"), "w"), ensure_ascii=False, indent=1)
print("已保存 _colmap.json")
