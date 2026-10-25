# -*- coding: utf-8 -*-
"""射杀（snipe）专项验证 —— 2026-09-25 老师新规则

规则原文（老师定夺）：
  「魏国控制的副帅已经照见 I5 的主帅，并且这时轮到魏国走，
    为何魏国控制的副帅不能射杀 I5 的主帅」
  → 新规则：**照见即可射杀**。四问四答的口径：
    · **谁**：主帅与副帅都能射杀；
    · **打谁**：只能射杀对方的「帅 / 副帅」（普通子打不动）；
    · **旧条款**：废除《一、9》禁止照面 +《一、10》被动判负，
      改为「**轮到谁，谁能吃**」；
    · **线路**：沿**见面线**（规则图那六条跨方贯通线）。

后果语义 = **吃子**（不是判负）：对方帅从盘上消失 ⇒ 该方出局 + 残兵易主
（走的是现成的 `patent.on_general_captured` 路径，`apply` 无需特判）。

本文件覆盖 8 节：
  1. 三方军帐射杀对称性（含「射杀线只在引擎列 4/5/6」）
  2. 中间有子 ⇒ 阻断（不射杀）
  3. 只能吃帅 / 副帅（对方普通子挡在线上 ⇒ 打不动也不穿透）
  4. `snipe_targets` 与 `line_of_sight` **跨方穷举等价**（强证据）
  5. 照面不再非法（源码级 + 行为级）
  6. 《一、10》判负机制退役（源码级 + 行为级）
  7. 《一、9》第 3 条「独占口径」四种情形
  8. 端到端：远程射杀 ⇒ 斩帅出局 + 残兵易主 + 就地生成副帅
"""
import inspect
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, os.path.join(_ROOT, "server"))

from engine import game_dxf as GA      # noqa: E402
from engine import rules_dxf as R      # noqa: E402
from engine import patent as P         # noqa: E402

RC = R.RC
GENERAL = R.GENERAL
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


def board_of(*triples):
    """board_of(("115", R.GENERAL, 1), ("315", R.ROOK, 3), ...)"""
    return {pos: pc(kind, army) for pos, kind, army in triples}


# 军帐点位 = 每方 row1..3 × col4..6
TENT = sorted(p for p in RC
              if RC[p][1] in (1, 2, 3) and RC[p][2] in (4, 5, 6))

# ---------------------------------------------------------------------------
print("=" * 78)
print("1. 三方军帐射杀对称性 —— 射杀线只在引擎列 4/5/6（= 规则图上那六条线）")
print("=" * 78)
print("   贴士：图中数字 = 10 − 引擎列 ⇒ 规则图【E5-A5-F5-J5】等六条线，")
print("        在引擎里就是 c ↔ (10−c) 的镜像配对，落在列 4/5/6。")

# 空盘（只有三帅）：三帅同在列5、彼此无阻隔 ⇒ 两两照见 ⇒ 6 条射杀关系（双向）
BD0 = board_of(("115", GENERAL, 1), ("215", GENERAL, 2), ("315", GENERAL, 3))
s0 = mk(BD0, turn=1)
sp0 = sorted(GA.snipe_pairs(s0))
chk("空盘三帅同在列5 ⇒ snipe_pairs 恰 6 条（三帅两两、各双向）",
    sp0 == [("115", "215"), ("115", "315"), ("215", "115"),
            ("215", "315"), ("315", "115"), ("315", "215")], f"{sp0}")
chk("三帅两两照见（facing_pairs 3 对）",
    sorted(sorted(p) for p in GA.facing_pairs(s0)) ==
    [["115", "215"], ["115", "315"], ["215", "315"]],
    f"{[sorted(p) for p in GA.facing_pairs(s0)]}")
chk("对称：115↔215 双向都成立", ("115", "215") in sp0 and ("215", "115") in sp0)
chk("对称：115↔315 双向都成立", ("115", "315") in sp0 and ("315", "115") in sp0)
chk("对称：215↔315 双向都成立", ("215", "315") in sp0 and ("315", "215") in sp0)

