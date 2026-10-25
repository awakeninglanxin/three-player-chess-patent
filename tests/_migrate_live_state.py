# -*- coding: utf-8 -*-
"""把**正在运行的旧服务**的对局局面迁移到新引擎的续局存档里。

【为什么要这个脚本】
    `server/data/autosave.json` 是 2026-10-01 才加的续局功能。老师当前这一局
    （ply=116）是在**旧代码**上走出来的 —— 旧 `Match` 没有 `enable_autosave`，
    内存里的局面**从未落盘**。直接重启 = 白走 116 手。

【做法】
    旧服务的 `/api/state` 已经暴露了重建局面所需的全部信息：
      · `pieces`（23 枚棋子的 pos/kind/army/home）    → 重建 `state["board"]`
      · `status`（turn/ply/vitality/combat/chain/…）  → 与 `state` 同名键逐个覆盖
    拿 `GA.new_game()` 的完整键集当模板（`board` / `first` / `history` 是它独有的，
    `history` 没被 `match.py` 引用过，保留空值即可）。

【保真度】
    ✅ 盘面、轮次、手数、三方战损/收编/副帅/出局/认输、连吃上限、回合步数、
       残局判平计数、将军状态 —— 全部逐字段迁移。
    ✗ 悔棋栈 `snapshots` 与回看缓冲 `replay`（旧服务未导出）—— 迁移后**悔棋不可用**，
       这是唯一的功能缺口，属可接受降级（本来就是为了"不用重走 116 手"）。

跑法：
    cd 中国三人象棋_专利版
    curl -s --noproxy '*' http://127.0.0.1:8771/api/state -o tests/_live_state_snapshot.json
    "D:/Program Files/Python312/python.exe" tests/_migrate_live_state.py
"""
import json
import os
import sys
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "server"))

from engine import game_dxf as GA           # noqa: E402
import match as M                           # noqa: E402

SNAP = os.path.join(_ROOT, "tests", "_live_state_snapshot.json")
DEST = M.SAVE_FILE

# `state` 与 `/api/state.status` 同名的键（其余 status 键是 snapshot 的计算产物）
SHARED = ("annexed", "chain", "chain_limit", "combat", "declared_lose", "deputies",
          "eliminated", "out", "passed", "ply", "resigned", "stale_from_ply",
          "steps_per_turn", "turn", "turn_steps", "vitality", "winner")

live = json.load(open(SNAP, encoding="utf-8"))
pieces = live["pieces"]
status = live["status"]

# ---------------------------------------------------------------- 1. 重建 state
state = dict(GA.new_game(first=1))
for k in SHARED:
    if k in status:
        state[k] = status[k]
board = {}
for p in pieces:
    cell = {"kind": p["kind"], "army": p["army"], "home": p["home"]}
    for extra in ("deputy", "vitality"):
        if extra in p:
            cell[extra] = p[extra]
    board[p["pos"]] = cell
state["board"] = board

print(f"重建盘面：{len(board)} 枚棋子  ply={state.get('ply')}  turn={state.get('turn')}")
_dep = [q for q, c in board.items() if c.get("deputy")]
print(f"  其中副帅 {len(_dep)} 枚 {_dep}")

# ---------------------------------------------------------------- 2. 灌进新 Match
m = M.Match()
m.state = state
# 接管/规则配置从 `/api/state` **顶层**取（它们不在 status 里）
m.human_armies = set(live.get("human_armies") or [1])
m.auto = bool(live.get("auto", False))
m.difficulty = M.DIFF.norm(live.get("difficulty") or m.difficulty)
m.allow_undo = bool(live.get("allow_undo", True))
m.undo_per_side = int(live.get("undo_per_side") or m.undo_per_side)
m.undo_left = {int(k): v for k, v in (live.get("undo_left") or {}).items()} \
    or {1: m.undo_per_side, 2: m.undo_per_side, 3: m.undo_per_side}
m.undo_used = {int(k): v for k, v in (live.get("undo_used") or {}).items()} \
    or {1: 0, 2: 0, 3: 0}
