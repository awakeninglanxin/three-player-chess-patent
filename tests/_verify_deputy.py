# -*- coding: utf-8 -*-
"""验证老师 2026-09-24 深夜确认的四条副帅口径。

① 副帅「**就地变色**」
   老师：「另一种读法是"A 方那枚帅棋子就地变色"，这样逻辑是对的。」
   ⇒ 副帅位置 = **被吃帅的原位置**（不再另挪到军帐中心）。

② 副帅**不能阻隔帅见面**
   老师：「这种情况不可能有吧？副帅不能出它原方的军帐。」
   ⇒ 结构性证明：六条见面线路的**中段全在 row5**，不在任何军帐内。

③ 副帅**可以吃在局方敌方的帅**
   老师：「行，出局方那枚帅就是副帅，副帅归主帅管，可以吃在局方敌方的帅。」
   ⇒ 引擎不得有任何"副帅不能吃帅"的过滤。

④ 《一、10》方案②「用自己的棋阻隔」**必须落在两帅之间那条线路上**
   老师：「对，棋子落在两帅之间那条线。」
   ⇒ 落在线路外 → 见面未消除 → 该着法被剔除。

标签口径：图中数字 = 10 − 引擎列；字母 魏 A-E / 吴 K-O / 蜀 F-J（row5→row1）。
"""
import sys

sys.path.insert(0, "server")
from engine import game_dxf as GA      # noqa: E402
from engine import rules_dxf as R      # noqa: E402
from engine import patent as P         # noqa: E402

CN = {1: "魏", 2: "吴", 3: "蜀"}
OK = FAIL = 0

# 六条帅见面线路（规则《一、9》原文 → 引擎点位）
LINES = {
    "E5-A5-F5-J5": ("115", "155", "355", "315"),
    "J5-F5-K5-O5": ("315", "355", "255", "215"),
    "O5-K5-A5-E5": ("215", "255", "155", "115"),
    "E6-A6-F4-J4": ("114", "154", "356", "316"),
    "J6-F6-K4-O4": ("316", "356", "256", "216"),
    "O6-K6-A4-E4": ("216", "256", "156", "116"),
}


def chk(name, cond, extra=""):
    global OK, FAIL
    if cond:
        OK += 1
        print(f"  [OK]   {name}" + (f"  {extra}" if extra else ""))
    else:
        FAIL += 1
        print(f"  [FAIL] {name}  {extra}")


def pc(kind, home, army=None, deputy=False):
    d = {"kind": kind, "army": army or home, "home": home}
    if deputy:
        d["deputy"] = True
    return d


def mk(board, turn=1, out=(), deputies=None):
    s = GA.new_game(first=turn)
    s["board"] = {k: dict(v) for k, v in board.items()}
    s["out"] = list(out)
    s["eliminated"] = list(out)
    s["annexed"] = {}
    s["declared_lose"] = []
    s["deputies"] = dict(deputies or {})
    P.refresh_combat(s)
    return s


# 三帅两两共线（都在列5），用 155/255/355 三点堵住即可让三对都不见面
def blockers(holder=2):
    return {p: pc(R.PAWN, holder) for p in ("155", "255", "355")}


print("=" * 78)
print("① 《一、7》原文：**吃帅的那枚棋子就地升格为副帅**（原棋子从盘上消失）")
print("   老师 2026-09-25「退回原先的方式」—— 看回第 7 条原文后确认原文口径正确")
print("=" * 78)
b = {"115": pc(R.GENERAL, 1), "215": pc(R.GENERAL, 2), "315": pc(R.GENERAL, 3),
     "316": pc(R.ROOK, 1)}          # 魏車 已深入蜀军帐 r1c6
b.update(blockers())
s = mk(b, turn=1)
n0 = len(s["board"])
chk("前提：三帅不违规见面", GA.facing_pairs(s, strict=True) == [],
    f"{GA.facing_pairs(s, strict=True)}")
chk("前提：(316→315) 吃蜀帥 在魏的合法着法里",
    ("316", "315") in GA.legal_moves(s, 1), f"魏合法 {len(GA.legal_moves(s, 1))} 步")

