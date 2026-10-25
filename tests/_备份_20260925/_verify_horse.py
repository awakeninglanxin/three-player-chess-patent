# -*- coding: utf-8 -*-
"""马步口径验证：传统「日」8 步（**数格点数**）。

判据 = 数格点数：一个方向走 **1 格** + 另一方向走 **2 格**
       → (Δr,Δc) ∈ {(±1,±2), (±2,±1)}，共 8 个落点。
规则依据 = docs/三人中国象棋的游戏规则.md §二.1 原文：
  「马在其它地方行进方式与传统象棋行进方式（**起、终点相对坐标**）完全相符」
  （「相对坐标」= (行,列) 拓扑网格，与格子是 90° 还是 120° 无关。）

为什么要独立成脚本：`tests/test_dxf.py` 的 §4 覆盖蹩腿语义，
本脚本专门盯「步法本身对不对」，含**全盘一致性**检查。

跑法：cd 中国三人象棋_专利版 && python tests/_verify_horse.py
"""
import os
import sys
import collections

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "server"))

from engine import geometry_dxf as G          # noqa: E402
from engine import rules_dxf as R            # noqa: E402

B = G.BOARD
ok = bad = 0


def chk(name, cond, detail=""):
    global ok, bad
    if cond:
        ok += 1
        print("  [OK]   %s" % name)
    else:
        bad += 1
        print("  [FAIL] %s  %s" % (name, detail))


def delta(a, b):
    """两个引擎点位号 → (Δ行, Δ列)"""
    _a, r1, c1 = G.parse(a)
    _b, r2, c2 = G.parse(b)
    return r2 - r1, c2 - c1


def shape(a, b):
    """→ 排序后的 (|Δ行|, |Δ列|)"""
    dr, dc = delta(a, b)
    return tuple(sorted((abs(dr), abs(dc))))


print("=" * 76)
print("一、HORSE_MOVES 定义（数格点数口径）")
print("=" * 76)
chk("HORSE_MOVES 恰 8 步", len(R.HORSE_MOVES) == 8, "实际 %d 步" % len(R.HORSE_MOVES))
chk("8 步全部满足「一个方向 1 格 + 另一方向 2 格」",
    all(sorted((abs(a), abs(b))) == [1, 2] for a, b in R.HORSE_MOVES),
    "实际 %s" % (R.HORSE_MOVES,))
chk("8 步两两不重复", len(set(R.HORSE_MOVES)) == 8)
chk("UNIT_DIRS = 4 邻域（行 ±1、列 ±1）",
    set(R.UNIT_DIRS) == {(0, 1), (0, -1), (1, 0), (-1, 0)}, "实际 %s" % (R.UNIT_DIRS,))

print()
print("=" * 76)
print("二、全盘一致性：每个马位的落点位移必须都是 {1,2}")
print("=" * 76)
LETTER = {1: "ABCDE", 2: "ONMLK", 3: "JIHGF"}
off_grid = []           # 同方内部但位移不是 {1,2} 的落点
cross = 0               # 跨方（三角区回跳）
tot = 0
for a in (1, 2, 3):
    for r in range(1, 6):
        for c in range(1, 10):
            p = "%d%d%d" % (a, r, c)
            if p not in B.ids:
                continue
            for _leg, d in R.HORSE_T[p]:
                tot += 1
                if G.parse(d)[0] != a:
                    cross += 1          # 三角区回跳（独立条款）
                    continue
                if shape(p, d) != (1, 2):
                    off_grid.append((p, d, shape(p, d)))
chk("全盘常规马步的位移**全部**是 (1格+2格)",
    not off_grid, "越格步 %d 个，例：%s" % (len(off_grid), off_grid[:5]))
print("        （全盘共 %d 个马步，其中跨方三角区回跳 %d 个）" % (tot, cross))

print()
print("=" * 76)
print("三、马腿唯一性（传统「日」的指纹）")
print("=" * 76)
multi = []
for p in B.ids:
    for d, legs in R.HORSE_LEG.get(p, {}).items():
        if len(legs) > 1:
            multi.append((p, d, legs))
chk("全盘每个落点的腿都唯一（多腿 0 个）", not multi, "多腿 %d 个：%s" % (len(multi), multi[:5]))

pair = R.HORSE_LEG["112"]
chk("馬112：腿 122 管两个**对称**落点 131 与 133",
    set(pair) == {"124", "131", "133"} and pair["131"] == pair["133"] == ("122",),
    "实际 %s" % (pair,))

print()
print("=" * 76)
print("四、三角区回跳（原文 6 对穷举，独立条款）")
print("=" * 76)
CASES = [("156", "355"), ("154", "255"), ("356", "255"),
         ("354", "155"), ("256", "155"), ("254", "355")]
LEG = {"156": "155", "154": "155", "356": "355",
       "354": "355", "256": "255", "254": "255"}
miss = [(_p, _q) for _p, _q in CASES if _q not in [d for _l, d in R.HORSE_T[_p]]]
chk("6 对回跳全部存在", not miss, "缺失 %s" % (miss,))
chk("6 对全部双向（REBOUND 表 12 个方向）",
    all((LEG[_p], _q) in R.REBOUND.get(_p, ()) and (LEG[_p], _p) in R.REBOUND.get(_q, ())
        for _p, _q in CASES),
    "实际 %s" % sorted((k, len(v)) for k, v in R.REBOUND.items()))
chk("回跳落点都是跨方（不是常规 8 步）",
    all(G.parse(_q)[0] != G.parse(_p)[0] for _p, _q in CASES),
    "实际 %s" % [(p, q) for p, q in CASES if G.parse(q)[0] == G.parse(p)[0]])

print()
print("=" * 76)
print("马步验证：%d 通过 / %d 失败" % (ok, bad))
print("=" * 76)
sys.exit(1 if bad else 0)
