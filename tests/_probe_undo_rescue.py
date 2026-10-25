# -*- coding: utf-8 -*-
"""探针：**终局之后，被斩方还剩的机会能不能用来「退回将军之前」？**

回答老师 2026-10-02 的要求：
  「虽然是游戏结束了，但是魏国还剩一次悔棋机会，
    应该允许魏国退回到将军之前」

改动前的两道闸门（都被本探针钉死）：
  ① 后端 `match.py`：`undo_last()` 开头 `if self._finished(): return "对局已结束"`
  ② 前端 `app.js`  ：`btnU.disabled = !(… && !st.finished)`
     ⇒ 老师看到的就是「悔棋键禁止点击」。

改动后语义（**只放行被斩方**，不开后门）：
  · 终局由「主帅被斩」造成 ⇒ 被斩方若还剩机会，可退回自己上次落子前
    （＝被将军之前）重走；悔棋后 `winner` 清空、对局**复活**。
  · 终局由「判和 / 超时」造成 ⇒ `_rescue_army()` 返回 None ⇒ 维持原判拒绝。
  · 未被斩的方（胜方）不参与自救 —— 撤回自己的取胜手没有语义。

⚠️【2026-10-02 重构】**不再读老师的实时存档**。
   第一版直接拷 `server/data/autosave.json` 当夹具，结果老师在对弈台上玩了两手
   （ply 64→65、点掉悔棋机会），探针立刻 16 条失败 —— 它把"老师此刻的存档"
   当成了固定输入。现在改为**内存自建局面**：用 `Match.manual_move()` 走真实产线
   路径（推快照 → 落子 → 记战报 → 回看缓冲），既有真路径覆盖，又完全可重现、
   且绝不触碰任何存档文件。
"""
import inspect
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, os.path.join(_ROOT, "server"))

import match as M                              # noqa: E402
from engine import game_dxf as GA              # noqa: E402
from engine import rules_dxf as R              # noqa: E402

CN = {1: "魏", 2: "吴", 3: "蜀"}
OK = FAIL = 0


def chk(name, cond, extra=""):
    global OK, FAIL
    if cond:
        OK += 1
        print(f"  [OK]   {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}" + (f"   << {extra}" if extra else ""))


def build_scene():
    """自建一个「吴已出局、轮到魏、魏还剩 1 次悔棋」的中局（内存，不落盘）。

    盘面：魏帥 115（回合方）/ 蜀帥 315 / 驻吴帐的蜀方副帅 225（deputy）/ 魏車 111。
    计划：魏走 111 的一手（**避开列5**，让魏帥留在 115），
          蜀副帅 225→115 射杀魏帥 ⇒ 复现老师那局 ply 64 的"副帅射杀主帅"终局。

    ⚠️ 点位不是随便挑的：`225↔115` 才是规则图上那条跨方见面线
       （`RAYS` 实测共线），`225↔125` **不共线** —— 第一版探针让魏帥走到 125
       再让副帅 225 去斩，`legal_moves` 里根本没有这一手（本次踩过）。
       所以魏方的第一手必须走一枚**不碰列5**的子。
    """
    m = M.Match(auto=False)
    m.auto = False
    m.allow_undo = True
    m.undo_left = {1: 1, 2: 3, 3: 3}       # 魏「还剩一次」——老师原话
    m.undo_used = {1: 0, 2: 0, 3: 0}
    m.human_armies = {1}                   # 魏是人类的席位
    m.drawn = False
    m.log = []
    m.snapshots = []
    m.replay = []
    m.autosave_path = None                 # ★ 绝不落盘
    st = GA.new_game(first=1)
    st["board"] = {
        "115": {"kind": "general", "army": 1, "home": 1},   # 魏帥（E5 底线中点）
        "315": {"kind": "general", "army": 3, "home": 3},   # 蜀帥
        "225": {"kind": "general", "army": 3, "home": 2, "deputy": True},  # 蜀方副帅（驻吴帐 N5）
        "111": {"kind": "rook", "army": 1, "home": 1},      # 魏車（给魏方一手可走，避开列5）
    }
    st["ply"] = 40
    st["turn"] = 1
    st["eliminated"] = [2]                 # 吴已出局（主帅早被斩）
    st["out"] = [2]
    st["annexed"] = {2: 3}
    st["deputies"] = {2: {"pos": "225", "owner": 3}}
    st["vitality"] = {1: True, 2: False, 3: True}
    st["combat"] = {1: True, 2: False, 3: True}
    m.state = st
    m._record_replay()
    return m


