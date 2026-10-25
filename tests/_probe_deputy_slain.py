# -*- coding: utf-8 -*-
"""探针：吃「副帅」会不会被误报成「斩某方主帅」？

背景（老师 2026-09-24 的疑问）：
  「有时候帅被吃了……屏幕显示此方将被杀出局」

可疑链路：
  game_dxf.apply() 里
      if victim and victim["kind"] == R.GENERAL:
          note["eliminated"] = victim["home"]     # ← 副帅也是 general！
  而 match.step() 里同样不区分：
      if victim["kind"] == R.GENERAL: self.slain[army] += 1
  前端 web/app.js 又写成
      e.eliminated ? '斩帥 X方主帅' : e.is_deputy ? '斩副帅' : ...
  → eliminated 优先，副帅被吃也会显示「斩帥 X方主帅」。
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


def lab(p):
    a, r, c = G.parse(p)
    return "%s%s%d" % (LETTER.get((a, r), "?"), CN.get(a, "?"), 10 - c)


def mk(board, turn):
    s = {"board": board, "turn": turn, "eliminated": [], "annexed": {},
         "history": [], "passed": [], "winner": None, "ply": 0, "first": 1}
    s.update(P.new_fields())
    return s


def tag_of(pc):
    return "副帅" if pc.get("deputy") else "主帅"


def main():
    # 魏主帅已被斩 → 魏军帐 125 上驻着「吴方副帅」(deputy=True, home=1)
    s = mk({
        "125": {"kind": "general", "army": 2, "home": 1, "deputy": True},
        "215": {"kind": "general", "army": 2, "home": 2},
        "315": {"kind": "general", "army": 3, "home": 3},
        "135": {"kind": "rook", "army": 3, "home": 3},     # 蜀车，与副帅同列
    }, turn=3)
    s["deputies"] = {1: {"pos": "125", "owner": 2}}
    s["eliminated"] = [1]
    s["out"] = [1]
    s["vitality"][1] = False
    s["combat"][1] = False
    P.refresh_combat(s)

    print("=" * 68)
    print("场景：魏已被斩帅出局；魏军帐 125 上驻着吴方【副帅】")
    print("=" * 68)
    gens = [(p, lab(p), CN[pc["army"]], tag_of(pc))
            for p, pc in s["board"].items() if pc["kind"] == "general"]
    print("  盘上 general 单位：")
    for g in gens:
        print("     %-5s %-6s 归属=%s  %s" % g)

    print()
    print("  蜀车 135 → 125 是 legal_moves 内吗：",
          ("135", "125") in GA.legal_moves(s, army=3))

    note = GA.apply(s, "135", "125")
    print()
    print("  ── apply() 返回的 note ──")
    for k, v in note.items():
        print("     %-16s = %r" % (k, v))
    print()
    if note.get("eliminated"):
        print("  ⚠️ 命中旧 bug：被吃的明明是【副帅】，note['eliminated'] 仍被设成",
              CN.get(note["eliminated"]))
        print("     → match.step() 会 slain[3] += 1 → 综合分白送 1000 分")
        print("     → 前端会渲染成「斩帥 %s方主帅」" % CN.get(note["eliminated"]))
        print("     【2026-09-24 已修】若本行出现，说明修复被回退了，请检查")
        print("       game_dxf.apply() 里的 `if victim.get('deputy')` 分支。")
    else:
        print("  ✅ 未命中：note 不含 eliminated  （走的是 is_deputy=True）")
        print("     —— 这是 2026-09-24 修复后的**正确**行为。")

    print()
    print("  ── 对照：真·主帅被吃时的 note ──")
    s2 = mk({
        "115": {"kind": "general", "army": 1, "home": 1},
        "215": {"kind": "general", "army": 2, "home": 2},
        "315": {"kind": "general", "army": 3, "home": 3},
        "125": {"kind": "rook", "army": 3, "home": 3},
    }, turn=3)
    n2 = GA.apply(s2, "125", "115")
    print("     eliminated=%r  is_deputy=%r  captured=%r"
          % (n2.get("eliminated"), n2.get("is_deputy"), n2.get("captured")))
    print("     → 真主帅：eliminated=%s（正确）" % CN.get(n2.get("eliminated")))

    print()
    print("  ── 副帅参与照面判定吗 ──")
    print("     generals_facing =", R.generals_facing(s), "（副帅不参与，正确）")


if __name__ == "__main__":
    main()