note = GA.apply(s, "316", "315")
chk("★ 吃帅后 315 上是**魏控制的蜀副帅**（吃帅的車就地升格）",
    s["board"].get("315", {}).get("deputy") is True
    and s["board"]["315"]["army"] == 1 and s["board"]["315"]["home"] == 3,
    f"{s['board'].get('315')}")
chk("副帅位置登记 = 315（= 被吃帅的原位，不是军帐中心 325）",
    s["deputies"].get(3, {}).get("pos") == "315", f"{s['deputies']}")
chk("★ 316 已空（魏車已升格成副帅，不在原地留下第二枚子）",
    "316" not in s["board"], f"316 = {s['board'].get('316')}")
chk("蜀军帐中心 325 **没有**凭空出现的副帅（不是「另挪到军帐中心」）",
    "325" not in s["board"], f"{sorted(s['board'])}")
chk("★ 战报记录升格前的棋子种类 promoted_from=rook（前端显示「车→副帥」）",
    note.get("promoted_from") == R.ROOK, f"{note}")
chk("棋子数守恒（吃帅净减 1：被吃的帅消失，吃帅的車换身份占位）",
    len(s["board"]) == n0 - 1, f"{n0} → {len(s['board'])}")
chk("蜀方生命力=False（主帅没了）/ 战斗力=False",
    s["vitality"][3] is False and s["combat"][3] is False)
chk("魏方生命力仍=True（是它自己的主帅还在）",
    s["vitality"][1] is True)
chk("战报标记 eliminated=3（真·出局）",
    note.get("eliminated") == 3 and 3 in s["eliminated"], f"{note}")

print()
print("  副帅落点是否严格限制在蜀军帐内（老师：不能出军帐）：")
TENT3 = set(P.TENT[3])
dst = {to for frm, to in GA.legal_moves(s, 1) if frm == "315"}
print(f"    蜀军帐 {sorted(TENT3)}")
print(f"    副帅 315 的合法落点 {sorted(dst)}")
chk("副帅落点 ⊆ 蜀军帐（不能出军帐）", bool(dst) and dst <= TENT3, f"{sorted(dst)}")
chk("副帅落点 = {314,316,325}（军帐内横竖 1 格，缺 305 因已在军帐上边界）",
    dst == {"314", "316", "325"}, f"{sorted(dst)}")

print()
print("=" * 78)
print("② 副帅**不可能阻隔**帅见面 —— 结构化证明")
print("=" * 78)
print("  先看清一件事：原文的【E5-A5-F5-J5】只是**4 个关键点**（两端帅位 + 两个折点），")
print("  引擎里这条线的**真实路径有 10 个格点**（中间要沿列5 一格一格走）：")
LINE_PAIRS = [("E5-A5-F5-J5", "115", "315"), ("J5-F5-K5-O5", "315", "215"),
              ("O5-K5-A5-E5", "215", "115"), ("E6-A6-F4-J4", "114", "316"),
              ("J6-F6-K4-O4", "314", "216"), ("O6-K6-A4-E4", "214", "116")]
paths = {}
for name, g1, g2 in LINE_PAIRS:
    ps = [p for p in R.RAYS.get(g1, ()) if g2 in p]
    full = (g1,) + tuple(ps[0])
    paths[name] = (g1, g2, full)
    lands = {q[0] for q in full}
    print(f"    {name}  {' → '.join(full)}")
    chk(f"{name}：路径 {len(full)} 点，只经过两端主帅自己的领地",
        lands <= {g1[0], g2[0]},
        f"领地={[CN[int(x)] for x in sorted(lands)]}")
print()
print("  ⇒ 关键推论：对任意一条'两在局方主帅 Y-Z 的线路'，")
print("     第三方 X 的军帐与这条线路**没有任何交点**（因为路径只经过 Y、Z 的领地）：")
for name, (g1, g2, full) in paths.items():
    allowed = {int(g1[0]), int(g2[0])}
    pset = set(full)
    for x in (1, 2, 3):
        if x in allowed:
            continue
        inter = pset & set(P.TENT[x])
        chk(f"{name}：{CN[x]}军帐 ∩ 路径 = ∅（{CN[x]}出局时副帅挡不到）",
            not inter, f"{sorted(inter)}")