print("=" * 78)
print("§A 起点自建：吴已出局、轮到魏、魏还剩 1 次悔棋")
print("=" * 78)
m0 = build_scene()
chk("起点未终局（还有魏、蜀两方在世）", m0._finished() is False)
chk("起点 turn=1（魏）", m0.state["turn"] == 1, f"turn={m0.state['turn']}")
chk("起点 eliminated=[2]（吴已出局）", m0.state["eliminated"] == [2],
    f"{m0.state['eliminated']}")
chk("起点魏方还剩 1 次悔棋机会", m0.undo_left.get(1) == 1, f"{m0.undo_left}")
chk("起点 undo_rescue=0（没终局就谈不上自救）",
    m0.snapshot().get("undo_rescue") == 0, f"{m0.snapshot().get('undo_rescue')}")
chk("★ 前提：`225↔115` 确实共线（规则图那条跨方见面线）",
    bool(R.line_of_sight(m0.state, "225", "115")), "实测 RAYS")
chk("★ 前提：副帅 225 的射杀目标就是魏帥 115",
    R.snipe_targets(m0.state["board"], "225", 3, frozenset()) == ["115"],
    f"{R.snipe_targets(m0.state['board'], '225', 3, frozenset())}")
chk("★ 对照：`225↔125` 虽几何共线，但 125 是**空点** ⇒ 不构成射杀目标",
    ("225", "125") not in GA.legal_moves(m0.state, 3)
    and "125" not in R.snipe_targets(m0.state["board"], "225", 3, frozenset()))
_mv1 = [m for m in GA.legal_moves(m0.state, 1) if m[0] == "111"]
chk("前提：魏車 111 有可走的一手（且不碰列5）", len(_mv1) > 0, f"{_mv1[:4]}")

print()
print("=" * 78)
print("§B 走真实产线两步，制造「副帅射杀主帅」终局")
print("=" * 78)
r1 = m0.manual_move(*_mv1[0])              # 魏方走車（推快照 army=1，不动魏帥）
chk(f"魏方落子 {_mv1[0][0]}→{_mv1[0][1]} 成功", r1.get("ok") is True, f"{r1}")
chk("★ 魏帥仍在 115（第一手没动它）",
    (m0.state["board"].get("115") or {}).get("army") == 1,
    f"115={m0.state['board'].get('115')}")
chk("快照链已有 1 条（army=1）", len(m0.snapshots) == 1
    and m0.snapshots[-1]["army"] == 1, f"{m0.snapshots[-1]['army'] if m0.snapshots else None}")
chk("轮次交给蜀（吴已出局、被跳过）", m0.state["turn"] == 3,
    f"turn={m0.state['turn']}")
r2 = m0.manual_move("225", "115")          # 蜀副帅射杀魏帥（推快照 army=3）——老师那局的真实点位
chk("蜀方副帅 225→115 射杀魏帥成功", r2.get("ok") is True, f"{r2}")
chk("最后一手 = 副帅射杀主帅（is_deputy 为假、eliminated=1）",
    (m0.log[-1].get("army"), m0.log[-1].get("from"), m0.log[-1].get("to"),
     m0.log[-1].get("captured"), m0.log[-1].get("eliminated")) ==
    (3, "225", "115", "general", 1), f"{m0.log[-1]}")

st = m0.snapshot()
chk("snapshot().finished is True（终局）", st["finished"] is True)
chk("winner=3（蜀）", m0.state.get("winner") == 3, f"winner={m0.state.get('winner')}")
chk("eliminated=[2,1]（吴、魏均被斩）", m0.state.get("eliminated") == [2, 1],
    f"{m0.state.get('eliminated')}")
chk("★ snapshot().undo_rescue == 1（前端据此放行按钮）",
    st.get("undo_rescue") == 1, f"undo_rescue={st.get('undo_rescue')}")
chk("★ snapshot().can_undo is True（终局后仍可悔）",
    st.get("can_undo") is True, f"can_undo={st.get('can_undo')}")
chk("★ snapshot().undo_who == 1（终局推定直指被斩方，不是刚斩帅的蜀）",
    st.get("undo_who") == 1, f"undo_who={st.get('undo_who')}")

