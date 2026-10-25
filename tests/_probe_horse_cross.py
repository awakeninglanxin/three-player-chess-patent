# -*- coding: utf-8 -*-
"""探针：马能否「跨中间区域带」—— 老师 2026-09-24 提出。

老师的例子：
  · 魏马在 A7，A6 空 → 为何不跨到 F5？
  · 只要 F3 空，就可以去 G2 或 G4

本脚本逐步 dump 相关点位的引擎坐标、几何邻居、马的合法落点，
并单独检查「马在本方 row5 时，朝对面方一侧的马步落点」是否被实现。
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "server"))

from engine import geometry_dxf as G
from engine import rules_dxf as R
from engine import game_dxf as GA

B = G.BOARD

# ---- 字母/数字 → 引擎 pid ----
LETTER = {"2-1": "O", "2-2": "N", "2-3": "M", "2-4": "L", "2-5": "K",
          "1-1": "E", "1-2": "D", "1-3": "C", "1-4": "B", "1-5": "A",
          "3-1": "J", "3-2": "I", "3-3": "H", "3-4": "G", "3-5": "F"}
P2L = {}                      # pid -> "方行字母+数字"
NAME = {1: "魏", 2: "吴", 3: "蜀"}
for key, ch in LETTER.items():
    a_s, r_s = key.split("-")
    for digit in range(1, 10):
        P2L["%s%s%d" % (a_s, r_s, 10 - digit)] = "%s%s" % (ch, digit)


def lab(p):
    return P2L.get(p) or ("?%s" % p)


POINTS = ["153", "154", "356", "355", "353", "346", "342", "345"]
print("=" * 78)
print("① 老师提到的点位 → 引擎 pid / 字母标注")
print("=" * 78)
for p in POINTS:
    print("  %-6s = %s" % (p, lab(p)))

print()
print("=" * 78)
print("② 魏马 A7(153) 的几何邻居与合法落点（空盘）")
print("=" * 78)
for p in ("153", "154", "155"):
    nb = sorted(B.adj.get(p) or [])
    print("  %s(%s) 几何邻居 %d 个: %s" % (p, lab(p), len(nb),
                                       ", ".join("%s(%s)" % (q, lab(q)) for q in nb)))

print()
print("  马在 153 的常规马步落点：")
for leg, dest in R.HORSE_T.get("153", ()):
    print("     腿 %s(%s) → 落点 %s(%s)" % (leg, lab(leg), dest, lab(dest)))
print("  马在 153 的合法着法（空盘）：",
      sorted("%s(%s)" % (d, lab(d)) for d in
             (lambda: [y for _x, y in R.HORSE_T.get("153", ())])()))

print()
print("=" * 78)
print("③ 三角区回跳表全貌（原文 6 对）")
print("=" * 78)
print("  REBOUND 原始结构（前 4 项）:")
for i, kv in enumerate(sorted(R.REBOUND.items())):
    if i >= 4:
        break
    print("     %r" % (kv,))
print("  _REBOUND_SELF（原文 6 对记账，(方,列) -> 落点方）:")
for k, v in sorted(R._REBOUND_SELF.items()):
    src = "%d5%d" % (k[0], k[1])
    print("     %s(%s) -> %s方 row5 中点 %d5%d" % (src, lab(src), NAME[v], v, 5))
print("  展平后:")
for p in sorted(R.REBOUND):
    tgts = []
    for q in sorted(R.REBOUND[p]):
        q = q if isinstance(q, str) else q[-1]
        tgts.append("%s(%s)" % (q, lab(q)))
    print("     %s(%s) -> %s" % (p, lab(p), ", ".join(tgts)))

print()
print("=" * 78)
print("④ F4(356) 的马步 —— 验证老师的「F3 空 → 可去 G2/G4」")
print("=" * 78)
print("  马在 356(%s) 的常规马步：" % lab("356"))
for leg, dest in R.HORSE_T.get("356", ()):
    print("     腿 %s(%s) → 落点 %s(%s)" % (leg, lab(leg), dest, lab(dest)))

print()
print("=" * 78)
print("⑤ 跨方能力总检：马能否走出本方 row1..row5（除 6 对回跳外）")
print("=" * 78)
CROSS = []
for p, lst in R.HORSE_T.items():
    a = int(p[0])
    for _leg, dest in lst:
        if int(dest[0]) != a:
            CROSS.append((p, dest))
print("  全盘「跨方马步」共 %d 个起点-落点对：" % len(CROSS))
for p, dest in sorted(CROSS)[:40]:
    print("     %s(%s) → %s(%s)" % (p, lab(p), dest, lab(dest)))
if len(CROSS) > 40:
    print("     ...（略）")

print()
print("=" * 78)
print("⑥ 关键：回到「马在本方 row5，朝对面方一侧」的马步应当落在哪")
print("=" * 78)
print("  以魏方 row5 为例，列出每个点的常规马步落点（含被边界砍掉的位移）：")
for c in range(1, 10):
    p = "15%d" % c
    got = sorted(d for _l, d in R.HORSE_T.get(p, ()))
    print("     15%d(%s) → %s" % (c, lab(p), ", ".join("%s(%s)" % (d, lab(d)) for d in got)))

print()
print("  同一点位，若把「行 +1 / +2」视为跨入对面方，理论上应有哪些落点：")
DELTAS = [(dr, dc) for dr in (-2, -1, 1, 2) for dc in (-2, -1, 1, 2)
          if sorted((abs(dr), abs(dc))) == [1, 2]]
for c in (3, 4, 6, 7):
    p = "15%d" % c
    fwd = [(dr, dc) for dr, dc in DELTAS if dr > 0]
    print("     %s(%s) 朝对面方（行 +1/+2）的位移: %s" % (p, lab(p), fwd))

print()
print("=" * 78)
print("⑦ 几何实证：A7(153) 到 F5(355) 的距离，与「日」对比")
print("=" * 78)
try:
    import math
    def pt(p):
        return B.pts[p] if hasattr(B, "pts") else B.coord[p]
    for a, b in [("153", "355"), ("154", "355"), ("356", "353"),
                 ("356", "346"), ("356", "342"), ("153", "353"), ("153", "354")]:
        pa, pb = pt(a), pt(b)
        d = math.hypot(pa[0] - pb[0], pa[1] - pb[1])
        print("     %s(%s) ↔ %s(%s)  d = %.4f" % (a, lab(a), b, lab(b), d))
except Exception as e:
    print("     几何读取失败:", e)
    print("     BOARD 可用属性:", [k for k in dir(B) if not k.startswith("_")])