chk("⇒ 副帅（只能在己方军帐内）永远站不到两帅之间 ⇒ **永不参与阻隔**（结论）",
    all(not (set(full) & set(P.TENT[x]))
        for _n, (g1, g2, full) in paths.items()
        for x in (1, 2, 3) if x not in {int(g1[0]), int(g2[0])}))
print()
print("  注意：路径**当然**包含两端主帅自己军帐内的点（115/125/135 就在魏帥那条线上）——")
print("  这正是『帅只能在军帐内走、却仍能走出共线』的原因：沿列5 上下走不会脱离这条线。")
print()
print("  副帅与在局方帅**共线**是可能的（它自己就是线路端点），但属《一、9》豁免：")
# 线路 O5-K5-A5-E5 = 215-…-115：魏帥115 与 蜀副帅215 同线且中间无子
s2 = mk({"115": pc(R.GENERAL, 1),
         "215": pc(R.GENERAL, 3, army=1, deputy=True)},
        turn=1, out=(3,), deputies={3: {"pos": "215", "owner": 1}})
print(f"    魏帥115 ↔ 蜀副帅215 共线 = {R.line_of_sight(s2, '115', '215')}")
chk("魏帥115 与 蜀副帅215 确实共线（端点关系，不是阻隔）",
    R.line_of_sight(s2, "115", "215") is True)
chk("「主帅 ↔ 副帅」不计入违规见面（generals_facing 只看主帅）",
    GA.facing_pairs(s2, strict=True) == [], f"{GA.facing_pairs(s2, strict=True)}")
chk("但副帅被登记进《一、9》第3条保护（第三方不得趁机吃它）",
    "215" in GA.protected_out_generals(s2),
    f"{GA.protected_out_generals(s2)}")

print()
print("=" * 78)
print("③ 副帅**可以吃在局方敌方的帅**（引擎不得有『副帅不能吃帅』的过滤）")
print("=" * 78)
# 蜀出局 → 其帅就地变副帅 315（归魏控制）；魏帥 114；吴帥 316（人为摆进蜀军帐，
# 目的是把"在局方敌方的帅"放进副帅的攻击范围 —— 真实对局中主帅出不了军帐）
s3 = mk({"114": pc(R.GENERAL, 1),
         "315": pc(R.GENERAL, 3, army=1, deputy=True),   # 魏控制的蜀副帅
         "316": pc(R.GENERAL, 2),                        # 吴帥
         "154": pc(R.PAWN, 2)},                          # 挡住 114↔316 共线
        turn=1, out=(3,), deputies={3: {"pos": "315", "owner": 1}})
chk("前提：局面不违反《一、9》", GA.facing_pairs(s3, strict=True) == [],
    f"{GA.facing_pairs(s3, strict=True)}")
lm3 = GA.legal_moves(s3, 1)
chk("副帅能吃在局方（吴）的帅：315→316 在合法着法里",
    ("315", "316") in lm3,
    f"魏(含副帅)合法 {len(lm3)} 步：{sorted(t for f, t in lm3 if f == '315')}")
chk("该目标点不在《一、9》第3条保护内（保护的是出局方的帅，不是吴帥）",
    "316" not in GA.protected_out_generals(s3),
    f"guard = {GA.protected_out_generals(s3)}")
# 反向：副帅**不能**吃自家 owner 的帅（那是同 army，属自家子）
s3b = mk({"316": pc(R.GENERAL, 1),
          "315": pc(R.GENERAL, 3, army=1, deputy=True),
          "215": pc(R.GENERAL, 2), "155": pc(R.PAWN, 2)},
         turn=1, out=(3,), deputies={3: {"pos": "315", "owner": 1}})
chk("副帅不能吃自己主人（魏）的帅（同 army = 自家子）",
    ("315", "316") not in GA.legal_moves(s3b, 1))