print()
print("=" * 78)
print("§C 终局自救：真的退回了「将军之前」")
print("=" * 78)
ply_before = m0.state["ply"]
res = m0.undo_last()                       # army=None ⇒ 走 rescue 推定
chk("undo_last() 返回 ok", res.get("ok") is True, f"{res}")
chk("目标方 = 1（魏）", res.get("army") == 1, f"{res}")
chk("连带退回 2 手（蜀斩帅 + 魏自己那步）", res.get("rolled_back") == 2, f"{res}")
chk("魏方机会用掉 ⇒ 剩余 0", m0.undo_left.get(1) == 0, f"{m0.undo_left}")

chk("★ 对局复活：winner 已清空", m0.state.get("winner") is None,
    f"winner={m0.state.get('winner')}")
chk("★ 魏方回到局中：eliminated 只剩 [2]（吴仍出局）",
    m0.state.get("eliminated") == [2], f"eliminated={m0.state.get('eliminated')}")
chk("★ out 同步恢复为 [2]", m0.state.get("out") == [2], f"out={m0.state.get('out')}")
chk("★ 轮次回到魏方（turn=1）", m0.state.get("turn") == 1,
    f"turn={m0.state.get('turn')}")
chk("★ ply 退回 2 手", m0.state.get("ply") == ply_before - 2,
    f"ply {ply_before} → {m0.state.get('ply')}")
chk("★ 魏主帅回到棋盘上（115 原位的走子已撤回）",
    (m0.state["board"].get("115") or {}).get("army") == 1
    and (m0.state["board"].get("115") or {}).get("kind") == "general"
    and (m0.state["board"].get("115") or {}).get("deputy") is None,
    f"115={m0.state['board'].get('115')}")
chk("★ 蜀副帅退回原位 225（斩帅那手一并撤回）",
    (m0.state["board"].get("225") or {}).get("deputy") is True
    and (m0.state["board"].get("225") or {}).get("army") == 3,
    f"225={m0.state['board'].get('225')}")

st2 = m0.snapshot()
chk("悔棋后 snapshot().finished is False（不再终局）",
    st2["finished"] is False, f"finished={st2['finished']}")
chk("悔棋后 undo_rescue 归 0", st2.get("undo_rescue") == 0,
    f"undo_rescue={st2.get('undo_rescue')}")
undo_logs = [e for e in m0.log if e.get("type") == "undo" and e.get("army") == 1]
chk("战报记了一条「终局自救」悔棋", bool(undo_logs)
    and "终局自救" in undo_logs[-1].get("text", ""), f"{undo_logs[-1:]}")
chk("悔棋后对局自动暂停（不留悬空的长考）", m0.auto is False, f"auto={m0.auto}")

print()
print("=" * 78)
print("§D 边界：不许把「悔棋」变成取消终局的万能钥匙")
print("=" * 78)


def to_endgame():
    """复用一个新场景，走两步进入「副帅射杀主帅」终局，返回 Match。"""
    m = build_scene()
    mv1 = [x for x in GA.legal_moves(m.state, 1) if x[0] == "111"][0]
    a = m.manual_move(*mv1)
    b = m.manual_move("225", "115")
    assert m._finished(), (f"场景未进终局：r1={a} r2={b} "
                           f"turn={m.state['turn']} ply={m.state['ply']}")
    return m


# D1：终局 + 被斩方机会已用完 ⇒ 仍拒绝
m1 = to_endgame()
m1.undo_left[1] = 0
r1 = m1.undo_last()
chk("魏方机会=0 时，终局悔棋被拒（error='对局已结束'）",
    r1.get("ok") is False and r1.get("error") == "对局已结束", f"{r1}")
chk("被拒后局面**分毫未动**（winner 仍是 3）",
    m1.state.get("winner") == 3, f"winner={m1.state.get('winner')}")

# D2：判和终局 ⇒ 没有「将军之前」可言，不给自救
m2 = to_endgame()
m2.state["winner"] = None
m2.state["eliminated"] = []
m2.state["out"] = []
m2.drawn = True
chk("判和终局时 _rescue_army() 返回 None", m2._rescue_army() is None,
    f"{m2._rescue_army()}")
chk("判和终局时 snapshot().undo_rescue == 0",
    m2.snapshot().get("undo_rescue") == 0)
r2 = m2.undo_last()
chk("判和终局时悔棋被拒", r2.get("ok") is False, f"{r2}")

