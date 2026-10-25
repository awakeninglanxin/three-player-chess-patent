# -*- coding: utf-8 -*-
"""帅见面线路专项自检 —— 老师 2026-09-24 问「副帅照见 I5 的主帅，为何不能射杀」。

【老师原话与局面】
    老师局面：魏方控制的**副帅**在 `215`(O5)、蜀方**主帅**在 `325`(I5)，轮到魏方走。
    老师问：「副帅已经照见 I5 的主帅，并且这时轮到魏国走，为何魏国控制的副帅不能射杀 I5 的主帅」

【第一件事：老师的观察是对的】
    `line_of_sight(215, 325) == True` —— 两点同在**列5 贯通纵线**上，
    中间 225/235/245/255/355/345/335 **全空**，确实毫无阻隔地照见。

【第二件事：不能射杀，且引擎行为正确】
    ① §9 原文「不可把己方帅和对手的帅放在没有棋子阻隔的线路上」是**禁止性规则**
       （规定走子方不得**造成**照面），不是一种吃子能力 —— 原文通篇没有"照见即可吃"。
    ② 照面的**后果机制**在 §10：被动见面时 A 二选一 —— **判 B 负**（B 帅**留在盘上**、
       棋子**不易主**）或自己阻隔/移开。文档 §10.1 已严格对比过「**判负 ≠ 吃帅**」。
    ③ 而**这一局连判负都不触发**：副帅的 `home=2` 是**已出局的吴方**，蜀帅是在局方
       ⇒ 正是 §9 **豁免 2**「在局方的帅可与出局方的帅见面」⇒ 合法照见、零后果。
       （同时被豁免 1 覆盖：副帅 `army=1` = 魏主帅本人控制的，属"己方两帅"。）
    ④ 副帅的能力只有「在军帐内**行使帅的运行方式和职责**」= 军帐内横竖 1 格
       （`GEN_T[(2,'215')] = ('214','216','225')`），**没有任何远程能力**；
       三个军帐彼此最近 83.974，单步 1 格 ⇒ 连"走过去吃"都不可能。

【第三件事：引擎确实没有「副帅不能吃帅」的过滤】（专利版规则第 18 条）
    把蜀帅放进副帅的军帐邻格 `225`，`legal_moves` 里**有** `215→225` 吃帅
    ⇒ 说明引擎只在"够得着"时放行，与规则一致（§18：不得有任何"副帅不能吃帅"的过滤）。

【顺带证伪文档 §9.1 的一条错误结论】（本测试 §4）
    文档原文：「**只有 6 对**，且全部落在各军帐的**行1（底边）**。
              帅走到军帐行2 / 行3 时永远不会"见面"。」
    实测：军帐内两两照见 **120 对**（同方 66 / 跨方 54，三方完全对称）。
    根因：规则图那六条「线路」是**整条贯通直线**，军帐里落在其上的点远不止两端的"底线中点" ——
    列5 上三方军帐的 9 个点（行1/行2/行3）**两两全部照见**（36/36）。
    反例就是老师看到的这一对：`I5(325) ↔ O5(215)` 照见 = True。

跑法：cd 中国三人象棋_专利版 && python tests/_verify_facing_lines.py
"""
import itertools
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "server"))

from engine import geometry_dxf as D        # noqa: E402
from engine import game_dxf as GA           # noqa: E402
from engine import rules_dxf as R           # noqa: E402

OK = FAIL = 0

LETTER = {1: "ABCDE", 2: "KLMNO", 3: "FGHIJ"}


def chk(name, cond, extra=""):
    global OK, FAIL
    if cond:
        OK += 1
        print(f"  [OK]   {name} {extra}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name} {extra}")


def lb(p):
    """引擎点号 → 棋盘原图标签（A1..O9）"""
    a, r, c = R.RC[p]
    return LETTER[a][5 - r] + str(10 - c)


def mk(pieces, turn=1):
    """只放指定棋子的局面（其余字段从 new_game 继承，保证结构完整）"""
    s = GA.new_game()
    s["board"] = {p: dict(v) for p, v in pieces.items()}
    s["turn"] = turn
    s["ply"] = 0
    s["history"] = []
    return s


def gen(p):
    return {"kind": "general", "army": R.RC[p][0], "home": R.RC[p][0]}


def dep(pos, army, home):
    return {"kind": "general", "army": army, "home": home, "deputy": True}


EMPTY = {"board": {}, "turn": 1}

GONG = {a: [D.pid(a, r, c) for r in (1, 2, 3) for c in (4, 5, 6)] for a in D.ARMIES}
ALLG = [p for a in D.ARMIES for p in GONG[a]]

print("=" * 70)
print("帅见面线路专项自检（副帅照见主帅能否射杀 + 文档 §9.1 结论证伪）")
print("=" * 70)

# ---------------------------------------------------------------- §1
print("\n§1 规则图六条线路的两端（空盘必须照见）")
LINES = [("115", "315", "E5-J5"), ("315", "215", "J5-O5"), ("215", "115", "O5-E5"),
         ("114", "316", "E6-J4"), ("314", "216", "J6-O4"), ("214", "116", "O6-E4")]
