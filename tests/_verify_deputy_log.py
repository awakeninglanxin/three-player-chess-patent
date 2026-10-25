# -*- coding: utf-8 -*-
"""验证「战报字段丢失」bug 已修（老师 2026-10-01 报）

老师原话：
  ①「报了 bug：蜀的车吃完吴的帅后，蜀的车没有升级成副帅」
  ②「任何棋子吃了敌方的帅都会原地升级成副帅，并且敌方棋子变色变成己方」

**存档重放还原的真相**（`server/data/autosave.json`，全 109 手）：
  · ply 27 `229-225`：魏**炮**吃吴**真帅** ⇒ 炮**已经正确**就地升格为副帥（驻 225）；
  · ply 28 `227-225`：**蜀車**吃掉的正是**那枚副帥** ⇒ 依《一、7》原文
    「副帅……直至被吃掉（**棋子再次易主**）」⇒ **不产生新副帅**（引擎行为正确）。
  ⇒ 真 bug 是**战报**：`note.is_deputy` / `note.promoted_from` 只在 `web/app.js`
    里被读取，**服务端两处战报构造都没写进去** ⇒ 前端恒 undefined：
      · 斩真帅 → 少了「炮→副帥」（老师 09-25 明确要求过，等于没生效）；
      · 斩副帥 → 落到 `e.captured ? 吃 帥` ⇒ 显示成「吃 帥」
                 ⇒ 看起来就是"吃了帅却没升级成副帅"。

本测试四节：
  ① `move_log_entry()` 是唯一构造点，两个字段必带（含 None 也带）
  ② 吃**真帅** → `is_deputy=False` + `promoted_from=<凶手种类>`；吃**副帥** → True + None
  ③ `_repair_move_log()` 能把**老存档**里的历史条目回填正确（读真实 autosave 的副本）
  ④ 幂等：已填过的不再动；非 general 的吃子条目一律不碰

标签口径：引擎点位 id = 方 + 行 + 列；ARMY_CN = {1:魏, 2:吴, 3:蜀}。
"""
import json
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "server"))

from engine import game_dxf as GA      # noqa: E402
from engine import patent as P         # noqa: E402
from match import Match, move_log_entry  # noqa: E402

CN = {1: "魏", 2: "吴", 3: "蜀"}
OK = FAIL = 0


def chk(name, cond, detail=""):
    global OK, FAIL
    if cond:
        OK += 1
        print(f"  [OK]   {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}  {detail}")


def build(spec, turn):
    """造一个只含 spec 里棋子的局面（spec: pos -> (kind, army, home)）"""
    s = GA.new_game(first=turn)
    s["board"] = {}
    for pos, (kind, army, home) in spec.items():
        s["board"][pos] = {"kind": kind, "army": army, "home": home}
    P.refresh_combat(s)
    P.refresh_vitality(s)
    GA.mark_stale(s)
    s["turn"] = turn
    return s


print("=" * 74)
print("① `move_log_entry()` 唯一构造点：两个字段必带")
print("=" * 74)
note_full = {"captured": "general", "captured_army": 2, "eliminated": 2,
             "is_deputy": False, "promoted_from": "cannon"}
e = move_log_entry(1, "229", "225", 27, note_full, reason="x", model="人类")
chk("带 is_deputy", e.get("is_deputy") is False, e)
chk("带 promoted_from", e.get("promoted_from") == "cannon", e)
chk("基础字段仍在", (e["type"], e["army"], e["from"], e["to"], e["ply"],
                 e["captured"], e["captured_army"], e["eliminated"])
    == ("move", 1, "229", "225", 27, "general", 2, 2), e)
chk("extra 透传", e.get("reason") == "x" and e.get("model") == "人类", e)
chk("字段名固定（防止改名后前端又读不到）",
    set(e) >= {"type", "army", "from", "to", "ply", "captured", "captured_army",
               "eliminated", "is_deputy", "promoted_from"}, sorted(e))

print()
print("=" * 74)
print("② 吃真帅 vs 吃副帥：两个字段的真值")
print("=" * 74)
print("  —— 2a 吃**真帅**：凶手就地升格，promoted_from = 凶手种类 ——")
s = build({"215": ("general", 2, 2), "115": ("general", 1, 1),
           "335": ("general", 3, 3), "235": ("rook", 3, 3)}, turn=3)
chk("前提：蜀車 235 能吃到吴帥 215", ("235", "215") in GA.legal_moves(s, 3))
n = GA.apply(s, "235", "215")
chk("引擎已就地升格为副帥（位置 = 被吃帅原位）",
    s["board"]["215"].get("deputy") is True and s["board"]["215"]["army"] == 3,
    s["board"]["215"])
chk("note.is_deputy = False", n.get("is_deputy") is False, n)
chk("note.promoted_from = 'rook'（吃帅的是蜀車）",
    n.get("promoted_from") == "rook", n)
lg = move_log_entry(3, "235", "215", s["ply"], n, reason="人类接管")
chk("⇒ 前端能渲染「車→副帥」",
    lg["is_deputy"] is False and lg["promoted_from"] == "rook"
    and lg["eliminated"] == 2, lg)