# D3：胜方（蜀）不能借终局撤回自己的取胜手
m3 = to_endgame()
r3 = m3.undo_last(army=3)
chk("终局时点名胜方（蜀=3）悔棋，被拒",
    r3.get("ok") is False and r3.get("error") == "对局已结束", f"{r3}")

# D4：被斩方在快照链里已无落子（机会有、但无从退）⇒ 不给假按钮
m4 = to_endgame()
m4.snapshots = [sn for sn in m4.snapshots if sn["army"] != 1]
chk("快照链里没有魏方的棋时，_rescue_army() 返回 None（防点不动的按钮）",
    m4._rescue_army() is None, f"{m4._rescue_army()}")

print()
print("=" * 78)
print("§E 结构断言（防回退 / 防漏字段）")
print("=" * 78)
# ★ 回归钉子：存档里的快照经 JSON 往返会把 int 键变字符串键，
#   而"重启续局 + 终局自救"是第一条必然跨存档用快照的路径 ⇒
#   不归一化就崩在 snapshot() 的 self.graded[k]（KeyError: 1）。
m5 = build_scene()
_mv5 = [x for x in GA.legal_moves(m5.state, 1) if x[0] == "111"][0]
m5.manual_move(*_mv5)
sn5 = m5.snapshots[-1]
chk("快照 graded / kills / slain / loss_sum 的键都是 int",
    all(isinstance(k, int) for d_ in (sn5["graded"], sn5["kills"],
                                      sn5["slain"], sn5["loss_sum"])
        for k in d_),
    f"graded={list(sn5['graded'])[:3]}")
chk("restore() 里确实调用了 _norm_snap（读回快照时归一化键）",
    "_norm_snap(sn)" in inspect.getsource(M.Match.restore))

src_push = inspect.getsource(M.Match._push_snapshot)
chk("_push_snapshot 存了 drawn（否则判和回滚不掉、悔棋后立刻又终局）",
    '"drawn"' in src_push)

src_undo = inspect.getsource(M.Match.undo_last)
chk("undo_last 里有「终局自救」分支", "终局自救" in src_undo)
chk("undo_last 的准入含「必须在 eliminated 里」",
    'self.state.get("eliminated")' in src_undo)
chk("undo_last 有判和回滚（self.drawn = bool(snap.get(...))）",
    'self.drawn = bool(snap.get("drawn", False))' in src_undo)

chk("_undo_plan 终局时先认被斩方（调 _rescue_army）",
    "_rescue_army()" in inspect.getsource(M.Match._undo_plan))

src_snap = inspect.getsource(M.Match.snapshot)
chk("snapshot 输出 undo_rescue", '"undo_rescue"' in src_snap)
chk("snapshot 的 can_undo 把「终局但可自救」算作可悔",
    "not fin or rescue" in src_snap)

chk("_rescue_army 要求「快照链里确有该方的棋」（防点不动的假按钮）",
    'sn["army"] for sn in self.snapshots' in
    inspect.getsource(M.Match._rescue_army))

# ★【2026-10-02】restore 只清副帅账本、不重算 vitality/combat
src_restore = inspect.getsource(M.Match.restore)
chk("restore() 调 prune_deputies 清幽灵副帅登记",
    "prune_deputies" in src_restore)
chk("restore() **不**调 refresh_combat（避免覆盖存档已算好的 vitality/combat）",
    "P.refresh_combat(" not in src_restore)

print()
print("=" * 78)
print("§F 前端：按钮在终局自救时不再被禁用")
print("=" * 78)
js = open(os.path.join(_ROOT, "web", "app.js"), encoding="utf-8").read()
chk("app.js 读了 st.undo_rescue", "st.undo_rescue" in js)
chk("app.js 的 disabled 放行「终局但可自救」",
    "(!st.finished || rescue)" in js)
chk("app.js 有终局自救的提示文案", "悔棋自救" in js or "退回被将军之前" in js)
chk("app.js 悔棋后会复位回看位置（backOffset = 0）",
    "backOffset = 0; viewSnap = null;" in js)

print()
print("=" * 78)
print(f"结果：{OK} 通过 / {FAIL} 失败")
print("=" * 78)
if FAIL:
    print("❌ 有断言未通过 —— 改动不成立，需查源码")
else:
    print("✅ 全部通过：终局后被斩方可用剩余机会「退回将军之前」；")
    print("   判和/超时终局、机会已用完、胜方 —— 三种情形仍被拒（无后门）。")
sys.exit(1 if FAIL else 0)
