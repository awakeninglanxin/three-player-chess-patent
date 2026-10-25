# -*- coding: utf-8 -*-
"""⚠️【已作废，勿作依据】几何探针：三角区回跳 6 对的「原文配对」与「几何配对」是否一致。

【2026-09-24 老师裁定】本脚本的**前提**就是错的：它拿"距离更近"当判据去
"验证"原文配对。老师说：「不要算距离，算数走了几个格点，因为这棋盘不是像
中国象棋那样方正的格子。**A6→F5 距离 33.93（近）这是错的，不能这么走**」。
原文是 **6 对穷举**，不需要、也不允许用几何去验证/推导。

本文件保留仅作**反面教材**。它的输出曾被误当成"引擎 _REBOUND_SELF 配反了"的证据，
实际上配反的正是本脚本自己 —— 它把 `156` 标成了 `A4`（实为 `A6`，见下），
再用距离替它挑了个"更近"的邻方。

正确口径：图中数字 d = 10 − 引擎列；6 对为
    `156(A4)↔355(F5)`、`154(A6)↔255(K5)`、`356(F4)↔255(K5)`
    `354(F6)↔155(A5)`、`256(K4)↔155(A5)`、`254(K6)↔355(F5)`

----------------------------------------------------------------
（以下是原脚本，未改动）

规则原文（docs/三人中国象棋的游戏规则.md §二.1）：
    A5 空时：A4↔F5、A6↔K5
    F5 空时：F4↔K5、F6↔A5
    K5 空时：K4↔A5、K6↔F5

引擎 _REBOUND_SELF 实际给出的配对相反（本脚本验证）。
这里用 DXF 几何坐标独立算距离，看哪一种更「顺」。
"""
import math
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "server"))

from engine import geometry_dxf as G
from engine import rules_dxf as R

B = G.BOARD
LETTER = {"2-1": "O", "2-2": "N", "2-3": "M", "2-4": "L", "2-5": "K",
          "1-1": "E", "1-2": "D", "1-3": "C", "1-4": "B", "1-5": "A",
          "3-1": "J", "3-2": "I", "3-3": "H", "3-4": "G", "3-5": "F"}
P2L = {}
for key, ch in LETTER.items():
    a_s, r_s = key.split("-")
    for digit in range(1, 10):
        P2L["%s%s%d" % (a_s, r_s, 10 - digit)] = "%s%s" % (ch, digit)


def lab(p):
    return P2L.get(p) or ("?%s" % p)


def pt(p):
    return B.xy[p]


def d(a, b):
    pa, pb = pt(a), pt(b)
    return math.hypot(pa[0] - pb[0], pa[1] - pb[1])


print("=" * 80)
print("① 相关点位的几何坐标")
print("=" * 80)
for p in ("153", "154", "155", "156", "157", "255", "355", "254", "354", "256", "356"):
    x, y = pt(p)
    print("  %s(%-3s) = (%.3f, %.3f)" % (p, lab(p), x, y))

print()
print("=" * 80)
print("② 三角区 3 条边（中点系互连）")
print("=" * 80)
for a, b in [("155", "355"), ("355", "255"), ("255", "155")]:
    print("  %s(%s) ↔ %s(%s)   d = %.4f" % (a, lab(a), b, lab(b), d(a, b)))
print("  （对照：A 行相邻点距 = %.4f，B 行相邻 = %.4f）"
      % (d("155", "154"), d("145", "144")))

print()
print("=" * 80)
print("③ 关键：A4 / A6 到两个对面中点的距离")
print("=" * 80)
for src in ("156", "154"):
    print("  %s(%s):" % (src, lab(src)))
    for tgt in ("355", "255"):
        print("       → %s(%s)   d = %.4f" % (tgt, lab(tgt), d(src, tgt)))

print()
print("=" * 80)
print("④ 三角区边的「方向」：A5 分别朝 A4 侧 / A6 侧 的夹角")
print("=" * 80)
import math as _m


def ang(o, a, b):
    """∠(o→a, o→b) 度数"""
    po, pa, pb = pt(o), pt(a), pt(b)
    v1 = (pa[0] - po[0], pa[1] - po[1])
    v2 = (pb[0] - po[0], pb[1] - po[1])
    n1 = _m.hypot(*v1)
    n2 = _m.hypot(*v2)
    cosv = max(-1.0, min(1.0, (v1[0] * v2[0] + v1[1] * v2[1]) / (n1 * n2)))
    return _m.degrees(_m.acos(cosv))


print("  A5(155) 为原点：")
print("     ∠(A5→A4, A5→F5) = %.2f°" % ang("155", "156", "355"))
print("     ∠(A5→A4, A5→K5) = %.2f°" % ang("155", "156", "255"))
print("     ∠(A5→A6, A5→F5) = %.2f°" % ang("155", "154", "355"))
print("     ∠(A5→A6, A5→K5) = %.2f°" % ang("155", "154", "255"))
print("     ∠(A5→F5, A5→K5) = %.2f°  ← 三角区夹角" % ang("155", "355", "255"))

print()
print("=" * 80)
print("⑤ 原文配对 vs 引擎配对")
print("=" * 80)
ORIG = {  # 原文：(起点, 落点)
    "156": "355", "154": "255",   # A4↔F5, A6↔K5
    "356": "255", "354": "155",   # F4↔K5, F6↔A5
    "256": "155", "254": "355",   # K4↔A5, K6↔F5
}
# 引擎实际落点
ENG = {}
for p, lst in R.REBOUND.items():
    if p in ORIG:
        ENG[p] = lst[0][1]          # (腿, 落点)
print("  %-16s %-14s %-14s %-8s %-8s" % ("起点", "原文落点", "引擎落点", "原文d", "引擎d"))
bad = 0
for p, want in ORIG.items():
    got = ENG.get(p, "?")
    mark = "OK" if got == want else "✗错"
    if got != want:
        bad += 1
    print("  %-16s %-14s %-14s %-8.3f %-8.3f %s"
          % ("%s(%s)" % (p, lab(p)), "%s(%s)" % (want, lab(want)),
             "%s(%s)" % (got, lab(got)), d(p, want), d(p, got), mark))
print()
print("  与原文不符的条数 = %d / 6" % bad)