# 军帐全 27 点穷举：所有「跨方可照见」的对，按起点列统计
_tent_pairs = []
for i in range(len(TENT)):
    for j in range(i + 1, len(TENT)):
        a, b = TENT[i], TENT[j]
        aa, ab = RC[a][0], RC[b][0]
        if aa == ab:
            continue
        bd = {a: pc(GENERAL, aa), b: pc(GENERAL, ab)}
        st = {"board": bd}
        if R.line_of_sight(st, a, b):
            assert b in R.snipe_targets(bd, a, aa, frozenset()), (a, b)
            _tent_pairs.append((a, b))
_cols = {}
for a, b in _tent_pairs:
    _cols[RC[a][2]] = _cols.get(RC[a][2], 0) + 1
chk("军帐内「跨方可照见」共 54 对（= 27 对 × 双向）", len(_tent_pairs) == 54,
    f"{len(_tent_pairs)} 对")
chk("★ 这些射杀线的**起点列**只落在 4 / 5 / 6", sorted(_cols) == [4, 5, 6],
    f"列分布 {dict(sorted(_cols.items()))}")
chk("★ 且列5 占 27 条（= 9 个列5军帐点 × 3 个对面点）",
    _cols.get(5) == 27, f"列5 {_cols.get(5)} 条")
chk("★ 全部射杀线都是**跨方**（同方帅之间不算射杀）",
    all(RC[a][0] != RC[b][0] for a, b in _tent_pairs))

# ---------------------------------------------------------------------------
print()
print("=" * 78)
print("2. 中间有子 ⇒ 阻断（照不见 ⇒ 不射杀）")
print("=" * 78)
# 115（魏帥）— 155 — 315（蜀帥）在列5 同线。
BD1 = board_of(("115", GENERAL, 1), ("315", GENERAL, 3), ("155", R.PAWN, 2))
s1 = mk(BD1, turn=1)
chk("前提：155 确实在 115↔315 的射线上",
    next((p for p in R.RAYS["115"] if "315" in p), None) and
    "155" in next(p for p in R.RAYS["115"] if "315" in p))
chk("中间有吴兵155 ⇒ 蜀帥315 照不见魏帥115", not R.line_of_sight(s1, "315", "115"))
chk("★ 蜀帥315 射杀目标为空", R.snipe_targets(s1["board"], "315", 3) == [],
    f"{R.snipe_targets(s1['board'], '315', 3)}")
chk("★ 蜀方着法表不含 315→115", ("315", "115") not in GA.legal_moves(s1, 3))
chk("★ 魏方着法表不含 115→315", ("115", "315") not in GA.legal_moves(s1, 1))
# 抽离阻隔子 ⇒ 立刻恢复射杀
s1b = GA.clone(s1)
del s1b["board"]["155"]
chk("抽离阻隔子 155 后 ⇒ 恢复互相射杀",
    R.snipe_targets(s1b["board"], "315", 3) == ["115"] and
    R.snipe_targets(s1b["board"], "115", 1) == ["315"])

# ---------------------------------------------------------------------------
print()
print("=" * 78)
print("3. 只能吃帅 / 副帅 —— 对方**普通子**挡在线上 ⇒ 打不动、也不穿透")
print("=" * 78)
# 把吴兵换成吴車 155：仍是"第一个子"，但 kind != GENERAL ⇒ 不收录、且 break
BD2 = board_of(("115", GENERAL, 1), ("315", GENERAL, 3), ("155", R.ROOK, 2))
s2 = mk(BD2, turn=1)
chk("线上第一个子是敌方**車**（非帅）⇒ snipe 不收录它",
    R.snipe_targets(s2["board"], "315", 3) == [],
    f"{R.snipe_targets(s2['board'], '315', 3)}")
chk("★ 也不穿透到后面的魏帥 115（被車挡死）",
    "115" not in R.snipe_targets(s2["board"], "315", 3))
