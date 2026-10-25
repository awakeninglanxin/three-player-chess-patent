# -*- coding: utf-8 -*-
"""悔棋计数口径专项验证 —— 「只扣自己，连带退回其他方」· 独立 Match 实例，不碰运行中的服务

老师 2026-10-01 原话：
  「注意当我魏国点悔棋的时候，其它方不算悔棋次数，但是其它方要退回一步，
    只有魏国算一次悔棋次数。否则不合理」

【为什么要改】三方棋回合是 魏→吴→蜀→魏…，「轮到我走」时最后落子的其实是**对手**。
  旧实现只撤最后一步 ⇒ 魏方点悔棋撤的是**蜀方**的棋、还白扣蜀方一次机会，
  撤完仍然轮到魏走 —— 悔棋等于没悔，还把对手的次数吃掉。完全反直觉。

【新口径】撤到 `target` 方（= 点悔棋的那一方）**自己上次落子之前**：
  · 魏刚走完就点 → 撤 1 手（纯单步，与旧行为一致）
  · 轮到魏、吴蜀已各走一步 → 撤 3 手（蜀+吴+魏），回到魏上次落子前
  · **只扣 target 一次**，被连带退回的方一次都不扣

运行：python tests/_verify_undo_multi.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "server"))

from match import Match                     # noqa: E402
import engine.game_dxf as GA               # noqa: E402

ok = 0
bad = 0


def chk(cond, msg, extra=""):
    global ok, bad
    if cond:
        ok += 1
        print(f"  [OK]   {msg} {extra}")
    else:
        bad += 1
        print(f"  [FAIL] {msg} {extra}")


def sect(n, t):
    print("\n" + "=" * 74)
    print(f"第 {n} 节 · {t}")
    print("=" * 74)


def fresh(human=(1,), undo_per=3, first=1, allow_undo=True):
    """独立 Match。auto=False 防 _loop 抢走；alive=False 让 daemon 线程立刻退出。"""
    m = Match(auto=False)
    m.alive = False
    m.human_armies = set(human)
    m.undo_per_side = undo_per
    m.allow_undo = allow_undo
    m.undo_left = {1: undo_per, 2: undo_per, 3: undo_per}
    m.undo_used = {1: 0, 2: 0, 3: 0}
    return m


def walk(m, n):
    """按回合顺序走 n 手合法着法，返回 [(from, to), ...]"""
    out = []
    for _ in range(n):
        if m._finished():
            break
        legal = GA.legal_moves(m.state, m.state["turn"])
        if not legal:
            break
        a, b = legal[0]
        if not m.manual_move(a, b).get("ok"):
            break
        out.append((a, b))
    return out


def board_of(m):
    return {p: (v.get("kind"), v.get("army")) for p, v in m.state["board"].items()}


print("=" * 74)
print("悔棋计数口径 —— 「只扣自己，连带退回其他方」（老师 2026-10-01）")
print("=" * 74)

# ============================================================================
sect(1, "① 单步：魏刚走完就悔 → 只撤 1 手（与旧行为一致，不误伤）")

m = fresh(human=(1,))
mv = walk(m, 1)
chk(len(mv) == 1, "走 1 手（魏）", f"实际 {len(mv)}")
chk(m.state["turn"] == 2, "轮到吴", f"实际 {m.state['turn']}")
r = m.undo_last()
chk(r.get("ok") is True, "悔棋成功", f"实际 {r}")
chk(r.get("rolled_back") == 1, "★ 只退回 1 手", f"实际 {r.get('rolled_back')}")
chk(r.get("army") == 1, "目标是魏方", f"实际 {r.get('army')}")
chk(m.state["ply"] == 0, "ply 回到 0", f"实际 {m.state['ply']}")
chk(m.state["turn"] == 1, "仍是魏方走（自己重走）", f"实际 {m.state['turn']}")
chk(r["left"] == {1: 2, 2: 3, 3: 3}, "只扣魏 1 次：魏 3→2，吴蜀不动",
    f"实际 {r['left']}")

# ============================================================================
sect(2, "② ★核心：轮到魏、吴蜀已各走一步 → 一次悔棋退 3 手，只扣魏 1 次")

m = fresh(human=(1,))
mv = walk(m, 3)
chk(len(mv) == 3, "走 3 手（魏→吴→蜀）", f"实际 {len(mv)}")
chk(m.state["turn"] == 1, "★ 恰好轮到魏（最后落子的是蜀）", f"实际 {m.state['turn']}")
chk(m.state["ply"] == 3, "ply = 3", f"实际 {m.state['ply']}")

r = m.undo_last()
chk(r.get("ok") is True, "悔棋成功", f"实际 {r}")
chk(r.get("rolled_back") == 3, "★ 一次退回 3 手（本方 1 + 对手各 1）",
    f"实际 {r.get('rolled_back')}")
chk(r.get("army") == 1, "目标是魏方（不是最后落子的蜀方）", f"实际 {r.get('army')}")
chk(r.get("others") == ["蜀", "吴"],
    "★ 连带的对手 = 蜀、吴", f"实际 {r.get('others')}")
chk(m.state["ply"] == 0, "回到 ply=0（魏尚未落子）", f"实际 {m.state['ply']}")
chk(m.state["turn"] == 1, "★ 回到魏方走（这才叫「我的悔棋」）",
    f"实际 {m.state['turn']}")
chk(r["left"] == {1: 2, 2: 3, 3: 3},
    "★★ 核心断言：只扣魏 1 次，吴蜀**一次都不扣**", f"实际 {r['left']}")
chk(m.undo_used == {1: 1, 2: 0, 3: 0}, "undo_used 同样只记魏 1 次",
    f"实际 {m.undo_used}")

# ============================================================================
sect(3, "③ 撤 3 手后盘面 = 开局（棋子一件不多一件不少）")

chk(len(m.state["board"]) == 48, "撤完仍是 48 枚棋子（三方各 16）",
    f"实际 {len(m.state['board'])}")
ref = GA.new_game(first=1)
chk(set(m.state["board"]) == set(ref["board"]), "棋盘点位集合 = 开局",
    f"实际 {len(m.state['board'])} 点")
mismatch = [p for p in ref["board"]
            if p not in m.state["board"]
            or (m.state["board"][p]["kind"], m.state["board"][p]["army"])
            != (ref["board"][p]["kind"], ref["board"][p]["army"])]
chk(mismatch == [], "逐点比对：与开局完全一致（kind + army）",
    f"差异点 {mismatch[:5]}")
chk(m.state["ply"] == 0 and m.state["turn"] == 1, "ply=0 且轮到魏",
    f"ply={m.state['ply']} turn={m.state['turn']}")

# ============================================================================
sect(4, "④ 撤 2 手：魏、吴走后轮到蜀时点悔棋 → 退 2 手，只扣魏")

m = fresh(human=(1,))
mv = walk(m, 2)
chk(m.state["turn"] == 3, "走 2 手后轮到蜀", f"实际 {m.state['turn']}")
r = m.undo_last()
chk(r.get("rolled_back") == 2, "★ 退回 2 手（魏 1 + 吴 1）",
    f"实际 {r.get('rolled_back')}")
chk(r.get("army") == 1, "目标仍是魏（人类席位里最近落子的一方）",
    f"实际 {r.get('army')}")
chk(r["left"] == {1: 2, 2: 3, 3: 3}, "只扣魏；吴（被连带退回）不扣",
    f"实际 {r['left']}")
chk(m.state["ply"] == 0 and m.state["turn"] == 1, "回到开局、轮魏",
    f"ply={m.state['ply']} turn={m.state['turn']}")

# ============================================================================
sect(5, "⑤ 三方都是人类时：显式指定 army 可撤到任意方之前")

m = fresh(human=(1, 2, 3))
mv = walk(m, 4)                     # 魏 吴 蜀 魏
chk(m.state["ply"] == 4, "走 4 手", f"实际 {m.state['ply']}")
r = m.undo_last(army=2)             # 回到吴上次落子（第 2 手）之前
chk(r.get("ok") is True, "指定 army=2 悔棋成功", f"实际 {r}")
chk(r.get("rolled_back") == 3, "★ 退回 3 手（第 4 魏 + 第 3 蜀 + 第 2 吴）",
    f"实际 {r.get('rolled_back')}")
chk(m.state["ply"] == 1, "回到 ply=1（只剩第 1 手魏）", f"实际 {m.state['ply']}")
chk(m.state["turn"] == 2, "轮到吴重走", f"实际 {m.state['turn']}")
chk(r["left"] == {1: 3, 2: 2, 3: 3}, "★ 只扣吴 1 次；魏、蜀不扣（魏那手也退了）",
    f"实际 {r['left']}")

# ============================================================================
sect(6, "⑥ 显式指定「还没落过子的一方」→ 明确拒绝，且**不消耗任何存档**")

m = fresh(human=(1,))
walk(m, 1)                          # 只走了魏的一手；吴一步没走过
n_snap = len(m.snapshots)
r = m.undo_last(army=2)             # 吴一步没走过
chk(r.get("ok") is False, "被拒", f"实际 {r}")
chk("还没有可悔的棋" in (r.get("error") or ""), "错误信息说明原因",
    f"实际 {r.get('error')}")
chk(len(m.snapshots) == n_snap, "★ 存档数未变（没有把栈 pop 坏）",
    f"{n_snap} → {len(m.snapshots)}")

# ============================================================================
sect(7, "⑦ 机会用尽 → 拒绝；且不影响别方")

m = fresh(human=(1,), undo_per=1)
walk(m, 3)
r1 = m.undo_last()
chk(r1["left"][1] == 0, "悔 1 次后魏方机会归零", f"实际 {r1['left']}")
walk(m, 3)
r2 = m.undo_last()
chk(r2.get("ok") is False, "★ 再用被拒", f"实际 {r2}")
chk("已用完" in (r2.get("error") or ""), "错误信息：机会已用完",
    f"实际 {r2.get('error')}")
chk(m.undo_left == {1: 0, 2: 1, 3: 1}, "别方次数丝毫未动", f"实际 {m.undo_left}")

# ============================================================================
sect(8, "⑧ 观战档（human_armies 为空）→ 退回最后一步，扣最后落子方（旧行为兜底）")

m = fresh(human=())
walk(m, 3)
r = m.undo_last()
chk(r.get("rolled_back") == 1, "撤 1 手", f"实际 {r.get('rolled_back')}")
chk(r.get("army") == 3, "目标是最后落子的蜀方", f"实际 {r.get('army')}")
chk(r["left"] == {1: 3, 2: 3, 3: 2}, "扣蜀 1 次", f"实际 {r['left']}")

# ============================================================================
sect(9, "⑨ ★ 等价性：1 次「连带悔棋」== 3 次「单步悔棋」，但只花 1 次机会")

# 甲：一次连带悔棋（走 3 手后悔一次）
ma = fresh(human=(1,))
walk(ma, 3)
ra = ma.undo_last()

# 乙：连续 3 次显式单步悔棋（蜀 → 吴 → 魏）
mb = fresh(human=(1, 2, 3))
walk(mb, 3)
for who in (3, 2, 1):
    rb = mb.undo_last(army=who)
    chk(rb.get("ok") is True, f"单步悔 {GA.ARMY_CN[who]}方成功", f"实际 {rb}")

chk(board_of(ma) == board_of(mb), "★ 两条路径的**盘面完全相同**")
chk(ma.state["ply"] == mb.state["ply"] == 0, "ply 都回到 0",
    f"{ma.state['ply']} / {mb.state['ply']}")
chk(ma.state["turn"] == mb.state["turn"] == 1, "都轮到魏",
    f"{ma.state['turn']} / {mb.state['turn']}")
chk(ra["left"][2] == 3 and ra["left"][3] == 3 and mb.undo_left[2] == 2
    and mb.undo_left[3] == 2,
    "★★ 但代价不同：连带悔棋后吴蜀仍是 3 次（没被扣）；"
    "三次单步则把吴、蜀各扣掉 1 次 —— 这正是老师要消除的不合理",
    f"连带 {ra['left']} vs 分步 {mb.undo_left}")
chk(mb.undo_left[3] == 2 and mb.undo_left[2] == 2,
    "分步路径确实扣掉了吴、蜀各 1 次 → 这正是老师要消除的不合理",
    f"实际 {mb.undo_left}")

# ============================================================================
sect(10, "⑩ 回看缓冲同步截断 + 痕迹不留幽灵")

m = fresh(human=(1,))
len0 = len(m.replay)
walk(m, 3)
chk(len(m.replay) == len0 + 3, "走 3 手 → 回看缓冲 +3", f"实际 {len(m.replay)}")
r = m.undo_last()
chk(len(m.replay) == len0, "★ 退 3 手 → 缓冲同步截断回原长度",
    f"{len0 + 3} → {len(m.replay)}")
chk(m._recent_move_notes(2) == [], "痕迹清空（被撤的手不留幽灵路径）",
    f"实际 {m._recent_move_notes(2)}")
bk = m.replay_at(0)
chk(bk.get("ply") == 0, "回看第 0 项仍是开局", f"实际 {bk.get('ply')}")

# ============================================================================
sect(11, "⑪ 日志文案写明「不消耗机会」")

m = fresh(human=(1,))
walk(m, 3)
m.undo_last()
undo_logs = [e for e in m.log if e.get("type") == "undo"]
chk(len(undo_logs) == 1, "产生 1 条 undo 日志", f"实际 {len(undo_logs)}")
txt = undo_logs[-1].get("text", "") if undo_logs else ""
chk("魏方" in txt, "写明悔棋方", f"实际 {txt!r}")
chk("3 手" in txt, "写明清了几手", f"实际 {txt!r}")
chk("不消耗机会" in txt, "★ 写明其他方不消耗机会", f"实际 {txt!r}")
chk(undo_logs and undo_logs[-1].get("army") == 1, "日志 army 记为魏",
    f"实际 {undo_logs[-1].get('army') if undo_logs else None}")

# ============================================================================
sect(12, "⑫ /api/state 的预告字段：undo_who / undo_rollback")

m = fresh(human=(1,))
walk(m, 3)
snap = m.snapshot()
chk(snap.get("undo_who") == 1, "undo_who = 1（点按钮会撤魏）",
    f"实际 {snap.get('undo_who')}")
chk(snap.get("undo_rollback") == 3, "undo_rollback = 3（会退 3 手）",
    f"实际 {snap.get('undo_rollback')}")
m.undo_last()
snap2 = m.snapshot()
chk(snap2.get("undo_who") is None or snap2.get("undo_rollback") == 0,
    "无棋可悔时预告清零", f"who={snap2.get('undo_who')} n={snap2.get('undo_rollback')}")

# ============================================================================
sect(13, "⑬ 未开启悔棋 / 对局已结束 → 拒绝")

m = fresh(human=(1,), allow_undo=False)
walk(m, 3)
r = m.undo_last()
chk(r.get("ok") is False and "未开启" in (r.get("error") or ""),
    "未开启时拒绝", f"实际 {r}")

m = fresh(human=(1,))
walk(m, 3)
m.drawn = True
r = m.undo_last()
chk(r.get("ok") is False and "已结束" in (r.get("error") or ""),
    "对局结束时拒绝", f"实际 {r}")

# ============================================================================
print("\n" + "=" * 74)
print(f"结果：OK = {ok}   FAIL = {bad}")
print("=" * 74)
sys.exit(1 if bad else 0)
