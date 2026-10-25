# -*- coding: utf-8 -*-
"""跨方几何枚举：找出所有「几何形状与传统马步同构」的跨方点对。

用途（仅诊断，不定义规则 —— 老师明确要求规则判据是「数格点数」）：
  ① 统计本方内部马步 (1格+2格) 的几何长度分布
  ② 扫描全部跨方点对，距离落在该区间内的列出来
  ③ 看老师的例子 A7→F5 / A6→F5 / A4→F5 / F4→G2 各属于哪一类
"""
import math
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "server"))

from engine import geometry_dxf as G
from engine import rules_dxf as R
from engine import game_dxf as GA

B = G.BOARD
LETTER = {"2-1": "O", "2-2": "N", "2-3": "M", "2-4": "L", "2-5": "K",
          "1-1": "E", "1-2": "D", "1-3": "C", "1-4": "B", "1-5": "A",
          "3-1": "J", "3-2": "I", "3-3": "H", "3-4": "G", "3-5": "F"}
P2L = {}
for key, ch in LETTER.items():
    a_s, r_s = key.split("-")
    for digit in range(1, 10):
        P2L["%s%s%d" % (a_s, r_s, 10 - digit)] = "%s%s" % (ch, digit)
NAME = {1: "魏", 2: "吴", 3: "蜀"}


def lab(p):
    return P2L.get(p) or ("?%s" % p)


def pt(p):
    return B.xy[p]


def d(a, b):
    pa, pb = pt(a), pt(b)
    return math.hypot(pa[0] - pb[0], pa[1] - pb[1])


# ---------- ① 本方内部马步的几何长度分布 ----------
lens = []
for p, lst in R.HORSE_T.items():
    a0 = p[0]
    for _leg, dest in lst:
        if dest[0] == a0:                     # 只统计本方内部（排除回跳）
            lens.append(d(p, dest))
lens.sort()
print("=" * 84)
print("① 本方内部马步（1格+2格）的几何长度分布：%d 条" % len(lens))
print("=" * 84)
print("   最小 %.4f   最大 %.4f   中位 %.4f" % (lens[0], lens[-1], lens[len(lens) // 2]))
import collections
hist = collections.Counter(round(x) for x in lens)
print("   取整分布:", dict(sorted(hist.items())))
LO, HI = lens[0], lens[-1]

# ---------- ② 扫描全部跨方点对 ----------
print()
print("=" * 84)
print("② 跨方点对中，几何距离落在「马步长度区间 [%.2f, %.2f]」的：" % (LO, HI))
print("=" * 84)
hits = []
for p in sorted(B.ids):
    for q in sorted(B.ids):
        if p >= q or p[0] == q[0]:
            continue
        dd = d(p, q)
        if LO - 0.5 <= dd <= HI + 0.5:
            hits.append((dd, p, q))
# 按起点分组
by_src = collections.defaultdict(list)
for dd, p, q in hits:
    by_src[p].append((dd, q))
print("   共 %d 个点对，涉及 %d 个起点" % (len(hits), len(by_src)))
shown = 0
for p in sorted(by_src):
    lst = sorted(by_src[p])
    print("   %s(%s) → %s" % (p, lab(p),
          ", ".join("%s(%s) d=%.2f" % (q, lab(q), dd) for dd, q in lst)))
    shown += 1
    if shown >= 30:
        print("   ...（只列前 30 个起点）")
        break

# ---------- ③ 老师举的例子逐条判 ----------
print()
print("=" * 84)
print("③ 老师举的例子逐条几何判定")
print("=" * 84)
CASES = [
    ("A7(153) → F5(355)", "153", "355"),
    ("A7(153) → K5(255)", "153", "255"),
    ("A6(154) → F5(355)", "154", "355"),
    ("A6(154) → K5(255)", "154", "255"),
    ("A4(156) → F5(355)", "156", "355"),
    ("A4(156) → K5(255)", "156", "255"),
    ("F4(356) → G2(348)", "356", "348"),
    ("F4(356) → G4(346)", "356", "346"),
    ("A5(155) → F5(355)", "155", "355"),
]
for nm, a, b in CASES:
    dd = d(a, b)
    tag = "在马步长度区间内" if LO - 0.5 <= dd <= HI + 0.5 else "**超出马步长度**"
    same = "同方" if a[0] == b[0] else "跨方"
    print("   %-24s d=%7.4f  %-8s %s" % (nm, dd, same, tag))

# ---------- ④ 单步网格距离对比 ----------
print()
print("=" * 84)
print("④ 用「网格步数」看：三角区的中点环与 A 行关系")
print("=" * 84)
for p in ("153", "154", "155", "156", "157"):
    nb = sorted(B.adj.get(p) or [])
    print("   %s(%s) 邻居: %s" % (p, lab(p), ", ".join("%s(%s)" % (q, lab(q)) for q in nb)))
print()
print("   A5(155) 的跨方邻居 = ", ", ".join("%s(%s)" % (q, lab(q))
      for q in sorted(B.adj["155"]) if q[0] != "1"))
print("   → 本方 row5 上**只有中点**与外界相邻；其余点均不跨方。")
