# -*- coding: utf-8 -*-
"""探针：**副帅能不能吃（射杀）对方主帅？**

回答老师 2026-10-02 在对弈台的质疑：
  「副帅应该是不能吃主帅的吧？原先规则有说副帅能吃主帅吗？」

本探针**只做实测**（不引用任何推理），用的就是老师那一局的真实点位：

  对弈台 ply 63 → ply 64 的战报：
    army=3  225 → 115  captured=general  captured_army=1
    eliminated=1  is_deputy=False  promoted_from='general'
  · 225 = 蜀方控制的副帅（驻吴军帐，home=2）
  · 115 = 魏方主帅（驻魏军帐，home=1）
  · 这是**跨军帐**位移 ⇒ 普通走法（军帐内 1 格）绝无可能 ⇒ 只可能是射杀

要钉死的四件事：
  ① 引擎**当前**允不允许「副帅 → 射杀 → 对方主帅」？（legal_moves 实测）
  ② 这条路是「走过去吃」还是「沿见面线射杀」？（用 GEN_T / RAYS 区分）
  ③ 中间有子是否被挡？（射杀的边界）
  ④ 与「主帅射杀主帅」「副帅射杀副帅」是否**同口径**？（因为共用 `_general()`）

⚠️ 本探针的结论只描述**引擎现状**，不代表"规则原文这么写"。
   原文口径与现行规则的差别见 `docs/三人中国象棋的游戏规则.md` §7 / §9
   与 `docs/专利版规则.md` §5.13。
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, os.path.join(_ROOT, "server"))

from engine import game_dxf as GA      # noqa: E402
from engine import rules_dxf as R      # noqa: E402
from engine import patent as P         # noqa: E402

GENERAL, ROOK, PAWN = R.GENERAL, R.ROOK, R.PAWN
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


def pc(kind, home, army=None, **kw):
    d = {"kind": kind, "army": army or home, "home": home}
    d.update(kw)
    return d


def mk(board, turn=1, out=()):
    s = GA.new_game(first=turn)
    s["board"] = {k: dict(v) for k, v in board.items()}
    s["eliminated"] = list(out)
    s["out"] = list(out)
    s["annexed"] = {}
    s["history"] = []
    s["passed"] = []
    s["ply"] = 0
    P.refresh_combat(s)
    return s


def moves_of(s, army):
    return [tuple(m) for m in GA.legal_moves(s, army)]


# 与 `web/board.js` 的 coordLabel() 同口径：LETTER[方][5−行] + (10−列)
# （`letters` 与引擎 `LETTER` 必须一致，故就地复制一份，避免探针依赖前端文件）
LETTER = {1: "ABCDE", 2: "KLMNO", 3: "FGHIJ"}


def coord_label(p):
    army, row, col = R.RC[p]
    return f"{LETTER[army][5 - row]}{10 - col}"


print("=" * 78)
print("0. 坐标核对：老师那局的 225 / 115 到底在哪")
print("=" * 78)
for p in ("115", "125", "135", "215", "225", "235", "315", "325", "335"):
    print(f"   引擎 {p}  =  {coord_label(p)}   "
          f"(方{R.RC[p][0]} 行{R.RC[p][1]} 列{R.RC[p][2]})")
chk("225 在吴军帐内（home=2 的行1..3 × 列4..6）",
    R.RC["225"][1] in (1, 2, 3) and R.RC["225"][2] in (4, 5, 6))
chk("115 在魏军帐内", R.RC["115"][1] in (1, 2, 3) and R.RC["115"][2] in (4, 5, 6))
chk("225 与 115 **同在列5**（射杀线的前提）",
    R.RC["225"][2] == R.RC["115"][2] == 5)

# ---------------------------------------------------------------------------
print()
print("=" * 78)
print("1. ★ 实测：蜀方副帅在 225，魏方主帅在 115 —— 能不能吃？")
print("=" * 78)

BD_A = {
    "115": pc(GENERAL, 1, 1),                  # 魏方【主帅】
    "225": pc(GENERAL, 2, 3, deputy=True),     # 蜀方【副帅】（驻吴军帐 home=2）
    "315": pc(GENERAL, 3, 3),                  # 蜀方自己的主帅（保持三方完整）
}
sA = mk(BD_A, turn=3)

chk("『照见』成立 —— line_of_sight(225, 115) = True",
    bool(R.line_of_sight(sA, "225", "115")))
chk("snipe_targets(225, 蜀) 含 '115'（纯拓扑判据）",
    "115" in list(R.snipe_targets(sA["board"], "225", 3, frozenset())))
mvA = moves_of(sA, 3)
chk("★★ 蜀方 legal_moves **含** ('225','115') ⇒ 引擎允许副帅射杀主帅",
    ("225", "115") in mvA,
    f"蜀方共 {len(mvA)} 手")
chk("snipe_pairs 含 ('225','115')（前端标红 / 将军告警同源）",
    ("225", "115") in [tuple(x) for x in GA.snipe_pairs(sA)])

# ② 这条路是射杀还是走法？
gen_225 = list(R.GEN_T.get((2, "225"), ()))
print()
print(f"   副帅 225 的【军帐内 1 格走法】GEN_T[(吴,'225')] = {gen_225}")
chk("★ '115' **不在**军帐内 1 格走法里 ⇒ 225→115 不是『走过去吃』",
    "115" not in gen_225)
chk("★ 因此 225→115 只能来自【射杀】分支（snipe_targets）",
    "115" in list(R.snipe_targets(sA["board"], "225", 3, frozenset())))

# ---------------------------------------------------------------------------
print()
print("=" * 78)
print("2. 射杀的边界：中间有子就断（沿列5 找一个真正挡路的点）")
print("=" * 78)

mid = None
path_with_115 = None
for q in R.RAYS.get("225") or ():
    if "115" in q:                                 # ★ 必须找**含 115 的那条**射线
        path_with_115 = list(q)                    # 注意：路径**不含起点**，是纯落点序列
        break
if path_with_115:
    i115 = path_with_115.index("115")
    before = path_with_115[:i115]                  # 225 与 115 之间的点（由近及远）
    mid = before[-1] if before else None           # 取最靠近 115 的那个
print(f"   225 的射线中含 115 的那条 = {path_with_115}")
print(f"   225 与 115 之间的中间点 = "
      f"{[f'{x}({coord_label(x)})' for x in before] if path_with_115 else '—'}")

BD_B = dict(BD_A)
BD_B[mid] = pc(PAWN, 2, 2)                         # 吴方兵挡在中间
sB = mk(BD_B, turn=3)
mvB = moves_of(sB, 3)
chk(f"中间插一枚子（{mid} {coord_label(mid)}）⇒ ('225','115') **不再合法**",
    ("225", "115") not in mvB, f"蜀方 {len(mvB)} 手")
chk("同理 line_of_sight 也变 False", not bool(R.line_of_sight(sB, "225", "115")))
chk("对照：不插子时仍是 True（证明差异来自这枚子）",
    bool(R.line_of_sight(sA, "225", "115")))

# ---------------------------------------------------------------------------
print()
print("=" * 78)
print("3. 三种『射杀者 × 目标』组合是否同口径？（共用 _general）")
print("=" * 78)

# (a) 主帅 射 主帅
sab = mk({"115": pc(GENERAL, 1, 1), "225": pc(GENERAL, 2, 3),
          "315": pc(GENERAL, 3, 3)}, turn=3)
chk("蜀【主帅】225 → 射杀 魏【主帅】115  ✓",
    ("225", "115") in moves_of(sab, 3))

# (b) 副帅 射 副帅（蜀副帅 225 打 驻魏帐的吴方副帅 115）
sbb = mk({
    "115": pc(GENERAL, 1, 2, deputy=True),     # 驻魏帐的【吴方副帅】
    "225": pc(GENERAL, 2, 3, deputy=True),     # 驻吴帐的【蜀方副帅】
    "315": pc(GENERAL, 3, 3),
}, turn=3, out=(1, 2))
chk("蜀【副帅】225 → 射杀 吴【副帅】115  ✓",
    ("225", "115") in moves_of(sbb, 3))

# (c) 主帅 射 副帅
scb = mk({
    "115": pc(GENERAL, 1, 2, deputy=True),     # 驻魏帐的吴方副帅
    "225": pc(GENERAL, 2, 3),                  # 蜀方主帅
    "315": pc(GENERAL, 3, 3),
}, turn=3, out=(1, 2))
chk("蜀【主帅】225 → 射杀 吴【副帅】115  ✓",
    ("225", "115") in moves_of(scb, 3))

chk("⇒ 三种组合同口径（`_general()` 对 deputy 完全透明）",
    ("225", "115") in moves_of(sA, 3)      # 副帅 → 主帅 ★老师问的那一种
    and ("225", "115") in moves_of(sab, 3)
    and ("225", "115") in moves_of(sbb, 3)
    and ("225", "115") in moves_of(scb, 3))

# ---------------------------------------------------------------------------
print()
print("=" * 78)
print("4. 对照：『贴到隔壁』是另一条路（军帐内 1 格直接吃）")
print("=" * 78)
BD_C = {
    "225": pc(GENERAL, 2, 3, deputy=True),     # 蜀副帅（驻吴帐）
    "215": pc(ROOK, 1, 1),                     # 魏方车贴在隔壁（吴帐内的点）
    "315": pc(GENERAL, 3, 3),
}
sC = mk(BD_C, turn=3)
mvC = moves_of(sC, 3)
chk("副帅 225 能吃掉隔壁 215 的**普通子**（非射杀，是走法）",
    ("225", "215") in mvC)
chk("但『隔壁』必须是**同军帐内 1 格**（215 与 225 都在吴帐）",
    R.RC["215"][0] == R.RC["225"][0] == 2 and R.RC["215"][2] == R.RC["225"][2])

# ---------------------------------------------------------------------------
print()
print("=" * 78)
print("5. 端到端：真跑一步，看后果（= 老师那一局 ply 64 的复现）")
print("=" * 78)
sE = mk({
    "115": pc(GENERAL, 1, 1),
    "215": pc(ROOK, 1, 1),                     # 魏方还有个车（验证残兵易主）
    "225": pc(GENERAL, 2, 3, deputy=True),
    "315": pc(GENERAL, 3, 3),
}, turn=3)
note = GA.apply(sE, "225", "115")
print(f"   apply 返回 note = {note}")
chk("魏方进入 eliminated", 1 in list(sE.get("eliminated") or []))
chk("魏方进入 out（失去行棋资格）", 1 in list(sE.get("out") or []))
chk("斩的是**真帅** ⇒ note.is_deputy 为 False（或缺失即假）",
    not note.get("is_deputy"), f"is_deputy={note.get('is_deputy')!r}")
chk("note.promoted_from == 'general'（= 被吃的是帅，故就地升格为副帅）",
    note.get("promoted_from") == "general", f"{note.get('promoted_from')!r}")
now115 = sE["board"].get("115")
chk("115 上现在是**蜀方（3）的副帅**（这枚棋子就地变色）",
    bool(now115) and now115.get("army") == 3 and now115.get("deputy") is True,
    f"{now115}")
chk("魏方残兵（215 的车）已归蜀",
    (sE["board"].get("215") or {}).get("army") == 3,
    f"{sE['board'].get('215')}")

# ---------------------------------------------------------------------------
print()
print("=" * 78)
print("6. 源码级：`_general()` 里射杀分支**不区分 deputy**（结构性断言）")
print("=" * 78)
import inspect                                    # noqa: E402
src = inspect.getsource(R._general)
chk("_general 里调用了 snipe_targets", "snipe_targets(" in src)
chk("_general 里**没有** 'deputy' 关键字（⇒ 对主帅/副帅同口径）",
    "deputy" not in src)
chk("snipe_targets 的目标条件只要求『敌方的 GENERAL』、不排除 deputy",
    "GENERAL" in inspect.getsource(R.snipe_targets)
    and "deputy" not in inspect.getsource(R.snipe_targets))

print()
print("=" * 78)
print(f"结果：{OK} 通过 / {FAIL} 失败")
print("=" * 78)
if FAIL:
    print("❌ 有断言未通过 —— 结论不成立，需查源码")
else:
    print("✅ 全部通过：**引擎当前确实允许『副帅射杀主帅』**，")
    print("   依据是《专利版规则》§5.13（老师 2026-09-25 定夺「照见即可射杀」，")
    print("   其中明确『主帅 + 副帅都有此能力』）—— 不是规则原文（一、7）写过的。")
sys.exit(1 if FAIL else 0)