for a, b, nm in LINES:
    chk(f"线路 {nm} 两端照见", R.line_of_sight(EMPTY, a, b),
        f"（{a}({lb(a)}) ↔ {b}({lb(b)})）")

# ---------------------------------------------------------------- §2
print("\n§2 列5 上三方军帐的 9 个点 —— 两两全部照见（36/36）")
C5 = [p for p in ALLG if R.RC[p][2] == 5]
chk("列5 军帐点数 = 9（三方各 行1/行2/行3）", len(C5) == 9, f"实际 {len(C5)}")
_hit = [(p, q) for p, q in itertools.combinations(C5, 2)
        if R.line_of_sight(EMPTY, p, q)]
chk("列5 军帐 9 点两两照见 = 36/36", len(_hit) == 36, f"实际 {len(_hit)}/36")

# ---------------------------------------------------------------- §3
print("\n§3 军帐内照见对的完整规模（文档说「只有 6 对」）")
_alls = [(p, q) for p, q in itertools.combinations(ALLG, 2)
         if R.line_of_sight(EMPTY, p, q)]
_same = sum(1 for p, q in _alls if R.RC[p][0] == R.RC[q][0])
_cross = len(_alls) - _same
chk("军帐内照见对总数 = 120", len(_alls) == 120, f"实际 {len(_alls)}")
chk("其中同方 = 66（含『己方两帅可见面』豁免 1）", _same == 66, f"实际 {_same}")
chk("其中跨方 = 54（每两方 18 对，三方对称）", _cross == 54, f"实际 {_cross}")
_bypair = {}
for p, q in _alls:
    if R.RC[p][0] != R.RC[q][0]:
        k = tuple(sorted((R.RC[p][0], R.RC[q][0])))
        _bypair[k] = _bypair.get(k, 0) + 1
chk("每两个方之间的跨方照见对数都是 18（三方完全对称）",
    set(_bypair.values()) == {18} and len(_bypair) == 3, f"实际 {_bypair}")

# ---------------------------------------------------------------- §4
print("\n§4 证伪文档 §9.1：「帅走到军帐行2/行3 时永远不会见面」")
_row23 = [D.pid(a, r, 5) for a in D.ARMIES for r in (2, 3)]
chk("行2/行3 列5 的 6 个点（D5/C5、N5/M5、I5/H5）都在见面线路上",
    all(any(R.line_of_sight(EMPTY, p, q) for q in ALLG if q != p) for p in _row23),
    f"点数 {len(_row23)}")
chk("★ 反例（老师看到的那一对）：I5(325) ↔ O5(215) 照见",
    R.line_of_sight(EMPTY, "325", "215"), "→ 文档旧结论错误")
chk("另两例：C5(135) ↔ I5(325)、N5(225) ↔ C5(135) 也照见",
    R.line_of_sight(EMPTY, "135", "325") and R.line_of_sight(EMPTY, "225", "135"))
chk("跨列不照见（列4 端点 ↔ 列5 任意点，抽样全 False）",
    not R.line_of_sight(EMPTY, "136", "325") and not R.line_of_sight(EMPTY, "116", "225"))

# ---------------------------------------------------------------- §5
print("\n§5 副帅不参与「帅见面」判定（generals_facing 只认非副帅 —— 客观口径，未随新规则变）")
st = mk({"115": gen("115"), "215": dep("215", 1, 2), "315": dep("315", 2, 3)}, 1)
chk("generals_facing 只认非副帅（盘上 2 副帅 + 1 主帅 → 结果为空）",
    R.generals_facing(st) == [], f"实际 {R.generals_facing(st)}")
chk("facing_pairs(strict) 同样为空（不产生违规对）",
    GA.facing_pairs(st, strict=True) == [])
chk("pending_judge 为空（不触发《一、10》被动见面）",
    GA.pending_judge(st) is None)

# ---------------------------------------------------------------- §6
print("\n§6 ★ 本局真实情形：副帅照见在局方主帅 ⇒ 应当可射杀（2026-09-25 新规则）")
st = mk({"114": gen("114"), "215": dep("215", 1, 2), "325": gen("325")}, 1)
chk("副帅 215(O5) ↔ 蜀帅 325(I5) 照见 = True（老师观察正确）",
    R.line_of_sight(st, "215", "325"))
chk("副帅不参与 generals_facing ⇒ 盘上非副帅只剩 114/325，且两者不同列不照见",
    R.generals_facing(st) == [], f"实际 {R.generals_facing(st)}")
_gdx_src = open(os.path.join(_ROOT, "server", "engine", "game_dxf.py"), encoding="utf-8").read()
chk("照面**不再是违规**：facing_pairs 里已无『豁免剔除』逻辑（旧《一、9》豁免 2 退役）",
    "out_of" not in _gdx_src.split("def facing_pairs")[1].split("\ndef ")[0])
chk("《一、10》判负待决机制已退役（恒 None）",
    GA.pending_judge(st) is None)
