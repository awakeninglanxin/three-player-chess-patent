# -*- coding: utf-8 -*-
"""探针：《一、9》第 3 条「C 不可吃 B 的帅」在老师给的例子上怎么落地

老师例子：E5(115) / O5(215) / I5(325) —— 三点同在列5 贯通纵线上。
        「O5和I5有自己方的主帅和副帅，若此时轮到E5这方下棋，
          在E5的敌方帅就不能吃 O5 或 I5 的帅」

角色分配有多种可能，全跑一遍（这一步不能猜）：
  情形甲  ：O5(215)=吴副帅(吴出局) **归魏控制** → 对魏是"自家子"
  情形甲2 ：O5(215)=吴副帅(吴出局) **归蜀控制** → 对魏是"敌子"  ★关键
  情形乙  ：O5(215)=吴主帅(在局)，I5(325)=蜀副帅(蜀出局)
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "server"))

from engine import geometry_dxf as D        # noqa: E402
from engine import rules_dxf as R           # noqa: E402
from engine import game_dxf as GA           # noqa: E402

CN = {1: "魏", 2: "吴", 3: "蜀"}


def mk(pieces, turn=1, out=()):
    s = GA.new_game(first=turn)
    s["board"] = {p: dict(v) for p, v in pieces.items()}
    s["ply"] = 0
    s["history"] = []
    s["out"] = list(out)
    s["eliminated"] = list(out)
    return s


def show(tag, s, actors=("115", "215", "325")):
    print("=" * 76)
    print(tag)
    print("=" * 76)
    for p, v in sorted(s["board"].items()):
        ex = " 副帅" if v.get("deputy") else ""
        print(f"    {p}: kind={v['kind']} 控制方={CN[v['army']]} 代表原方={CN[v['home']]}{ex}")
    print(f"  out = {s['out']}  alive = {[CN[a] for a in GA.alive_armies(s)]}")
    print("  照见矩阵（1=共线且中间无子）：")
    print("        " + "  ".join(f"{q:>5}" for q in actors))
    for p in actors:
        row = []
        for q in actors:
            row.append("   — " if p == q else f"   {'1' if R.line_of_sight(s, p, q) else '0'} ")
        print(f"    {p} " + " ".join(row))
    print(f"  generals_facing（只统计非副帅）= {R.generals_facing(s)}")
    print(f"  facing_pairs                   = {[sorted(x) for x in GA.facing_pairs(s)]}")
    print(f"  protected_out_generals         = {GA.protected_out_generals(s)}")
    print(f"  snipe_pairs                    = {GA.snipe_pairs(s)}")
    print("  各方合法着法与能否吃：")
    for a in (1, 2, 3):
        L = [(x, y) for x, y in GA.legal_moves(s, a)]
        eat = sorted(y for x, y in L if y in ("215", "325"))
        print(f"    {CN[a]}方 {len(L):2d} 步；可吃 {'/'.join(eat) if eat else '（无）'}"
              f"   全部落点={sorted(y for x, y in L)}")
    print()


# ------------------------------------------------------------ 情形甲
s = mk({"115": {"kind": "general", "army": 1, "home": 1},
        "215": {"kind": "general", "army": 1, "home": 2, "deputy": True},
        "325": {"kind": "general", "army": 3, "home": 3}}, 1, out=[2])
show("情形甲：O5(215)=吴副帅（吴出局）**归魏控制** ｜ I5(325)=蜀主帅（在局）｜ 轮到魏", s)

# ------------------------------------------------------------ 情形甲2（关键）
s = mk({"115": {"kind": "general", "army": 1, "home": 1},
        "215": {"kind": "general", "army": 3, "home": 2, "deputy": True},
        "325": {"kind": "general", "army": 3, "home": 3}}, 1, out=[2])
show("情形甲2：O5(215)=吴副帅（吴出局）**归蜀控制**（=魏的敌子）｜ I5(325)=蜀主帅 ｜ 轮到魏", s)

# ------------------------------------------------------------ 情形乙
s = mk({"115": {"kind": "general", "army": 1, "home": 1},
        "215": {"kind": "general", "army": 2, "home": 2},
        "325": {"kind": "general", "army": 2, "home": 3, "deputy": True}}, 1, out=[3])
show("情形乙：O5(215)=吴主帅（在局）｜ I5(325)=蜀副帅（蜀出局，归吴）｜ 轮到魏", s)

# ------------------------------------------------------------ 情形丙：出局方帅与第三方都照见
print("=" * 76)
print("情形丙：吴已出局，吴副帅 215 归蜀；魏帥 115 与它照见（第三方 = 魏）")
print("        —— 这正是第 3 条要拦的场面：第三方便宜行事")
print("=" * 76)
s = mk({"114": {"kind": "general", "army": 1, "home": 1},               # 魏帥 E6（列4，与215不共线）
        "215": {"kind": "general", "army": 3, "home": 2, "deputy": True},  # 吴副帅（吴出局）归蜀
        "155": {"kind": "rook", "army": 1, "home": 1},                  # 魏車 A5（列5，够得着 215）
        "325": {"kind": "general", "army": 3, "home": 3}}, 1, out=[2])  # 蜀帥 I5（与 215 照见）
print(f"  protected_out_generals = {GA.protected_out_generals(s)}")
print("  （key = 出局方帅的点位；value = 允许吃它的在局方集合）")
print(f"  蜀帥 325 与 215 照见? {R.line_of_sight(s, '325', '215')}")
print(f"  魏帥 114 与 215 照见? {R.line_of_sight(s, '114', '215')}")
L1 = [(x, y) for x, y in GA.legal_moves(s, 1)]
L3 = [(x, y) for x, y in GA.legal_moves(s, 3)]
print(f"  魏方着法 = {sorted(L1)}")
print(f"  ★ 魏車 155 能吃 215 吗?    {'215' in [y for x, y in L1 if x == '155']}"
      f"   ← 第三方 C 应被拦")
print(f"  蜀帥 325 能吃(射杀) 215 吗? {'215' in [y for x, y in L3 if x == '325']}"
      f"   ← A 应被允许")