print()
print("=" * 78)
print("④ 【2026-09-25 新规则】《一、10》阻隔义务已退役 —— 蜀方无任何额外约束")
print("=" * 78)
# 线路 E5-A5-F5-J5 = 115-155-355-315：魏帥115、蜀帥315，中段 155/355
# C(吴) 抽离阻隔子 155 → 魏(1) 与 蜀(3) 照见，轮到蜀走
# 255 上留一枚吴兵：既挡住"魏-吴"（215-255-155-115），又挡住"吴-蜀"（315-355-255-215）
#
# 【新旧规则的差别（本节要钉住的东西）】
#   旧：《一、10》要求 A 必须"用棋阻隔在两帅之间、或移开己方帅"，
#       否则就算走无关的棋把 B 逼成判负 —— 于是 353 这类着法会被剔除。
#   新：照面不再违规 ⇒ **蜀想走什么就走什么**；而且此时双方反而**互相能射杀**。
s4 = mk({"115": pc(R.GENERAL, 1), "315": pc(R.GENERAL, 3),
         "215": pc(R.GENERAL, 2),
         "155": pc(R.PAWN, 2),          # C 的阻隔子（吴兵，站在魏 r5c5）
         "354": pc(R.PAWN, 3),          # 蜀兵（蜀 r5c4），可横走到 355（两帅之间）
         "255": pc(R.PAWN, 2)},         # 挡住另两对
        turn=2)
chk("前提：抽离前两帅不共线（155 吴兵挡着）",
    not R.line_of_sight(s4, "115", "315"))
# 抽离落点必须**避开 115↔315 那条线**，否则等于换了个点继续堵路（我第一次就踩了这个坑）
_path_115_315 = set(paths["E5-A5-F5-J5"][2])
wu_moves = [t for f, t in GA.legal_moves(s4, 2)
            if f == "155" and t not in _path_115_315]
chk("前提：吴可从 155 抽离（且不会顺手在别处把这条线堵上）", bool(wu_moves),
    f"{wu_moves}")
GA.apply(s4, "155", wu_moves[0])      # C（吴）抽离阻隔子
chk("抽离后轮到蜀（走棋顺序 C⇒A）", s4["turn"] == 3, f"turn={s4['turn']}")
chk("抽离后魏帥115 ↔ 蜀帥315 照见",
    R.line_of_sight(s4, "115", "315"))
chk("《一、10》判负待决机制已退役 → pending_judge 恒 None",
    GA.pending_judge(s4) is None, f"{GA.pending_judge(s4)}")
lm4 = GA.legal_moves(s4, 3)
t4 = sorted(t for f, t in lm4)
print(f"    蜀的合法落点 = {t4}")
# 【2026-09-25 老师口径】蜀兵 354（蜀 row5 列4）**未过河 ⇒ 不能横走 353**，
#   唯一正解 = 过河（跨赤壁）到吴 256。这步与两帅照面毫无关系，
#   所以照样必须被允许 —— 本节要钉的仍是「不再有阻隔义务」。
chk("★ 蜀兵 354→256（过河，**不在两帅之间**）也允许 —— 不再有阻隔义务",
    ("354", "256") in lm4, f"{sorted(t for f, t in lm4 if f == '354')}")
chk("★ 蜀帥 315→325（仍在线路上）同样允许 —— 照面不再是违规",
    ("315", "325") in lm4, f"{sorted(t for f, t in lm4 if f == '315')}")
chk("★ 双方此时**互相能射杀**（snipe_pairs 双向）",
    ("115", "315") in GA.snipe_pairs(s4) and ("315", "115") in GA.snipe_pairs(s4),
    f"{GA.snipe_pairs(s4)}")
chk("★ 蜀帥的着法里含 315→115：**直接射杀魏帥**（新规则的核心能力）",
    ("315", "115") in lm4, f"{sorted(t for f, t in lm4 if f == '315')}")
chk("对照：蜀帥移出线路的 314/316 当然也仍然允许（常规军帐移动）",
    {"314", "316"} <= set(t4), f"{sorted({'314', '316'} & set(t4))}")

print()
print("=" * 78)
print(f"合计 {OK} 通过 / {FAIL} 失败")
print("=" * 78)
sys.exit(1 if FAIL else 0)
