# -*- coding: utf-8 -*-
"""`/api/move` 后端守卫专项验证（不接触正在运行的服务，独立 Match 实例）

背景（老师 2026-09-24 夜报「魏国的士凭空消失」）：
  查证结果是**士被合法吃掉**（完整棋谱见 tests/_replay_probe.py），但那手
  `ply10 士 E6→D5` 在日志里标着「人类接管」—— 而『人类接管』这个 reason
  全项目只有 `manual_move()` 会写。前端 `onPick()` **有**守卫
  （`未勾选人类接管 ＆ 自动对弈中 ⇒ 拒绝`），后端 `manual_move()` 却**完全没有**：
  只要有请求打到 /api/move，就能替**任意**当前回合方走一步。

本测试锁死修好后的语义，四种情形逐一断言：
  ① 自动对弈 + 未勾选该方          → 拒绝，且棋盘**不变**
  ② 自动对弈 + 已勾选该方          → 放行
  ③ 暂停     + 未勾选              → 放行（老师「暂停后可临时介入」的口径）
  ④ 自动对弈 + 勾了魏、但轮到吴     → 拒绝（守卫看的是**当前回合方**）
  ⑤ `judge-<方>` 伪着法同样受守卫
运行：python tests/_verify_move_guard.py
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


def fresh(auto=True, humans=()):
    """独立 Match 实例 + 手工设定守卫读的两个字段。

    ⚠️ **必须用 `Match(auto=False)` 构造**：`Match.__init__`（match.py:170）
       **无条件**启动 `_loop` 线程，若构造时 auto=True，线程会在测试断言之前
       就替 Bot 走掉一两手（实测 turn 已变吴方、ply=1），把局面污染掉。
       守卫只读属性值，所以「构造时关、构造后手工开」与真实运行完全等价。

    线程是 daemon（不阻止进程退出），且置 alive=False 让它自然结束。
    """
    m = Match(auto=False)
    m.alive = False            # 让后台 _loop 立刻退出，避免残留
    m.auto = auto              # 再手工打开守主要看的标志
    m.human_armies = set(humans)
    return m


print("=" * 74)
print("`/api/move` 后端守卫 —— 老师「魏国的士凭空消失」排查的连带加固")
print("=" * 74)

# 开局魏方 132(C8) 是炮，137(C3) 是空点（ply1 老师走的就是这一手）
# 开局吴方 238(M8) 是炮，312(J8) 是蜀马（ply2 吴方走的就是这一手）

# ============================================================================
sect(1, "① 自动对弈 + 未勾选「人类接管魏」→ 必须拒绝，且棋盘一动不动")

m = fresh(auto=True, humans=())
before = dict(m.state["board"])
r = m.manual_move("132", "137")
chk(r.get("ok") is False, "返回 ok=False", f"实际 {r}")
chk("人类接管" in (r.get("error") or ""),
  "错误文案提示要勾选「人类接管」（可读的拒绝理由）", f"实际 {r.get('error')}")
chk(m.state["board"] == before,
  "棋盘**完全没变**（132 仍有子、137 仍为空）",
  f"132={m.state['board'].get('132') is not None} 137={m.state['board'].get('137')}")
chk(m.state["ply"] == 0, "未推进 ply", f"实际 {m.state['ply']}")

# ============================================================================
sect(2, "② 自动对弈 + 已勾选「人类接管魏」→ 放行（老师正常下棋的路径）")

m = fresh(auto=True, humans=(1,))
r = m.manual_move("132", "137")
chk(r.get("ok") is True, "返回 ok=True", f"实际 {r}")
chk(m.state["board"].get("132") is None and m.state["board"].get("137") is not None,
  "132 的炮确实走到了 137")
chk(m.state["ply"] == 1, "ply 推进到 1", f"实际 {m.state['ply']}")

# ============================================================================
sect(3, "③ 暂停 + 未勾选 → 放行（老师口径：「暂停后可临时介入」）")

m = fresh(auto=False, humans=())
r = m.manual_move("132", "137")
chk(r.get("ok") is True, "暂停状态下允许人类临时走子", f"实际 {r}")
chk(m.state["board"].get("137") is not None, "棋子确实动了")

# ============================================================================
sect(4, "④ 守卫看的是**当前回合方**：勾了魏、轮到吴时，仍不能替吴落子")

m = fresh(auto=True, humans=(1,))
m.state["turn"] = 2                       # 强制轮到吴方
before = dict(m.state["board"])
r = m.manual_move("238", "312")           # 吴炮 M8→J8 吃蜀马（ply2 的真实着法）
chk(r.get("ok") is False,
  "勾了魏但轮到吴 → 替**吴**落子被拒（不是「勾了就行」）", f"实际 {r}")
chk("吴方回合" in (r.get("error") or ""),
  "错误文案点明是**吴方**回合", f"实际 {r.get('error')}")
chk(m.state["board"] == before, "棋盘未变")

# ============================================================================
sect(5, "⑤ `judge-<方>` 伪着法（《一、10》判负）同样受守卫")

m = fresh(auto=True, humans=())
r = m.manual_move("judge", "3")
chk(r.get("ok") is False,
  "自动对弈 + 未勾选时，「judge-3」也不能绕过守卫", f"实际 {r}")

# ============================================================================
sect(6, "⑥ 与前端守卫口径逐字一致（防两边再次漂移）")

src = open(os.path.join(ROOT, "server", "match.py"), encoding="utf-8").read()
js = open(os.path.join(ROOT, "web", "app.js"), encoding="utf-8").read()
chk("self.auto and army not in self.human_armies" in src,
  "后端条件 = `auto and 当前回合方 ∉ human_armies`")
chk("if (!hm.includes(cur) && st.auto)" in js,
  "前端条件 = `!human_armies.includes(cur) && auto`（同一逻辑）")

# ============================================================================
print("\n" + "=" * 74)
print(f"合计 {ok} 通过 / {bad} 失败")
print("=" * 74)
sys.exit(1 if bad else 0)
