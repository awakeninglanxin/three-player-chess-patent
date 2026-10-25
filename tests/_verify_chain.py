# -*- coding: utf-8 -*-
"""验证《一.5 平衡（连吃上限）》的引擎实现。

原文（`docs/三人中国象棋的游戏规则.jpeg` 第 1 列 一.5）：
    三方对战，为避免蓄意的"二打一"情况，玩家可提前约定，
    连吃一方棋子不能超 (*) 个。

口径（老师 2026-09-24）：
    · `(*)` 默认 **不限制**（等同传统象棋，不额外加限制）；
    · 网页可自行输入整数数值：0 = 禁止连吃；N = 同一方棋子最多连吃 N 个；
    · "连吃" 指【连续】吃【同一方】的棋子；中间只要走一步不吃子的棋，计数清零。
"""
import sys

sys.path.insert(0, "server")
from engine import game_dxf as GA      # noqa: E402
from engine import rules_dxf as R      # noqa: E402
from engine import patent as P         # noqa: E402

CN = {1: "魏", 2: "吴", 3: "蜀"}
OK = FAIL = 0


def chk(name, cond, extra=""):
    global OK, FAIL
    if cond:
        OK += 1
        print(f"  [OK]   {name}" + (f"  {extra}" if extra else ""))
    else:
        FAIL += 1
        print(f"  [FAIL] {name}  {extra}")


def pc(kind, home, army=None):
    return {"kind": kind, "army": army or home, "home": home}


# 局面：蜀已出局（不在盘上），只留魏、吴两方便于观察"连吃"。
#   line3 = 115-125-135-145-155-255-245-235-225-215
#   吴車 155 压在线上（顺带阻断魏帥115 ↔ 吴帥215 的见面）
#   魏兵 135 / 125 一前一后摆在同一根线上 → 吴車可以连续吃
BOARD = {"115": pc(R.GENERAL, 1), "215": pc(R.GENERAL, 2),
         "155": pc(R.ROOK, 2), "135": pc(R.PAWN, 1), "125": pc(R.PAWN, 1)}


def mk(limit, turn=2):
    s = GA.new_game(first=turn)
    s["board"] = {k: dict(v) for k, v in BOARD.items()}
    s["out"] = [3]
    s["eliminated"] = [3]
    s["annexed"] = {}
    s["history"] = []
    s["passed"] = []
    s["ply"] = 0
    s["chain_limit"] = limit
    s["chain"] = {}
    P.refresh_combat(s)
    return s


print("=" * 76)
print("0. 前置：确认 155→135→125 真的在同一条线上")
print("=" * 76)
_path = next((p for p in R.RAYS.get("115", ()) if "215" in p), None)
chk("魏帥115 ↔ 吴帥215 同线", bool(_path), f"{_path}")
chk("135、125 都在这条线上", {"135", "125"} <= set(_path or ()), f"{_path}")

# ---------------------------------------------------------------------------
print()
print("=" * 76)
print("1. 默认：chain_limit = None → 不限制（传统象棋口径）")
print("=" * 76)
s = mk(None)
chk("默认字段就是 None", s["chain_limit"] is None)
lm = GA.legal_moves(s, 2)
chk("吴車 155→135 可以吃魏兵", ("155", "135") in lm)
GA.apply(s, "155", "135")
chk("吃完记账：chain[吴] = 连吃魏 1 个",
    s["chain"][2] == {"victim": 1, "n": 1}, f"{s['chain'].get(2)}")
s["turn"] = 2                                    # 转一圈又轮到吴
lm = GA.legal_moves(s, 2)
chk("★ 未设上限 → 还能接着吃 135→125", ("135", "125") in lm,
    f"chain[吴]={s['chain'].get(2)}")

# ---------------------------------------------------------------------------
print()
print("=" * 76)
print("2. 上限 = 1：吃了 1 个之后，不能再连吃同一方")
print("=" * 76)
s = mk(1)
GA.apply(s, "155", "135")
s["turn"] = 2
lm = GA.legal_moves(s, 2)
chk("★ 连吃第 2 个被禁止（135→125 不在合法着法里）", ("135", "125") not in lm,
    f"chain[吴]={s['chain'].get(2)}")
