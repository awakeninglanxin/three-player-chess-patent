# -*- coding: utf-8 -*-
"""认输机制验证 —— 老师 2026-09-24 口径：「不存在求和，只允许认输」。

语义（与《一、10》判负同类）：
  · 认输方 **不再行棋**（`out` + `resigned`）；
  · 帅 **留着在盘上**、棋子 **不易主**（依《一、6》，另两方不能控制但可以吃）；
  · **不等于出局** —— 「出局」的唯一触发条件仍是主帅被吃（不写 `eliminated`）。
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


def pc(kind, home, army=None, deputy=False):
    d = {"kind": kind, "army": army or home, "home": home}
    if deputy:
        d["deputy"] = True
    return d


def base(turn=1):
    # 三帅 + 三点堵子（让三对帅都不违规见面）
    b = {"115": pc(R.GENERAL, 1), "215": pc(R.GENERAL, 2), "315": pc(R.GENERAL, 3),
         "155": pc(R.PAWN, 2), "255": pc(R.PAWN, 2), "355": pc(R.PAWN, 2),
         "144": pc(R.ROOK, 1)}
    s = GA.new_game(first=turn)
    s["board"] = {k: dict(v) for k, v in b.items()}
    s["out"], s["eliminated"], s["annexed"] = [], [], {}
    s["declared_lose"], s["resigned"] = [], []
    s["deputies"] = {}
    s["history"], s["passed"], s["ply"] = [], [], 0
    P.refresh_combat(s)
    return s


print("=" * 78)
print("1. 单方认输：失去资格，但帅留盘、棋子不易主、不算出局")
print("=" * 78)
s = base(turn=1)
n0 = len(s["board"])
arms0 = {p: q["army"] for p, q in s["board"].items()}
chk("前提：不违反《一、9》", GA.facing_pairs(s, strict=True) == [])
r = GA.resign(s, 1)
chk("返回事件 type=resign", (r or {}).get("type") == "resign", f"{r}")
chk("认输方进入 out（失去行棋资格）", 1 in s["out"], f"out={s['out']}")
chk("认输方记入 resigned", s.get("resigned") == [1], f"{s.get('resigned')}")
chk("**不**记入 eliminated（认输 ≠ 出局）",
    s["eliminated"] == [], f"{s['eliminated']}")
chk("主帅仍留在盘上（115 还在）", "115" in s["board"], f"{sorted(s['board'])}")
chk("棋子归属未被改动（不易主）",
    {p: q["army"] for p, q in s["board"].items()} == arms0)
chk("棋子总数不变", len(s["board"]) == n0, f"{n0} → {len(s['board'])}")
chk("认输方战斗力 = False", s["combat"][1] is False, f"{s['combat']}")
chk("认输方生命力 = True（帅还在盘上）", s["vitality"][1] is True,
    f"{s['vitality']}")
chk("回合交给下一方（认输方被跳过）", s["turn"] == 2, f"turn={s['turn']}")
chk("alive_armies 里不再有认输方", 1 not in GA.alive_armies(s),
    f"{GA.alive_armies(s)}")
chk("认输方 legal_moves 为空", GA.legal_moves(s, 1) == [])
chk("认输方不能被再次判负/认输（引擎返回 None）", GA.resign(s, 1) is None)

print()
print("  认输方棋子「不能控制但可以吃」（《一、6》）：")
s2 = base(turn=1)
s2["board"]["125"] = pc(R.ROOK, 2)           # 吴車已深入魏军帐
GA.resign(s2, 1)
targets = {p for p, q in s2["board"].items() if q["army"] == 1}
lm = GA.legal_moves(s2, 2)
eats = [(f, t) for f, t in lm if t in targets]
chk("吴的合法着法里存在『吃魏（认输方）棋子』的走法", bool(eats),
    f"{eats[:6]}")
chk("其中包含吃魏帥 125→115", ("125", "115") in lm,
    f"魏方棋子点 = {sorted(targets)}")
chk("但魏（认输方）自己一步也走不了", GA.legal_moves(s2, 1) == [])

print()
print("=" * 78)
print("2. 两方认输 → 剩下一方胜")
print("=" * 78)
s3 = base(turn=1)
GA.resign(s3, 1)
chk("一方认输后仍无 winner", s3["winner"] is None, f"{s3['winner']}")
GA.resign(s3, 2)
chk("两方认输后 winner = 蜀(3)", s3["winner"] == 3, f"{s3['winner']}")
chk("三方状态：out 含 1、2；eliminated 仍为空（没人被吃帅）",
    1 in s3["out"] and 2 in s3["out"] and s3["eliminated"] == [],
    f"out={s3['out']} elim={s3['eliminated']}")
chk("alive_armies = [3]", GA.alive_armies(s3) == [3], f"{GA.alive_armies(s3)}")

print()
print("=" * 78)
print("3. 认证语义：认输后帅被吃 → 这一刻才记 eliminated")
print("=" * 78)
s4 = base(turn=1)
GA.resign(s4, 1)
chk("认输时 eliminated 为空", s4["eliminated"] == [])
# 蜀車 316（人为摆进魏军帐）吃掉魏帥 115 ？—— 用就近摆法：魏帥 115 的邻点 125
s4["board"]["125"] = pc(R.ROOK, 3)
s4["board"].pop("155", None)                 # 清掉挡子，避免干扰
mov = GA.legal_moves(s4, 3)
note = GA.apply(s4, "125", "115") if ("125", "115") in mov else None
chk("蜀車 125→115 允许吃掉「已认输方」的帅", note is not None,
    f"蜀合法 {len(mov)} 步")
if note is not None:
    chk("吃帅这一刻才把魏记入 eliminated（真·出局）",
        1 in s4["eliminated"], f"{s4['eliminated']}")
    chk("认输标记仍在（resigned 不被清）", 1 in s4["resigned"])
    chk("★ 吃帅的蜀車就地在 115 升格为副帅（原棋子从盘上消失）",
        (s4["board"].get("115") or {}).get("deputy") is True
        and s4["board"]["115"]["army"] == 3,
        f"115 = {s4['board'].get('115')}")
    chk("★ 战报记录升格前的棋子种类 promoted_from=rook",
        note.get("promoted_from") == R.ROOK, f"实际 {note.get('promoted_from')!r}")

print()
print("=" * 78)
print("4. match.Match.resign 接口")
print("=" * 78)
sys.path.insert(0, "server")
from match import Match                        # noqa: E402
from agents import llm as LLM                  # noqa: E402
m = Match(LLM.load_roster())
m.auto = False
res = m.resign(2)
chk("接口返回 ok", res.get("ok") is True, f"{res}")
chk("状态里 resigned 含 2", 2 in m.state.get("resigned", []),
    f"{m.state.get('resigned')}")
chk("战报里出现 type=resign 的事件",
    any(e.get("type") == "resign" for e in m.log),
    f"{[e.get('type') for e in m.log][:5]}")
r2 = m.resign(2)
chk("重复认输被拒", r2.get("ok") is False, f"{r2}")
r3 = m.resign(9)
chk("非法 army 被拒", r3.get("ok") is False, f"{r3}")

print()
print("=" * 78)
print("5. 残局判平（老师 2026-09-24）")
print("   「车马炮兵都没有了，谁也将不死谁，留下的都是象、士，9 次轮盘之后")
print("    多方帅都不照面 → 自动判定场上剩下的各方平局」")
print("=" * 78)
# 只剩 帅 + 象/士；用 135 / 235 / 335 三点把三对帅的视线都挡住
ONLY_EA = {
    "115": pc(R.GENERAL, 1), "124": pc(R.ELEPHANT, 1), "135": pc(R.ADVISOR, 1),
    "215": pc(R.GENERAL, 2), "224": pc(R.ELEPHANT, 2), "235": pc(R.ADVISOR, 2),
    "315": pc(R.GENERAL, 3), "324": pc(R.ELEPHANT, 3), "335": pc(R.ADVISOR, 3),
}
s5 = base(turn=1)
s5["board"] = {k: dict(v) for k, v in ONLY_EA.items()}
P.refresh_combat(s5)
chk("前提：不违反《一、9》", GA.facing_pairs(s5, strict=True) == [],
    f"{GA.facing_pairs(s5, strict=True)}")
chk("识别为「只剩象/士」残局", GA.only_ele_adv(s5) is True)
chk("未计时前不判平", GA.stalemate_draw(s5) is False)
GA.mark_stale(s5)
chk("计时起点 = 当前 ply（0）", s5["stale_from_ply"] == 0,
    f"{s5['stale_from_ply']}")
s5["ply"] = GA.STALEMATE_ROUNDS * 3 - 1          # 差 1 个半回合
chk(f"未满 {GA.STALEMATE_ROUNDS} 轮（{s5['ply']} 步）不判平",
    GA.stalemate_draw(s5) is False, f"rounds={GA.stale_rounds(s5)}")
s5["ply"] = GA.STALEMATE_ROUNDS * 3              # 满 27 步 = 9 轮
chk(f"满 {GA.STALEMATE_ROUNDS} 轮（27 步）→ 判平",
    GA.stalemate_draw(s5) is True, f"rounds={GA.stale_rounds(s5)}")

s6 = base(turn=1)
s6["board"] = {k: dict(v) for k, v in ONLY_EA.items()}
s6["board"]["125"] = pc(R.ROOK, 1)               # 还剩一门车
P.refresh_combat(s6)
GA.mark_stale(s6)
s6["ply"] = 99
chk("还有车 → 不判平（谁也将得死谁）", GA.stalemate_draw(s6) is False)
chk("计时点不记录（stale_from_ply 保持 None）", s6["stale_from_ply"] is None)

s7 = base(turn=1)
s7["board"] = {k: dict(v) for k, v in ONLY_EA.items()}
s7["board"]["145"] = pc(R.ROOK, 2)
s7["out"] = [2]                                  # 吴已出局
s7["combat"][2] = False
P.refresh_combat(s7)
chk("出局方名下还有车 → **仍算**残局（它已不能行动）",
    GA.only_ele_adv(s7) is True)
GA.mark_stale(s7)
s7["ply"] = 27
chk("出局方的车不妨碍判平", GA.stalemate_draw(s7) is True)

print()
print("  Match 集成：")
sys.path.insert(0, "server")
from match import Match                        # noqa: E402
from agents import llm as LLM                  # noqa: E402
mm = Match(LLM.load_roster())
mm.auto = False
# ⚠️ 必须显式清空人类席位：agents.json 的开局默认是 `human_armies: [1]`（魏归老师），
#   而 step() 对"人类接管的方"会**直接 return 不代走** ⇒ 这条集成测试会假失败。
#   本测试要验的是「残局自动判平」，前提是三方全 Bot。
mm.human_armies = set()
mm.state["board"] = {k: dict(v) for k, v in ONLY_EA.items()}
mm.state["stale_from_ply"] = 0
mm.state["ply"] = 27
mm.step()
chk("对局被判平（drawn=True）", mm.drawn is True, f"drawn={mm.drawn}")
chk("战报出现 draw 事件且文案点明残局",
    any(e.get("type") == "draw" and "残局" in (e.get("text") or "") for e in mm.log),
    f"{[e.get('text') for e in mm.log if e.get('type') == 'draw']}")
chk("判平后 _finished() 为真", mm._finished() is True)

print()
print("=" * 78)
print(f"合计 {OK} 通过 / {FAIL} 失败")
print("=" * 78)
sys.exit(1 if FAIL else 0)
