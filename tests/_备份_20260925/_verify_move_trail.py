# -*- coding: utf-8 -*-
"""「上两手走子痕迹」后端专项验证 —— 独立 Match 实例，不碰运行中的服务

老师 2026-09-25 原话：
  「目前你会用红色虚线显示前一次走棋，但不够，我需要前两次，分别用红色和
    橙色虚线表示前一次和前两次」

设计意图：**吃子往往只是结果，根因常在上上一步**（对方刚把子送到这里 /
自己刚让开炮架）⇒ 后端必须把「最近两手」一起交给前端。

本脚本验证（全部在 log / replay 上做，不起服务、不动对局）：
  ① 开局：recent 为空、last 为 None
  ② 1 手 → recent=[第1手]；2 手 → recent=[第2手, 第1手]（**最新在前**）
  ③ 手数再多也只给 2 条（前端只需要 2 个位置，不会无限涨）
  ④ ★ 悔棋：undo_last() 真删 log ⇒ recent 立刻回退，**不留幽灵痕迹**
  ⑤ pass（无棋可走，不产生路径）被跳过，不占「前两次」的名额
  ⑥ 回看：replay[i] 的 recent = **那个历史时刻**的最近两手（不含未来手）
  ⑦ 回看是只读的：调 replay_at 前后 state 一字未动
  ⑧ 兼容旧存档：recent 字段缺失时回退成 [last]

运行：python tests/_verify_move_trail.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "server"))

from engine import game_dxf as GA          # noqa: E402
from match import Match                    # noqa: E402

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


def fresh(all_human=True):
    """构造独立 Match（auto=False 避免 _loop 线程在断言前抢着走棋）。"""
    m = Match(auto=False)
    m.alive = False                        # 让 daemon 线程立刻退出
    if all_human:
        m.human_armies = {1, 2, 3}         # 三方都当人类 → 可以按回合手工落子
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


print("=" * 74)
print("上两手走子痕迹 —— 红（最近）/ 橙（再往前）")
print("=" * 74)

# ============================================================================
sect(1, "① 开局：两手痕迹为空（不该凭空出现标记）")

m = fresh()
chk(m._recent_move_notes(2) == [], "开局 _recent_move_notes(2) = []",
    f"实际 {m._recent_move_notes(2)}")
chk(m._last_move_note() is None, "开局 _last_move_note() = None")
r0 = m.replay_at(0)
chk(r0.get("recent") == [], "开局 replay[0].recent = []（前端拿到空数组 → 清空痕迹）",
    f"实际 {r0.get('recent')}")
chk(r0.get("last") is None, "开局 replay[0].last 仍为 None（向后兼容）")

# ============================================================================
sect(2, "② 1 手 → 1 条；2 手 → 2 条且**最新在前**")

m = fresh()
mv = walk(m, 2)
chk(len(mv) == 2, "成功走了 2 手合法棋", f"实际 {mv}")

r = m._recent_move_notes(2)
chk(len(r) == 2, "recent 长度 = 2", f"实际 {len(r)}")
chk((r[0]["from"], r[0]["to"]) == mv[1],
    "recent[0] = **最近一手**（老师指定用红色画）", f"实际 {r[0]['from']}→{r[0]['to']}，预期 {mv[1]}")
chk((r[1]["from"], r[1]["to"]) == mv[0],
    "recent[1] = **再往前一手**（老师指定用橙色画）", f"实际 {r[1]['from']}→{r[1]['to']}，预期 {mv[0]}")
chk(r[0].get("ply", 0) > r[1].get("ply", 0), "recent[0].ply > recent[1].ply（顺序确实是新→旧）",
    f"实际 {r[0].get('ply')} / {r[1].get('ply')}")

# 字段齐全（前端 board.js 要用 army + captured）
keys = set(r[0].keys())
chk({"from", "to", "army", "captured", "ply"} <= keys,
    f"字段齐全（前端要 army 判色、captured 显示「吃士」）", f"实际 {sorted(keys)}")

# 与 log 里那条 move 完全一致（不另造数据）
log_moves = [e for e in m.log if e.get("type") == "move"]
chk(len(log_moves) == 2, "log 里有 2 条 move 记录", f"实际 {len(log_moves)}")
last_ev = log_moves[-1]
chk(r[0]["from"] == last_ev.get("from") and r[0]["to"] == last_ev.get("to")
    and r[0]["army"] == last_ev.get("army")
    and r[0]["captured"] == last_ev.get("captured"),
    "recent 逐字段复制自 log（单一事实来源，不二次计算）")

# ============================================================================
sect(3, "③ 手数再多也只给 2 条（前端只要两个位置，缓冲不随对局膨胀）")

m = fresh()
mv = walk(m, 7)
chk(len(mv) == 7, "连走 7 手", f"实际 {len(mv)} 手")
r = m._recent_move_notes(2)
chk(len(r) == 2, "依然只返回 2 条", f"实际 {len(r)}")
chk((r[0]["from"], r[0]["to"]) == mv[-1], "recent[0] = 第 7 手")
chk((r[1]["from"], r[1]["to"]) == mv[-2], "recent[1] = 第 6 手")
chk(len(m._recent_move_notes(1)) == 1, "_recent_move_notes(1) 只给 1 条（= 旧 _last_move_note）")
chk(m._last_move_note()["from"] == mv[-1][0], "_last_move_note() 与 recent[0] 一致")

# ============================================================================
sect(4, "④ ★ 悔棋：被撤回的那手**立刻**从两手痕迹里消失（不留幽灵）")

m = fresh()
m.allow_undo = True
mv = walk(m, 3)
chk(len(mv) == 3, "先走 3 手", f"实际 {len(mv)}")
before = m._recent_move_notes(2)
chk((before[0]["from"], before[0]["to"]) == mv[2], "悔棋前 recent[0] = 第 3 手")
chk((before[1]["from"], before[1]["to"]) == mv[1], "悔棋前 recent[1] = 第 2 手")

res = m.undo_last()
chk(res.get("ok") is True, "悔棋成功", f"实际 {res}")
after = m._recent_move_notes(2)
chk((after[0]["from"], after[0]["to"]) == mv[1],
    "★ 悔棋后 recent[0] 变成**原第 2 手**（被撤的第 3 手已从 log 真删除）",
    f"实际 {after[0]['from']}→{after[0]['to']}，预期 {mv[1]}")
chk((after[1]["from"], after[1]["to"]) == mv[0], "悔棋后 recent[1] = 原第 1 手")
chk(all((e["from"], e["to"]) != mv[2] for e in after),
    "★ 被撤的那手不会以任何形式残留（红/橙都不会画出幽灵路径）")

# 悔到只剩一手 → 只剩 1 条
m.undo_last()
m.undo_last()
chk(m._recent_move_notes(2) == [], "全部悔完 → recent = []（痕迹清空）",
    f"实际 {m._recent_move_notes(2)}")

# ============================================================================
sect(5, "⑤ pass（无棋可走，不产生路径）不占「前两次」的名额")

m = fresh()
mv = walk(m, 2)
m.log.append({"type": "pass", "army": 3, "ply": m.state.get("ply"),
              "text": "蜀方无棋可走，跳过"})
r = m._recent_move_notes(2)
chk(len(r) == 2, "log 尾部有 pass 时，仍返回 2 条**走子**", f"实际 {len(r)}")
chk((r[0]["from"], r[0]["to"]) == mv[1], "recent[0] 仍是最后一手走子（pass 被跳过）")
chk((r[1]["from"], r[1]["to"]) == mv[0], "recent[1] 仍是上一手走子")
chk(all(e.get("type") != "pass" for e in r), "recent 里不含 pass（前端只画路径）")

# ============================================================================
sect(6, "⑥ 回看：replay[i].recent = **那个历史时刻**的最近两手（不含未来手）")

m = fresh()
mv = walk(m, 4)
chk(len(mv) == 4, "走 4 手供回看", f"实际 {len(mv)}")
n = len(m.replay)
chk(n == 5, "replay 共 5 项（开局 + 4 手）", f"实际 {n}")

rk = m.replay_at(0)
chk(rk.get("recent") == [], "回看到**开局** → recent 为空（不该显示任何痕迹）")

rk = m.replay_at(1)
chk(len(rk.get("recent") or []) == 1 and (rk["recent"][0]["from"], rk["recent"][0]["to"]) == mv[0],
    "回看到**第 1 手** → recent 只有第 1 手（不含第 2 手）",
    f"实际 {[(x['from'], x['to']) for x in (rk.get('recent') or [])]}")

rk = m.replay_at(4)
rc = rk.get("recent") or []
chk(len(rc) == 2 and (rc[0]["from"], rc[0]["to"]) == mv[3] and (rc[1]["from"], rc[1]["to"]) == mv[2],
    "回看到**第 4 手** → recent = [第4手, 第3手]（最新在前）",
    f"实际 {[(x['from'], x['to']) for x in rc]}")

# 回看中途的每一项，都不能出现"当时还没发生"的手
bad_future = []
for i in range(n):
    rk = m.replay_at(i)
    for x in (rk.get("recent") or []):
        idx = next((k for k, t in enumerate(mv) if t == (x["from"], x["to"])), None)
        # mv 是顺序走的；第 i 项对应"走完第 i 手" ⇒ 只允许出现前 i 手
        if idx is not None and idx >= i:
            bad_future.append((i, x["from"], x["to"]))
chk(not bad_future, "所有回看项都不含**未来手**（痕迹与画面上的历史局面严格对齐）",
    f"越界项 {bad_future}" if bad_future else "")

# ============================================================================
sect(7, "⑦ 只读红线：调完 replay_at，对局状态一字未动")

m = fresh()
walk(m, 3)
b_ply, b_turn = m.state["ply"], m.state["turn"]
b_board = {p: (v["kind"], v["army"], v["home"]) for p, v in m.state["board"].items()}
b_len, b_log = len(m.replay), len(m.log)
for i in (0, 1, 2, 99, -5, "abc"):
    m.replay_at(i)
chk(m.state["ply"] == b_ply and m.state["turn"] == b_turn, "ply / turn 未变")
chk({p: (v["kind"], v["army"], v["home"]) for p, v in m.state["board"].items()} == b_board,
    "棋盘逐点完全一致")
chk(len(m.replay) == b_len and len(m.log) == b_log, "replay / log 长度未变")

# ============================================================================
sect(8, "⑧ 兼容旧存档：recent 字段缺失 → 回退成 [last]（旧服务不重启也不白屏）")

m = fresh()
mv = walk(m, 2)
m.replay[-1].pop("recent", None)           # 模拟"这条存档是旧版本写的"
rk = m.replay_at(len(m.replay) - 1)
chk(rk.get("recent") == [rk.get("last")],
    "缺 recent 时回退成 [last]（前端仍能画出红色最近一手，只是缺橙色那条）",
    f"实际 {rk.get('recent')}")
chk(rk.get("last") and rk["last"]["from"] == mv[1][0], "回退值就是该时刻的 last")

# ============================================================================
print("\n" + "=" * 74)
print(f"合计 {ok} 通过 / {bad} 失败")
print("=" * 74)
sys.exit(1 if bad else 0)