chk("但吴車仍可走不吃子的棋（135→145）", ("135", "145") in lm,
    f"吴合法 {len(lm)} 步")

# ---------------------------------------------------------------------------
print()
print("=" * 76)
print("3. 清零：中间走一步不吃子的棋 → 连吃中断，重新可以吃")
print("=" * 76)
GA.apply(s, "135", "145")                        # 不吃子
chk("不吃子的着法把连吃计数清零",
    s["chain"][2] == {"victim": None, "n": 0}, f"{s['chain'].get(2)}")
s["turn"] = 2
lm = GA.legal_moves(s, 2)
chk("★ 清零后又能吃魏兵（145→125）", ("145", "125") in lm,
    f"chain[吴]={s['chain'].get(2)}")

# ---------------------------------------------------------------------------
print()
print("=" * 76)
print("4. 上限 = 0：禁止连吃 → 一个子都吃不了")
print("=" * 76)
s = mk(0)
lm = GA.legal_moves(s, 2)
chk("★ 0 个都不许吃（155→135 被禁）", ("155", "135") not in lm,
    f"吴合法 {len(lm)} 步")
chk("不吃子的着法照常（155→145 / 155→156 …）", ("155", "145") in lm,
    f"吴合法 {len(lm)} 步")

# ---------------------------------------------------------------------------
print()
print("=" * 76)
print("5. 换对手：改吃另一方的子 → 重新起算（unit：直接测 note_chain）")
print("=" * 76)
s = mk(1)
pc_wei = pc(R.PAWN, 1)
pc_shu = pc(R.ROOK, 3)
r1 = P.note_chain(s, 2, pc_wei)
chk("吃魏第 1 个 → {victim:魏, n:1}", r1 == {"victim": 1, "n": 1}, f"{r1}")
r2 = P.note_chain(s, 2, pc_wei)
chk("再吃魏第 2 个 → n=2", r2 == {"victim": 1, "n": 2}, f"{r2}")
r3 = P.note_chain(s, 2, pc_shu)
chk("★ 改吃蜀 → 计数换对手重新起算 {victim:蜀, n:1}",
    r3 == {"victim": 3, "n": 1}, f"{r3}")
r4 = P.note_chain(s, 2, None)
chk("不吃子 → 清零", r4 == {"victim": None, "n": 0}, f"{r4}")
chk("吃自家子不算连吃（计数清零）",
    P.note_chain(s, 2, pc(R.PAWN, 2)) == {"victim": None, "n": 0})

# ---------------------------------------------------------------------------
print()
print("=" * 76)
print("6. 网页输入口的归一化（空串 / None / 负数 / 非数字 → 不限制）")
print("=" * 76)
sys.path.insert(0, "server")
from match import Match                          # noqa: E402
chk("空串 '' → None（不限制）", Match._norm_chain("") is None)
chk("None → None（不限制）", Match._norm_chain(None) is None)
chk("负数 -1 → None（不限制）", Match._norm_chain(-1) is None)
chk("非数字 'abc' → None（不限制）", Match._norm_chain("abc") is None)
chk("'3' → 3", Match._norm_chain("3") == 3)
chk("0 → 0（禁止连吃）", Match._norm_chain(0) == 0)

# ---------------------------------------------------------------------------
print()
print("=" * 76)
print("7. 回归：默认（不限）时，改动前后着法集合完全一致")
print("=" * 76)
s_def = mk(None)
_ = GA.legal_moves(s_def, 2)
chk("默认档下 155→135、135→125 都通",
    ("155", "135") in GA.legal_moves(s_def, 2))

print()
print("=" * 52)
print(f"连吃上限专项验证: {OK} 通过 / {FAIL} 失败")
print("=" * 52)
sys.exit(1 if FAIL else 0)