_mv = [(a, b) for a, b in GA.legal_moves(st, 1)]
chk("★ 副帅的合法着法里**有** 215→325（射杀蜀帅）—— 老师要的新规则",
    ("215", "325") in _mv, f"实际 {_mv}")
chk("射杀关系表 snipe_pairs 含 (215,325) 与 (325,215)（互为人质，双向）",
    ("215", "325") in GA.snipe_pairs(st) and ("325", "215") in GA.snipe_pairs(st),
    f"实际 {GA.snipe_pairs(st)}")

# ---------------------------------------------------------------- §7
print("\n§7 射杀 vs 普通吃子：够得着的仍走军帐 1 格，够不着才靠射杀")
st = mk({"114": gen("114"), "215": dep("215", 1, 2), "225": gen("225")}, 1)
_mv = [(a, b) for a, b in GA.legal_moves(st, 1)]
chk("蜀帅贴到副帅军帐邻格 225(N5) 时，副帅**可以吃它**",
    ("215", "225") in _mv, f"实际 {_mv}")
st2 = mk({"114": gen("114"), "215": dep("215", 1, 2), "325": gen("325")}, 1)
chk("★ 远距离的帅（325）**也能射杀** —— 射杀是远程能力（新规则的核心）",
    ("215", "325") in [(a, b) for a, b in GA.legal_moves(st2, 1)])
chk("军帐内横竖 1 格的基本盘没被改动（GEN_T 原样）",
    set(R.GEN_T[(2, "215")]) == {"214", "216", "225"},
    f"实际 {R.GEN_T[(2, '215')]}")
chk("相邻敌帅**只登记一次**（走 1 格与射杀重叠时去重）",
    [(a, b) for a, b in GA.legal_moves(st, 1)].count(("215", "225")) == 1)

# ---------------------------------------------------------------- §8
print("\n§8 照面不再违规：站在见面线上是战术选择，不是犯规")
st = mk({"115": gen("115"), "215": gen("215"), "325": gen("325")}, 1)
_fp = GA.facing_pairs(st)
chk("三个在局方主帅全在列5 ⇒ 客观照见 3 对",
    len(_fp) == 3, f"实际 {_fp}")
chk("§9.1 表格列的首对 魏115(E5) ↔ 蜀325(I5) 在其中",
    frozenset({"115", "325"}) in _fp)
chk("★ 三方两两互相都能射杀（snipe_pairs 共 6 条：3 对 × 双向）",
    len(GA.snipe_pairs(st)) == 6, f"实际 {len(GA.snipe_pairs(st))}")
_l115 = [(a, b) for a, b in GA.legal_moves(st, 1)]
chk("魏帅 115 的着法含 115-215、115-325（两个对手都在射程内）",
    ("115", "215") in _l115 and ("115", "325") in _l115, f"实际 {_l115}")
chk("pending_judge 恒 None（判负机制确实下岗）",
    GA.pending_judge(st) is None)

# ---------------------------------------------------------------- §9
print("\n§9 规则依据自检（射杀判据必须纯拓扑；旧判负机制必须确实退役）")
_src = open(os.path.join(_ROOT, "server", "engine", "game_dxf.py"), encoding="utf-8").read()
_rules_src = open(os.path.join(_ROOT, "server", "engine", "rules_dxf.py"), encoding="utf-8").read()
chk("line_of_sight 用 RAYS（接好战线直通的贯通线），不是未缝合的 B.rays",
    "RAYS.get(p1)" in _rules_src and "B.rays.get(p1)" not in _rules_src)
_gf = _rules_src.split("def generals_facing")[1].split("\ndef ")[0]
chk('generals_facing 函数体内明确排除副帅（not pc.get("deputy")）',
    'not pc.get("deputy")' in _gf, f"函数体 {len(_gf)} 字符")
_pj_src = _src.split("def pending_judge")[1].split("\ndef ")[0]
chk("pending_judge 已退役（函数体只剩 return None）",
    _pj_src.strip().splitlines()[-1].strip() == "return None",
    f"函数体末行 {_pj_src.strip().splitlines()[-1].strip()!r}")
_lm_src = _src.split("def legal_moves")[1].split("\ndef ")[0]
chk("legal_moves 已删掉照面过滤（不再引用 facing_pairs / pending_judge）",
    "facing_pairs" not in _lm_src and "pending_judge" not in _lm_src)
_sn = _rules_src.split("def snipe_targets")[1].split("\n# =")[0]
chk("★ snipe_targets 判据纯拓扑：不碰 atan2 / ANG_TOL / math",
    "atan2" not in _sn and "ANG_TOL" not in _sn and "math." not in _sn,
    f"函数体 {len(_sn)} 字符")
chk("game_dxf 仍保留 judge_lose 定义（退役但未删，供历史复盘）",
    "def judge_lose" in _src)

# ============================================================ 汇总
print("\n" + "=" * 70)
print(f"帅见面线路专项自检结果: {OK} 通过 / {FAIL} 失败")
print("=" * 70)
sys.exit(1 if FAIL else 0)