# 副帅也是合法射杀目标
BD3 = board_of(("115", GENERAL, 1), ("315", GENERAL, 3))
s3 = mk(BD3, turn=1)
s3["board"]["115"]["deputy"] = True          # 把 115 改成「副帅」
chk("★ 对方**副帅**同样是合法射杀目标",
    R.snipe_targets(s3["board"], "315", 3) == ["115"],
    f"{R.snipe_targets(s3['board'], '315', 3)}")
chk("副帅也在 snipe_pairs 里出现",
    ("315", "115") in GA.snipe_pairs(s3))
# 己方帅不可被己方射杀
chk("★ 己方帅不是射杀目标（只看对方）",
    "315" not in R.snipe_targets(s3["board"], "315", 3))

# ---------------------------------------------------------------------------
print()
print("=" * 78)
print("4. ★强证据：`snipe_targets` 与 `line_of_sight` **跨方穷举等价**")
print("=" * 78)
_all = sorted(RC)
_eq = _bad = 0
_bad_ex = []
for i in range(len(_all)):
    for j in range(i + 1, len(_all)):
        a, b = _all[i], _all[j]
        aa, ab = RC[a][0], RC[b][0]
        if aa == ab:
            continue                       # 同方：帅不吃自家帅，不参与比较
        bd = {a: pc(GENERAL, aa), b: pc(GENERAL, ab)}
        los = R.line_of_sight({"board": bd}, a, b)
        sn = b in R.snipe_targets(bd, a, aa, frozenset())
        if los == sn:
            _eq += 1
        else:
            _bad += 1
            if len(_bad_ex) < 5:
                _bad_ex.append((a, b, los, sn))
chk("全部 135 点位、6075 个跨方点对：两者判据 100% 一致",
    _bad == 0 and _eq == 6075, f"一致 {_eq} / 不一致 {_bad} {_bad_ex}")

