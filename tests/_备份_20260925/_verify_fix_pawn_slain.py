# -*- coding: utf-8 -*-
"""验证 2026-09-24 的两处修复：

  ① 兵「过界后不能深入敌境」（老师报的「兵不会过河」）
  ② 「吃帅的棋子原地不动 + 军帐另造副帅」→ 盘上棋子数不守恒
     （老师报的「帅被吃了，场上却还冒出个帅 / 帅没从棋盘消失」）
  ③ 吃「副帅」被误报成「斩某方主帅」（eliminated）
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


def pawn_moves(board, pos):
    s = mk(board)
    return [t for f, t in R.side_moves(s, 1) if f == pos]


GEN = {"115": {"kind": "general", "army": 1, "home": 1},
       "215": {"kind": "general", "army": 2, "home": 2},
       "315": {"kind": "general", "army": 3, "home": 3}}


def with_pawn(pos, army=1, home=1):
    b = dict(GEN)
    b[pos] = {"kind": "pawn", "army": army, "home": home}
    return b


print("=" * 70)
print("① 兵：过界后应能继续深入敌境")
print("=" * 70)
got = pawn_moves(with_pawn("255"), "255")     # 魏兵站在吴营点（吴 row5 列5）
print("     魏兵在 %s(%s) → %s" % ("255", lab("255"), [lab(x) for x in got]))
chk("兵在敌境 row5 能朝敌底线推进（255→245）", "245" in got, "实际 %s" % got)
chk("兵在敌境 row5 能横走（255→254/256）",
    "254" in got and "256" in got, "实际 %s" % got)
chk("兵在敌境不能再跨到第三方（255→155/355 均不许）",
    "155" not in got and "355" not in got, "实际 %s" % got)

got = pawn_moves(with_pawn("245"), "245")     # 吴 row4 列5
print("     魏兵在 %s(%s) → %s" % ("245", lab("245"), [lab(x) for x in got]))
chk("兵在敌境纵深能继续推进（245→235）", "235" in got, "实际 %s" % got)
chk("兵在敌境不可朝中心退（245→255 不许）", "255" not in got, "实际 %s" % got)

got = pawn_moves(with_pawn("359"), "359")     # 魏兵在蜀 row5 列9
print("     魏兵在 %s(%s) → %s" % ("359", lab("359"), [lab(x) for x in got]))
chk("兵从脖颈过界后能深入蜀境（359→349）", "349" in got, "实际 %s" % got)

print()
print("=" * 70)
print("② 本方领地内的兵：向心前进不变；**row5 未过河不再横走**（老师 2026-09-25 修正）")
print("=" * 70)
got = pawn_moves(with_pawn("141"), "141")
chk("兵141（本方行4）只有向前一格 151", got == ["151"], "实际 %s" % got)
got = pawn_moves(with_pawn("151"), "151")
print("     魏兵在 %s(%s) → %s" % ("151", lab("151"), [lab(x) for x in got]))
# 【老师 2026-09-25】「兵没过河（没过地带）之前不能横向左右行走」
chk("兵151（本方 row5 **未过河**）不可横走 152", "152" not in got, "实际 %s" % got)
chk("兵151 唯一正解 = 过河（跨祁山）到蜀 359", got == ["359"], "实际 %s" % got)
chk("兵151 不回头（不含 141）", "141" not in got, "实际 %s" % got)

print()
print("=" * 70)
print("③ 斩帅：吃帅的棋子原样留在落点，被斩方的帅易主进驻本方军帐（子数不变）")
print("=" * 70)
b = {"115": {"kind": "general", "army": 1, "home": 1},
     "215": {"kind": "general", "army": 2, "home": 2},
     "315": {"kind": "general", "army": 3, "home": 3},
     "235": {"kind": "rook", "army": 2, "home": 2},      # 吴车，在列5 上
     "334": {"kind": "advisor", "army": 3, "home": 3}}   # 蜀士（占军帐一角）
s = mk(b, turn=2)
n_before = len(s["board"])
note = GA.apply(s, "235", "315")            # 吴车 从 235 冲到 315 吃蜀帅
n_after = len(s["board"])
print("     吃帅前子数=%d  吃帅后子数=%d" % (n_before, n_after))
print("     盘上 general：%s" % [(p, lab(p), CN[pc["army"]],
                                 "副帅" if pc.get("deputy") else "主帅")
                                for p, pc in s["board"].items()
                                if pc["kind"] == "general"])
chk("吃帅前后子数守恒（-1：被吃的是蜀帅）", n_after == n_before - 1,
    "%d → %d" % (n_before, n_after))
chk("吃帅的车已离开原位置 235", "235" not in s["board"], "235 仍在盘上")
# 【最终口径 · 《一、7》原文（老师 2026-09-25「退回原先的方式」）】
#   吃帅的那枚棋子**就地升格**为副帅、原棋子从盘上消失 ⇒ 315 上就是那枚副帅。
chk("315 上就地升格为副帅（吃帅的吴車换身份占位；不是被吃空、也不是挪到军帐中心）",
    (s["board"].get("315") or {}).get("deputy") is True,
    "315 = %r" % (s["board"].get("315"),))
chk("军帐中心 325 **没有**凭空出现副帅", "325" not in s["board"])
dep = [p for p, pc in s["board"].items() if pc.get("deputy")]
chk("盘上出现了 1 枚副帅", len(dep) == 1, "实际 %s" % dep)
chk("★ 战报记录升格前的棋子种类 promoted_from=rook（前端显示「车→副帥」）",
    note.get("promoted_from") == "rook", "实际 %r" % note.get("promoted_from"))
chk("note.eliminated = 蜀(3)（真·主帅）", note.get("eliminated") == 3,
    "实际 %r" % note.get("eliminated"))
chk("note.is_deputy = False", note.get("is_deputy") is False,
    "实际 %r" % note.get("is_deputy"))

print()
print("=" * 70)
print("④ 吃副帅：绝不能报「斩某方主帅」")
print("=" * 70)
s2 = mk({
    "125": {"kind": "general", "army": 2, "home": 1, "deputy": True},
    "215": {"kind": "general", "army": 2, "home": 2},
    "315": {"kind": "general", "army": 3, "home": 3},
    "135": {"kind": "rook", "army": 3, "home": 3},
}, turn=3)
s2["deputies"] = {1: {"pos": "125", "owner": 2}}
s2["eliminated"] = [1]
s2["out"] = [1]
s2["vitality"][1] = False
s2["combat"][1] = False
P.refresh_combat(s2)
n2 = GA.apply(s2, "135", "125")
print("     note = %r" % n2)
chk("吃副帅时 note 不含 eliminated", "eliminated" not in n2,
    "实际 %r" % n2.get("eliminated"))
chk("吃副帅时 note.is_deputy = True", n2.get("is_deputy") is True,
    "实际 %r" % n2.get("is_deputy"))

print()
print("=" * 70)
print("结果：%d 通过 / %d 失败" % (PASS, FAIL))
print("=" * 70)
sys.exit(1 if FAIL else 0)