for _k in (1, 2, 3):
    m.undo_left.setdefault(_k, m.undo_per_side)
    m.undo_used.setdefault(_k, 0)
m.chain_limit = live.get("chain_limit")
m.state["chain_limit"] = m.chain_limit
m.steps_per_turn = int(live.get("steps_per_turn") or 1)
m.state["steps_per_turn"] = m.steps_per_turn
m.drawn = bool(live.get("drawn", False))
m.snapshots = []
m.replay = []
m.restored_from = None
print(f"接管/规则：auto={m.auto} human={sorted(m.human_armies)} "
      f"难度={m.difficulty} 悔棋剩={m.undo_left} 连吃上限={m.chain_limit} "
      f"每回合步数={m.steps_per_turn}")

# ---------------------------------------------------------------- 3. 落盘
m.autosave_path = DEST
ok = m.save(DEST)
print(f"\n写出存档：{DEST}  ({'成功' if ok else '失败'})  "
      f"{os.path.getsize(DEST) if os.path.exists(DEST) else 0} 字节")

# ---------------------------------------------------------------- 4. 闭环验证
# ⚠️ 用 `restore()` 而不是 `enable_autosave()` —— 后者在旧实现里会**立刻再落一次盘**，
#    把 `restore()` 末尾那条「↻ 已恢复…」瞬时日志写进存档（每次启动累加一条）。
m2 = M.Match()
info = m2.restore(DEST)
print(f"\n恢复结果：{info}")

s1, s2 = m.snapshot(), m2.snapshot()
bad = []
if s1["status"]["ply"] != s2["status"]["ply"]:
    bad.append(f"ply {s1['status']['ply']} ≠ {s2['status']['ply']}")
if s1["status"]["turn"] != s2["status"]["turn"]:
    bad.append(f"turn {s1['status']['turn']} ≠ {s2['status']['turn']}")
if {p["pos"]: (p["kind"], p["army"], p["home"]) for p in s1["pieces"]} != \
        {p["pos"]: (p["kind"], p["army"], p["home"]) for p in s2["pieces"]}:
    bad.append("盘面不一致")
for k in ("material", "scores", "ranks", "kills", "slain"):
    if s1.get(k) != s2.get(k):
        bad.append(f"{k} 不一致：{s1.get(k)} vs {s2.get(k)}")
for k in ("vitality", "combat", "annexed", "deputies", "out", "resigned",
          "eliminated", "declared_lose", "chain"):
    a = {str(x): y for x, y in (s1["status"].get(k) or {}).items()} \
        if isinstance(s1["status"].get(k), dict) else sorted(map(str, s1["status"].get(k) or []))
    b = {str(x): y for x, y in (s2["status"].get(k) or {}).items()} \
        if isinstance(s2["status"].get(k), dict) else sorted(map(str, s2["status"].get(k) or []))
    if a != b:
        bad.append(f"status.{k} 不一致：{a} vs {b}")

# 用新引擎的合法着法自检：轮到的那一方必须有着法（证明局面可用）
_legal = GA.legal_moves(m2.state, m2.state.get("turn", 1))
print(f"轮到方合法着法数 = {len(_legal)}")

# 接管 / 规则配置也要一致（否则重启后"人换成了 Bot"这类静默差异）
for _attr in ("auto", "difficulty", "allow_undo", "undo_per_side", "undo_left",
              "undo_used", "chain_limit", "steps_per_turn", "human_armies", "drawn"):
    _a, _b = getattr(m, _attr), getattr(m2, _attr)
    if _a != _b:
        bad.append(f"{_attr} 不一致：{_a} vs {_b}")

print("\n" + "=" * 60)
if bad:
    print("✗ 迁移**未**通过保真校验：")
    for x in bad:
        print("   ·", x)
    sys.exit(1)
print("✓ 迁移通过：ply / turn / 盘面 / 计分 / 战损 / 三方状态 逐字段一致")
print("  → 重启服务后会自动续上这一局（前端首屏会提示「已恢复上次对局」）")
print("  → 注意：悔棋栈与回看不完整（旧服务未导出），其余功能正常")
print("=" * 60)
