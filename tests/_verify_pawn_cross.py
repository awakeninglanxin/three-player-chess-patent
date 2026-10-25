# -*- coding: utf-8 -*-
"""兵「过河」口径专项验证（2026-09-25 · 老师报的「魏兵在 A7 走不了」）

老师原话：
  「我发现一个bug，魏国的兵在A7要过河往前走到F3，为啥走不了，是什么规则限制吗？」
  「这魏国的兵A7在没有过河（就是过祁山这个地带）之前不能横向左右行走的」

由此确立的口径（= 规则图《二、4》兵原文的正确读法）：
  · **过河 = 跨过中心地带（祁山 / 赤壁 / 荆州）进入对方领地**，
    而不是「走到本方最内层 row5」；
  · **没过河之前不能横走**；过河**之后**可以横走；
  · 过河落点 = 从本方最内层 row5 沿**纵向路线**正对的对面 row5 点
    （底边数字和恒为 10：本方列 c ⇔ 对面列 10−c）；例：魏 A7(列3) → 蜀 F3(列7)；
  · 兵**只能过一次界**。

本套同时钉住两处已修的实现偏差（它们互相掩盖，才让这个 bug 长期潜伏）：
  A. `crossed = (r0 >= 5) or (not in_own)` —— 把「走到本方 row5」当成过河，
     ⇒ A7 的兵被**错误地允许**横走 152/154；
  B. `PAWN_T` 在 `_splice_front_rays()` **之前**用原始 `B.rays` 生成
     ⇒ 只有图上真画线的 9 个 row5 点（斜边 6 + 三角区 3）带跨方通道，
       其余 18 个点（列2/3/4/6/7/8）**看不到**自己的过河落点。
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "server"))

from engine import game_dxf as GA       # noqa: E402
from engine import rules_dxf as R       # noqa: E402
from engine import geometry_dxf as G    # noqa: E402
from engine import patent as P          # noqa: E402

CN = {1: "魏", 2: "吴", 3: "蜀"}
LETTER = {(1, 1): "E", (1, 2): "D", (1, 3): "C", (1, 4): "B", (1, 5): "A",
          (2, 1): "O", (2, 2): "N", (2, 3): "M", (2, 4): "L", (2, 5): "K",
          (3, 1): "J", (3, 2): "I", (3, 3): "H", (3, 4): "G", (3, 5): "F"}
PASS = FAIL = 0


def chk(desc, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  [OK]   %s" % desc)
    else:
        FAIL += 1
        print("  [FAIL] %s   %s" % (desc, extra))


def lab(p):
    a, r, c = G.parse(p)
    return "%s%s%d" % (LETTER.get((a, r), "?"), CN.get(a, "?"), 10 - c)


def mk(board, turn=1):
    s = {"board": board, "turn": turn, "eliminated": [], "annexed": {},
         "history": [], "passed": [], "winner": None, "ply": 0, "first": 1}
    s.update(P.new_fields())
    return s


def moves(board, pos, army=1, home=None):
    """给定棋盘（含 pos 上那枚兵），返回该兵的落点（升序）"""
    s = mk(board)
    return sorted(t for f, t in R.side_moves(s, army) if f == pos)


GEN = {"115": {"kind": "general", "army": 1, "home": 1},
       "215": {"kind": "general", "army": 2, "home": 2},
       "315": {"kind": "general", "army": 3, "home": 3}}


def with_pawn(pos, army=1, home=1):
    b = dict(GEN)
    b[pos] = {"kind": "pawn", "army": army, "home": home}
    return b


print("=" * 74)
print("① 老师原场景：魏兵在 A7（= 153），要过祁山到 F3（= 357）")
print("=" * 74)
got = moves(with_pawn("153"), "153")
print("     魏兵在 %s(%s) → %s" % ("153", lab("153"), [lab(x) for x in got]))
chk("A7 的魏兵唯一正解 = 一步过河到 F3（357）", got == ["357"], "实际 %s" % got)
chk("A7 的魏兵**不可**左右横走（不含 A6/A8 = 152/154）",
    "152" not in got and "154" not in got, "实际 %s" % got)
chk("（反证）A7 与 F3 的底边数字和 = 10：7+3",
    7 + 3 == 10 and lab("153").endswith("7") and lab("357").endswith("3"),
    "%s / %s" % (lab("153"), lab("357")))

print()
print("=" * 74)
print("② 未过河不能横走 —— 本方 row5 每一列都如此")
print("=" * 74)
bad = []
for c in range(1, 10):
    p = "15%d" % c
    got = moves(with_pawn(p), p)
    horiz = [q for q in got
             if len(q) == 3 and q[0] == "1" and q[1] == "5"]      # 同行（本方 row5）
    if horiz:
        bad.append((p, horiz))
print("     本方 row5 各列（151..159）落点：")
for c in range(1, 10):
    p = "15%d" % c
    print("       %s(%s) → %s" % (p, lab(p), [lab(x) for x in moves(with_pawn(p), p)]))
chk("row5 上没有任何一点可以横走", not bad, "违规 %s" % bad)

print()
print("=" * 74)
print("③ 过河落点 = 纵向路线（底边数字和 = 10），三方对称")
print("=" * 74)
sym = []
for a in (1, 2, 3):
    for c in range(1, 10):
        p = "%d5%d" % (a, c)
        got = moves(with_pawn(p, army=a, home=a), p, army=a)
        cross = [q for q in got if q[0] != str(a)]
        want = 2 if c == 5 else 1        # 列5 = 三岔：同时正对另两方的 row5 中点
        if len(cross) != want:
            sym.append((p, cross, "期望 %d 个" % want))
            continue
        for q in cross:
            qa, qr, qc = G.parse(q)
            if not (qr == 5 and qc == 10 - c):
                sym.append((p, q, "列和=%d" % (c + qc)))
print("     样例：魏153→%s  吴253→%s  蜀354→%s"
      % (moves(with_pawn("153"), "153")[0],
         moves(with_pawn("253", 2, 2), "253", 2)[0],
         moves(with_pawn("354", 3, 3), "354", 3)[0]))
chk("row5 每点的过河落点都满足「本方列 + 对面列 = 10」（列5 是三岔，有 2 个）",
    not sym, "违规 %s" % sym)
chk("三方在 row5 上都有 9 个过河落点（9×3 = 27 条跨方通道）",
    sum(1 for a in (1, 2, 3) for c in range(1, 10)
        if [q for q in moves(with_pawn("%d5%d" % (a, c), a, a), "%d5%d" % (a, c), a)
            if q[0] != str(a)]) == 27)

print()
print("=" * 74)
print("④ 过河之后：可深入、可横走、不可再跨第三方")
print("=" * 74)
got = moves(with_pawn("357", army=1, home=1), "357", army=1)
print("     魏兵已过河、站在 %s(%s) → %s" % ("357", lab("357"), [lab(x) for x in got]))
chk("过河后能朝对方底线推进（357→347）", "347" in got, "实际 %s" % got)
chk("过河后能横走（357→356/358）", "356" in got and "358" in got, "实际 %s" % got)
chk("过河后不可朝中心退（不含 355）", "355" not in got, "实际 %s" % got)
chk("过河后不可再跨第三方（不含任何非蜀地落点）",
    all(x[0] == "3" for x in got), "实际 %s" % got)

print()
print("=" * 74)
print("⑤ 与车/炮/马共用的「战线直通」表一致（根因 B 的回归闸门）")
print("=" * 74)
mis = []
for a in (1, 2, 3):
    for c in range(1, 10):
        p = "%d5%d" % (a, c)
        ray_cross = sorted({ray[0] for ray in R.RAYS.get(p, ()) if ray and ray[0][0] != str(a)})
        pawn_cross = sorted(q for q in
                            [n[0] for n in R.PAWN_T.get(p, ())] if q[0] != str(a))
        if ray_cross != pawn_cross:
            mis.append((p, ray_cross, pawn_cross))
chk("兵在 row5 的跨方邻点 == 该点射线的跨方首点（不再漏 18 个点）",
    not mis, "不一致 %s" % mis[:4])

print()
print("=" * 74)
print("⑥ 全盘自检：非 row5 的点不该有跨方落点")
print("=" * 74)
stray = []
for p in R.B.ids:
    _, r0, _ = G.parse(p)
    if r0 == 5:
        continue
    cross = [n[0] for n in R.PAWN_T.get(p, ()) if n[0][0] != p[0]]
    if cross:
        stray.append((p, cross))
chk("row1~row4 的点都没有跨方邻点（过河只能从 row5 出发）",
    not stray, "越界 %s" % stray[:4])

# 兵的表里不该有重复项（接线/缝合会带来同首点的两条射线）
dup = [(p, [n[0] for n in v])
       for p, v in R.PAWN_T.items()
       if len(set(n[0] for n in v)) != len(v)]
chk("兵的邻点表无重复项", not dup, "重复 %s" % dup[:4])

print()
print("=" * 74)
print("合计 %d 通过 / %d 失败" % (PASS, FAIL))
print("=" * 74)
sys.exit(1 if FAIL else 0)