print()
print("  —— 2b 吃**副帥**：不升格、残兵易主，绝不能再显示成「吃 帥」 ——")
m = Match.__new__(Match)                     # 不建 Bot，只借 manual_move 的记账
m.__dict__.update({
    "allow_undo": False, "log": [], "kills": {}, "slain": {}, "wrong": {},
    "undo_left": {}, "undo_used": {}, "snapshots": [], "replay": [],
    "epoch": 0, "graded": {}, "loss_sum": {}, "bad": {},
    "drawn": False, "max_ply": 300, "human_armies": {3}, "auto": False,
    "thinking": None, "difficulty": 3, "opts": {},
})
import threading                            # noqa: E402
m.lock = threading.RLock()
m.state = build({"215": ("general", 1, 2), "225": ("rook", 3, 3),
                 "115": ("general", 1, 1), "335": ("general", 3, 3)}, turn=3)
m.state["board"]["215"]["deputy"] = True
m.state["deputies"] = {2: {"pos": "215", "owner": 1}}
P.refresh_combat(m.state)
m._autosave = lambda *a, **k: None
m._record_replay = lambda *a, **k: None
r = m.manual_move("225", "215")
chk("manual_move 成功", r.get("ok") is True, r)
chk("吃的是副帥（引擎侧 note 已标记）",
    m.log[-1].get("is_deputy") is True, m.log[-1])
chk("is_deputy=True 且 promoted_from 为空 ⇒ 前端走「斩副帥」分支",
    m.log[-1]["is_deputy"] is True and not m.log[-1]["promoted_from"], m.log[-1])
chk("eliminated 为空（吃副帥不代表任何方出局）",
    m.log[-1].get("eliminated") in (None, []), m.log[-1])
chk("旧代码在这里会退化成「吃 帥」：c a p t u r e d = general 仍在（前端靠 is_deputy 分流）",
    m.log[-1].get("captured") == "general"
    and m.state["board"]["215"]["kind"] == "rook"
    and not m.state["board"]["215"].get("deputy"), m.state["board"]["215"])
chk("残兵易主（annexed[2] = 3 蜀）", m.state["annexed"].get(2) == 3,
    m.state["annexed"])

print()
print("=" * 74)
print("③ `_repair_move_log()` 回填**真实存档**的历史战报")
print("=" * 74)
src = os.path.join(ROOT, "server", "data", "autosave.json")
if not os.path.exists(src):
    print("  [SKIP] 没有 autosave.json（新机器）")
else:
    tmp = tempfile.mkdtemp(prefix="dep_log_")
    cp = os.path.join(tmp, "autosave.json")
    shutil.copy2(src, cp)                    # ★ 用副本，绝不碰老师的真实存档
    mm = Match()                             # 只 restore，**不** enable_autosave
    info = mm.restore(cp)
    chk("续局成功", info.get("restored") is True, info)
    mv = [x for x in mm.log if x.get("type") == "move"]
    gen = [x for x in mv if x.get("captured") == "general"]
    print(f"       战报 {len(mv)} 条，其中吃 general {len(gen)} 条")
    chk("每条吃 general 的战报都已带 is_deputy（不再是缺字段）",
        all(x.get("is_deputy") is not None for x in gen),
        [x for x in gen if x.get("is_deputy") is None])
    # 与"重放真相"对拍：吃真帅 升格 / 吃副帥 不升格
    #   ★ 原写法把 **ply27 / ply28 的内容写死**（针对 2026-09-24 那一局），
    #     老师一重开新局就必然假失败 —— 2026-10-02 实测红过一次（22/1）。
    #     ⇒ 改成**按语义挑样本**：谁吃真帅、谁吃副帥，由存档自己说了算。
    #     ⚠️ 必须带 `if` 守卫：样本为空时 `all([])` 恒为 True ⇒ 假绿灯。
    dep = [x for x in gen if x.get("is_deputy") is True]
    real = [x for x in gen if x.get("is_deputy") is False]
    if dep:
        chk(f"吃**副帥**（ply{dep[0]['ply']}）⇒ is_deputy=True 且 promoted_from 为空",
            all(x.get("promoted_from") is None for x in dep),
            [x for x in dep if x.get("promoted_from") is not None])
    else:
        print("       （本存档没有「吃副帥」的条目 —— 跳过，不算失败）")
    if real:
        chk(f"吃**真帅**（ply{real[0]['ply']}）⇒ is_deputy=False 且 promoted_from 写明凶手",
            all(x.get("promoted_from") for x in real),
            [x for x in real if not x.get("promoted_from")])
    else:
        print("       （本存档没有「吃真帅」的条目 —— 跳过，不算失败）")
    print(f"       吃 general {len(gen)} 条 = 吃真帅 {len(real)} + 吃副帥 {len(dep)}")
    last = [x for x in mv if x.get("eliminated")][-1:]
    if last:
        chk(f"最近一次斩帅（ply{last[0]['ply']}）有 promoted_from ⇒ 能显示「x→副帥」",
            bool(last[0].get("promoted_from")), last[0])

    print()
    print("=" * 74)
    print("④ 幂等 + 不误伤")
    print("=" * 74)
    snap = json.dumps(mm.log, ensure_ascii=False, sort_keys=True)
    chk("再回填一次 = 0 条（幂等）", mm._repair_move_log() == 0)
    chk("回填不改变已填内容",
        json.dumps(mm.log, ensure_ascii=False, sort_keys=True) == snap)
    chk("非 general 的吃子条目 is_deputy 仍为 None（不误填）",
        all(x.get("is_deputy") is None
            for x in mv if x.get("captured") not in (None, "general")),
        [x for x in mv if x.get("captured") not in (None, "general")
         and x.get("is_deputy") is not None][:2])

print()
print("=" * 74)
print(f"结果：{OK} 通过 / {FAIL} 失败")
print("=" * 74)
sys.exit(1 if FAIL else 0)
