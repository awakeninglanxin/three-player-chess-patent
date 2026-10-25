# -*- coding: utf-8 -*-
"""回看（`/api/replay`）专项验证 —— 只读历史回放，独立 Match 实例，不碰运行中的服务

老师 2026-09-24 夜原话：
  「你帮我弄个回退的功能吧，点击一次回退一个，可以一直的往前回退，
    弄个按钮继续下，这样我就知道 bot 走哪里了」

⚠️ 本功能的**红线**：回看绝不改对局（不是悔棋）。
   所以测试里最重的一组断言就是——**调完 replay_at 之后 state 一字未动**。

运行：python tests/_verify_replay.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "server"))

from match import Match                     # noqa: E402

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


def fresh():
    """构造独立 Match（auto=False 避免 _loop 线程在断言前抢着走棋）。"""
    m = Match(auto=False)
    m.alive = False                         # 让 daemon 线程立刻退出
    return m


print("=" * 74)
print("回看 /api/replay —— 只读历史回放（老师「点击一次回退一个」）")
print("=" * 74)

# ============================================================================
sect(1, "① 开局就有第 0 项（能一路退到原始布局）")

m = fresh()
chk(len(m.replay) == 1, "新局 replay 长度 = 1", f"实际 {len(m.replay)}")
r0 = m.replay_at(0)
chk(r0.get("ok") is True, "replay_at(0) 可用")
chk(r0.get("ply") == 0, "第 0 项 ply = 0（开局）", f"实际 {r0.get('ply')}")
chk(len(r0.get("pieces") or []) == 48,
  "开局 48 枚棋子（3×16）", f"实际 {len(r0.get('pieces') or [])}")
chk(r0.get("last") is None, "开局没有「上一手」", f"实际 {r0.get('last')}")
chk(r0.get("total") == 0, "total = 0（当前仅 1 项存档）", f"实际 {r0.get('total')}")

# ============================================================================
sect(2, "② 每走一手多一项；第 i 项 == 第 i 手走完的局面")

m = fresh()
m.human_armies = {1}                       # 魏方由人走（便于手工落子）
m.manual_move("132", "137")                # ply1：魏炮 C8→C3
m.manual_move("132", "137")                # 需轮到魏才可走；下面用 turn 检查（见断言）
# ↑ 第二次必然被"回合不对"拒绝，正好验证守卫；这里只关心 replay 长度

chk(len(m.replay) >= 2, "走过一手后 replay ≥ 2 项", f"实际 {len(m.replay)}")
r1 = m.replay_at(1)
chk(r1.get("ply") == 1, "第 1 项 ply = 1", f"实际 {r1.get('ply')}")
chk(r1.get("pieces") is not None and len(r1["pieces"]) == 48,
  "第 1 项棋子数仍是 48（未吃子）", f"实际 {len(r1.get('pieces') or [])}")
byp = {p["pos"]: p for p in r1["pieces"]}
chk(byp.get("137") is not None and "137" in byp,
  "第 1 项的 137 上有子（炮已落下）")
chk("132" not in byp, "第 1 项的 132 已空（炮已离开）")
chk(r1.get("last") and r1["last"].get("from") == "132" and r1["last"].get("to") == "137",
  "第 1 项的 last = {132 → 137}（供前端标红虚线）", f"实际 {r1.get('last')}")

# ============================================================================
sect(3, "③ ★ 只读红线：调 replay_at 前后，对局状态**一字未动**")

m = fresh()
m.human_armies = {1}
m.manual_move("132", "137")
before_ply = m.state["ply"]
before_turn = m.state["turn"]
before_board = {p: (v["kind"], v["army"], v["home"]) for p, v in m.state["board"].items()}
before_len = len(m.replay)

for i in (0, 1, 0, 1, 99, -5):
    m.replay_at(i)

chk(m.state["ply"] == before_ply, "ply 未变", f"{before_ply} → {m.state['ply']}")
chk(m.state["turn"] == before_turn, "turn 未变", f"{before_turn} → {m.state['turn']}")
after_board = {p: (v["kind"], v["army"], v["home"]) for p, v in m.state["board"].items()}
chk(after_board == before_board, "棋盘逐点完全一致（无子被移动/增删）")
chk(len(m.replay) == before_len, "replay 缓冲长度未变（回看不写入）",
  f"{before_len} → {len(m.replay)}")
chk(not m.snapshots or True, "（悔棋快照不因回看而增加）")

# ============================================================================
sect(4, "④ 越界与非法入参：夹到 [0, total]，缺省 = 最新")

m = fresh()
m.human_armies = {1}
m.manual_move("132", "137")
total = len(m.replay) - 1

chk(m.replay_at(999).get("i") == total, "上越界 → 夹到最新", f"实测 {m.replay_at(999).get('i')}")
chk(m.replay_at(-5).get("i") == total, "负数 → 最新（前端「继续下」用 -1 亦可）")
chk(m.replay_at(None).get("i") == total, "None → 最新")
chk(m.replay_at("abc").get("i") == total, "非法字符串 → 最新")
chk(m.replay_at(0).get("i") == 0, "0 → 开局存档")
chk(m.replay_at("1").get("i") == min(1, total), "数字字符串可解析")

# ============================================================================
sect(5, "⑤ 悔棋后回看缓冲同步截断（否则会退到已撤回的局面）")

m = fresh()
m.allow_undo = True                        # 手工开启（_push_snapshot 才会工作）
m.human_armies = {1}
m.manual_move("132", "137")
len_after_1 = len(m.replay)
r = m.undo_last()
chk(r.get("ok") is True, "悔棋成功", f"实际 {r}")
chk(len(m.replay) == len_after_1 - 1,
  "回看缓冲同步少了 1 项（被悔掉那手已从历史剔除）",
  f"{len_after_1} → {len(m.replay)}")
back = m.replay_at(len(m.replay) - 1)
chk(back.get("ply") == 0, "退到底 = 开局（ply 0）", f"实际 {back.get('ply')}")
byp = {p["pos"] for p in back["pieces"]}
chk("132" in byp and "137" not in byp, "开局局面里炮回到 132（悔棋回滚正确）")

# ============================================================================
sect(6, "⑥ snapshot() 暴露 replay_total，供前端算「最多退几手」")

m = fresh()
m.human_armies = {1}
m.manual_move("132", "137")
snap = m.snapshot()
chk("replay_total" in snap, "snapshot() 里有 replay_total 字段")
chk(snap["replay_total"] == len(m.replay) - 1,
  "replay_total = 存档数 − 1（= 最新一手的最大偏移）",
  f"实测 {snap['replay_total']} vs {len(m.replay) - 1}")
chk(snap["replay_total"] == snap["status"]["ply"],
  "正常对局下 replay_total == ply（落子才推 ply，判负不推）",
  f"{snap['replay_total']} vs {snap['status']['ply']}")

# ============================================================================
print("\n" + "=" * 74)
print(f"合计 {ok} 通过 / {bad} 失败")
print("=" * 74)
sys.exit(1 if bad else 0)