# 中间放一个子的情形也要一致（阻断时两者同为 False）
_eq2 = _bad2 = 0
for i in range(len(_all)):
    for j in range(i + 1, len(_all)):
        a, b = _all[i], _all[j]
        aa, ab = RC[a][0], RC[b][0]
        if aa == ab:
            continue
        path = next((p for p in R.RAYS.get(a) or () if b in p), None)
        if not path:
            continue
        idx = path.index(b)
        if idx == 0:
            continue
        mid = path[idx // 2]                # 在中间插一个第三方子
        bd = {a: pc(GENERAL, aa), b: pc(GENERAL, ab), mid: pc(R.PAWN, 3)}
        los = R.line_of_sight({"board": bd}, a, b)
        sn = b in R.snipe_targets(bd, a, aa, frozenset())
        if los == sn:
            _eq2 += 1
        else:
            _bad2 += 1
chk("全量（中间插一子）：两者判据同样一致（阻断时同为 False）",
    _bad2 == 0 and _eq2 > 300, f"一致 {_eq2} / 不一致 {_bad2}")

# ---------------------------------------------------------------------------
print()
print("=" * 78)
print("5. 照面不再非法（源码级 + 行为级）")
print("=" * 78)
_lm_src = inspect.getsource(GA.legal_moves)
_lm_body = _lm_src.split('"""')[-1]        # 去掉 docstring，只看函数体
chk("★ legal_moves 已删除「试走 clone」式的见面过滤（函数体内无 _move_piece 调用）",
    "_move_piece" not in _lm_body)
chk("★ legal_moves 保留 §9 第3条 guard（第三方不得白捡出局方帅）",
    "protected_out_generals" in _lm_body)
chk("★ legal_moves 不再引用 pending_judge（被动见面待决已退役）",
    "pending_judge" not in _lm_src)
_fp_src = inspect.getsource(GA.facing_pairs)
chk("★ facing_pairs 函数体内已无「豁免对剔除」（C 不可吃 B 帅的旧过滤）",
    "out_of" not in _fp_src and "need" not in _fp_src)
# 行为级：走过去照面/走完仍照面，都在合法着法里
s5 = mk(board_of(("115", GENERAL, 1), ("315", GENERAL, 3)), turn=1)
chk("★ 魏帥 115→125（走到射杀线上、与蜀帥照面）合法",
    ("115", "125") in GA.legal_moves(s5, 1))
chk("★ 魏帥 115→315（远程射杀）合法",
    ("115", "315") in GA.legal_moves(s5, 1))

# ---------------------------------------------------------------------------
print()
print("=" * 78)
print("6. 《一、10》判负机制退役（源码级 + 行为级）")
print("=" * 78)
_msrc = open(os.path.join(_ROOT, "server", "match.py"), encoding="utf-8").read()
chk("★ match.py 已无 judge_lose 调用", "judge_lose(" not in _msrc)
chk("★ match.py 已无 judge_pending 逻辑", "judge_pending" not in _msrc)
_pj_src = inspect.getsource(GA.pending_judge)
chk("★ pending_judge 函数体只剩 `return None`",
    _pj_src.strip().endswith("return None"))
for _name, _st in (("空盘", s0), ("照面局面", mk(board_of(
        ("115", GENERAL, 1), ("215", GENERAL, 2), ("315", GENERAL, 3)), turn=2))):
    chk(f"pending_judge({_name}) 恒为 None", GA.pending_judge(_st) is None)
chk("★ status() 的 pending_judge 字段恒为 None",
    GA.status(s0)["pending_judge"] is None)
chk("★ status() 新增 snipe 字段（供前端标红被瞄准的帅）",
    isinstance(GA.status(s0).get("snipe"), list) and len(GA.status(s0)["snipe"]) == 6,
    f"{GA.status(s0)['snipe']}")

# ---------------------------------------------------------------------------
print()
print("=" * 78)
print("7. 《一、9》第 3 条「独占口径」四种情形")
print("=" * 78)
print("   口径：只有【独占照见】的那一方有资格吃 B 的帅；多方争抢 ⇒ 谁都不得吃。")

# 情形 (a)：无在局方与 B 帅照见 ⇒ 第 3 条前提不成立 ⇒ 不拦
#   魏出局；吴帥在 216、蜀帥在 316（都在列6，不与列5 的 115 照见）
BDa = board_of(("115", GENERAL, 1), ("216", GENERAL, 2), ("316", GENERAL, 3))
sa = mk(BDa, turn=2, out=(1,))
chk("(a) 前提：无在局帥与出局帥115 照见",
    not R.line_of_sight(sa, "216", "115") and not R.line_of_sight(sa, "316", "115"))
chk("(a) 前提不成立 ⇒ guard 里不含 115（不拦，按普通吃子处理）",
    GA.protected_out_generals(sa).get("115") is None,
    f"{GA.protected_out_generals(sa)}")

# 情形 (b)：独占照见 ⇒ 放行那一方
BDb = board_of(("115", GENERAL, 1), ("216", GENERAL, 2), ("315", GENERAL, 3))
sb = mk(BDb, turn=2, out=(1,))
chk("(b) 前提：只有蜀帥315 与出局帥115 照见",
    R.line_of_sight(sb, "315", "115") and not R.line_of_sight(sb, "216", "115"))
chk("(b) 独占 ⇒ guard['115'] = {蜀}（放行蜀）",
    GA.protected_out_generals(sb).get("115") == frozenset({3}),
    f"{GA.protected_out_generals(sb)}")

# 情形 (c)：多方争抢（三点共线）⇒ 谁都不得吃
BDc = board_of(("115", GENERAL, 1), ("215", GENERAL, 2), ("315", GENERAL, 3))
sc = mk(BDc, turn=2, out=(1,))
chk("(c) 前提：魏吴蜀三帥同在列5、吴与蜀都照见 115",
    R.line_of_sight(sc, "215", "115") and R.line_of_sight(sc, "315", "115"))
chk("(c) 多方争抢 ⇒ guard['115'] = 空集（谁都不得吃）",
    GA.protected_out_generals(sc).get("115") == frozenset(),
    f"{GA.protected_out_generals(sc)}")

# 情形 (d)：B 没出局 ⇒ 整个 guard 为空（第 3 条只在"出局方的帅"上生效）
BDd = board_of(("115", GENERAL, 1), ("215", GENERAL, 2), ("315", GENERAL, 3))
sd = mk(BDd, turn=2, out=())
chk("(d) 无出局方 ⇒ guard 整体为空（第 3 条不适用）",
    GA.protected_out_generals(sd) == {}, f"{GA.protected_out_generals(sd)}")

# ---------------------------------------------------------------------------
print()
print("=" * 78)
print("8. 端到端：远程射杀 ⇒ 斩帅出局 + 残兵易主 + 副帅进驻被斩方军帐（射手原样留盘）")
print("=" * 78)
BDe = {
    "115": pc(GENERAL, 1),                 # 魏帥（被射杀目标）
    "315": pc(GENERAL, 3),                 # 蜀帥（射手）
    "146": pc(R.PAWN, 1),                  # 魏残兵（验证易主；避开列5 射线）
    "116": pc(R.ROOK, 1),                  # 魏車（验证易主；避开列5 射线）
}
se = mk(BDe, turn=3)
# 315 到 115 的射线中途点（都不能放子，否则挡路）
_gap = next(p for p in R.RAYS["315"] if "115" in p)
chk("前提：列5 射线上确实有多个中途点（供下面放子实验）", len(_gap) >= 3, f"{_gap}")
chk("前提：蜀帥315 照见魏帥115（中途 325/335/345/155/145/135/125 全空）",
    R.line_of_sight(se, "315", "115"))
chk("前提：蜀帥315 的射杀目标 = [魏帥115]",
    R.snipe_targets(se["board"], "315", 3) == ["115"],
    f"{R.snipe_targets(se['board'], '315', 3)}")
chk("前提：315→115 是远程着法（射线上隔 8 个点，非相邻走子）",
    len(_gap) >= 3, f"射线中途 {len(_gap)-1} 个点")
chk("蜀方着法表含 315→115", ("315", "115") in GA.legal_moves(se, 3))
_note = GA.apply(se, "315", "115")
chk("★ 战报：captured=general 且 eliminated=1（魏方出局）",
    _note.get("captured") == GENERAL and _note.get("eliminated") == 1, f"{_note}")
chk("★ 魏方确实出局（eliminated 含 1）", 1 in se["eliminated"], f"{se['eliminated']}")
chk("★ 魏残兵 146 易主给蜀", se["board"].get("146", {}).get("army") == 3,
    f"{se['board'].get('146')}")
chk("★ 魏車 116 易主给蜀", se["board"].get("116", {}).get("army") == 3,
    f"{se['board'].get('116')}")
chk("★ 射手蜀帥落点 115 就地变成「魏方副帅」、归蜀控制（吃帅的棋子升格）",
    se["board"].get("115", {}).get("deputy") is True
    and se["board"]["115"]["army"] == 3
    and se["board"]["115"]["home"] == 1, f"{se['board'].get('115')}")
chk("★ 副帅登记表 owner=蜀", se["deputies"].get(1, {}).get("owner") == 3,
    f"{se['deputies']}")
chk("★ 战报记录升格前的棋子种类 promoted_from=general（射手是蜀帥）",
    _note.get("promoted_from") == GENERAL, f"{_note}")
chk("射手 315 已离开原位（远程射杀是「移动 + 吃」一步）",
    "315" not in se["board"], f"{se['board'].get('315')}")
chk("魏方已被排除出 alive（只剩吴、蜀）",
    1 not in GA.alive_armies(se), f"{[CN[k] for k in GA.alive_armies(se)]}")

print()
print("=" * 52)
print(f"射杀专项验证: {OK} 通过 / {FAIL} 失败")
print("=" * 52)
sys.exit(1 if FAIL else 0)
