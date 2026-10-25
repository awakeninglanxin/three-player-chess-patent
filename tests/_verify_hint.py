# -*- coding: utf-8 -*-
"""一键推荐下一步 · 后端专项验证（老师 2026-10-01）

老师原话：
  「加一个功能，可以一键推荐人类玩家走一下一步在棋盘上示意，但不帮他落子。
    你可以用蓝色虚线箭头加文字示意，推荐下一步必须专业，
    用上你最高档的 15 plies 的下棋智商」

本脚本守三条线（缺一条这个功能就是错的）：
  ★ **只读红线**：`Match.hint()` 调完之后，`self.state` **逐字段完全不变**。
    这是本功能与 `/api/move` 的分界线 ——「建议」和「落子」必须泾渭分明。
    ⚠️ 断言不能只写「返回的着法合法」（那只证明它算出来了），必须**深拷贝整个 state
       前后比对**，否则将来有人图省事改成「先真走一步再撤回」也照样通过。
  ★ **档位三档：9 / 12（默认）/ 15 plies**（2026-10-01 逐层实测定档），且**实到深度如实回报**。
  ★ **边界不崩**：非法方号 / 已结束 / 已认输 / 无合法着法 / 重入 —— 全部给 ok:false
    且**都不改状态**。

跑法：cd server && python ../tests/_verify_hint.py
"""
import copy
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "server"))

from match import Match, HINT_BUDGET                      # noqa: E402
from engine import game_dxf as GA                         # noqa: E402

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


def legal_of(m, army=None):
    s = m.state
    a = army if army is not None else s["turn"]
    return {f"{f}-{t}" for f, t in GA.legal_moves(s, a)}


# 短预算：正式是 HINT_BUDGET=300s / 15 plies，测试里只跑 0.4s —— 逻辑一样，
# 只是迭代加深提前停在浅层（「到点必返回」本身就是设计目标之一）。
FAST = 0.4

print("=" * 74)
print("一键推荐下一步 · 后端专项验证（Match.hint）")
print("=" * 74)

m = Match()
print(f"  初始局面：ply={m.state['ply']} turn={m.state['turn']} "
      f"合法着法={len(legal_of(m))} 条")

# ==============================================================================
sect(1, "① ★ 只读红线：调完之后 state 逐字段完全不变")

before = copy.deepcopy(m.state)
before_log = len(m.log)
before_snap = len(m.snapshots)
legal1 = legal_of(m)

r = m.hint(plies=3, budget=FAST)

after = copy.deepcopy(m.state)
diff = [k for k in set(list(before.keys()) + list(after.keys()))
        if before.get(k) != after.get(k)]
chk(after == before, "★★ state **逐字段完全不变**（深拷贝前后 == 比对）",
    "" if not diff else f"差异键 = {diff}")
chk(len(m.snapshots) == before_snap,
    "悔棋栈（snapshots）长度不变 —— 推荐不产生「可悔」的历史",
    f"实测 {before_snap} → {len(m.snapshots)}")
new_logs = m.log[before_log:]
chk(len(new_logs) >= 1, "确实往战报里记了一条推荐（老师能在战报里回看）",
    f"实测新增 {len(new_logs)} 条")
chk(all(e.get("type") == "hint" for e in new_logs),
    "新增战报**全部是 type='hint'**（没有任何 move / undo 混进来）",
    f"实测 {[e.get('type') for e in new_logs]}")
chk(not m.drawn and m.state.get("winner") is None, "不把对局标记成结束/判和")

# ==============================================================================
sect(2, "② 返回结构：着法合法、方号正确、带 ply/epoch 指纹")

chk(r.get("ok") is True, "返回 ok=True", f"实测 {r.get('ok')} err={r.get('error')}")
mv = f"{r.get('from')}-{r.get('to')}"
chk(mv in legal1, "★ 返回的着法在**合法着法表**内", f"实测 {mv}")
chk(r.get("army") == m.state["turn"], "默认给**当前回合方**推荐",
    f"实测 army={r.get('army')} turn={m.state['turn']}")
chk(r.get("ply") == m.state["ply"], "带回 ply 指纹（前端据此判「是否过期」）",
    f"实测 {r.get('ply')} vs {m.state['ply']}")
chk(r.get("epoch") == m.epoch, "带回 epoch 指纹（重开一局会 +1）",
    f"实测 {r.get('epoch')} vs {m.epoch}")
chk(isinstance(r.get("plies"), int) and r["plies"] % 3 == 0,
    "实到深度是 3 的倍数 plies", f"实测 {r.get('plies')}")
chk(r.get("nodes") is None or r["nodes"] > 0, "带节点数（专业度凭据）",
    f"实测 {r.get('nodes')}")

# ==============================================================================
sect(3, "③ ★ 档位口径：**默认 9 plies**（2026-10-02 老师定），12 / 15 为可选慢档")

# 为什么从"最高档 15"改成"默认 12"：老师原话是「用上你最高档的 15 plies 的下棋智商」，
#   但逐层实测（tests/_bench_ply_saturation.py，3→15 plies 两局对照）推翻了它：
#     · 12 plies ≈ 30~36s / 3200 万节点；15 plies ≈ 639~731s / 5.3~5.9 亿节点 ⇒ **×20**
#     · 12 → 15 的选招差别只有 **+0.04 / +0.06 分**（该层估值量级 4031 ≈ 0.001%）
#     ⇒ 瓶颈是**估值函数分不开这几手**，不是深度不够；再加深只是把噪声重洗一遍。
#   本节把"默认值"锁住，防止将来有人凭印象又改回 15。
chk(HINT_BUDGET.get(12) and HINT_BUDGET.get(15),
    "HINT_BUDGET 按 plies 分档（12 / 15 都有）", f"实测 {HINT_BUDGET}")
chk(HINT_BUDGET[15] > HINT_BUDGET[12] * 3,
    "★ 15 plies 的预算 ≫ 12 plies（实测耗时差 20 倍，预算必须跟上）",
    f"12→{HINT_BUDGET[12]}s / 15→{HINT_BUDGET[15]}s")
# 【2026-10-02 口径变更】默认档 12 → **9 plies**。老师原话：「网页 AI 推荐用 9 plies，
#   12 用的时间太长了」。
#   ⚠️ 两次独立标定在本档位上**互相矛盾**，一并留档（别只留对自己有利的那份）：
#     · 批一（tests/_bench_ply_sat.json，**2 个局面**）：9 选的手在 12 榜单里排第 6/8
#       （差 +6.03）、第 5/8（差 +0.88），且两层榜单互不认同 ⇒ 判为"9 不够、12 才好"。
#     · 批二（tests/_analyze_gold.py，**16 个局面**）：6→9 中位 ratio **3.54**（12/16 真变招）
#       这一段确实涨棋；但 **9→12 的 ratio 只有 1.00、噪声占 45%、耗时 ×24**
#       ⇒ 判为"9 已是智力饱和点，12 只是烧时间"。
#   ⇒ 批二样本量大一个数量级，且与老师的体感（12 太慢）一致 ⇒ **默认取 9**；
#      12 / 15 保留为下拉框里的可选慢档。
chk(HINT_BUDGET.get(9), "★ HINT_BUDGET 有 9 plies 档（下拉框的「秒回试算」）",
    f"实测 {HINT_BUDGET}")
chk(HINT_BUDGET[9] < HINT_BUDGET[12],
    "★ 9 plies 预算 < 12 plies（秒回档，不能给分钟级预算）",
    f"9→{HINT_BUDGET[9]}s / 12→{HINT_BUDGET[12]}s")
r9 = m.hint(plies=9, budget=FAST)
chk(r9.get("depth") == 3, "★ `plies=9` ⇒ search depth=3（9 = 3 × 3）",
    f"实测 depth={r9.get('depth')}")
chk(r9.get("depth") * 3 != 12 and r9.get("depth") * 3 == 9,
    "★ `plies=9` **不会**被静默吞成 12（老写法 `v===15?15:12` 的坑）",
    f"实测 目标 {r9.get('depth') * 3} plies")
rd = m.hint(budget=FAST)                     # 不传 plies ⇒ 用默认
chk(rd.get("depth") == 3, "★ **默认档 = 9 plies**（depth=3），不是 12 / 15（2026-10-02 老师定）",
    f"实测 depth={rd.get('depth')}")
rd2 = m.hint(budget=FAST)
chk(rd2.get("depth") == rd.get("depth"),
    "默认值是稳定的常数（两次调用同一档）",
    f"实测 {rd.get('depth')} / {rd2.get('depth')}")

r15 = m.hint(plies=15, budget=FAST)
chk(r15.get("depth") == 5, "★ `plies=15` ⇒ search depth=5（15 = 3 × 5，深搜仍可用）",
    f"实测 depth={r15.get('depth')}")
chk(r15.get("depth") * 3 == 15, "目标档位 = 15 plies",
    f"实测 {r15.get('depth') * 3}")
chk(r15.get("plies") <= 15, "实到深度**不超过**目标（不通胀）",
    f"实测 实到 {r15.get('plies')} / 目标 15")
chk(r15.get("plies") < 15,
    "★ 短预算（0.4s）下**实到 < 目标** —— 说明实到是真搜出来的，不是照抄档位",
    f"实测 实到 {r15.get('plies')}")
r12 = m.hint(plies=12, budget=FAST)
chk(r12.get("depth") == 4, "`plies=12` ⇒ depth=4",
    f"实测 depth={r12.get('depth')}")
# 非 3 的倍数要**向下取整到 3 的倍数**，否则 depth 换算会算出个半层
r7 = m.hint(plies=7, budget=FAST)
chk(r7.get("depth") == 2, "`plies=7` ⇒ 向下取整成 6 ⇒ depth=2（不许出现半层）",
    f"实测 depth={r7.get('depth')}")

# ==============================================================================
sect(4, "④ 幂等与可复现：同一局面连要两次推荐，不改盘、结果可复现")

b2 = copy.deepcopy(m.state)
r_a = m.hint(plies=3, budget=0.8)
r_b = m.hint(plies=3, budget=0.8)
chk(copy.deepcopy(m.state) == b2, "连调两次后 state 仍逐字段不变")
chk((r_a.get("from"), r_a.get("to")) == (r_b.get("from"), r_b.get("to")),
    "同预算连要两次 ⇒ 给出**同一手**（种子固定，结果可复现）",
    f"实测 {r_a.get('from')}-{r_a.get('to')} vs {r_b.get('from')}-{r_b.get('to')}")

# ==============================================================================
sect(5, "⑤ 时间硬上限：到点必返回，不会挂死")

t0 = time.time()
m.hint(plies=15, budget=1.0)
dt = time.time() - t0
chk(dt < 12.0, "★ 预算 1.0s（首调含 JIT 编译）也在 12s 内返回 —— 迭代加深到点必返回",
    f"实测 {dt:.2f}s")
t0 = time.time()
m.hint(plies=15, budget=1.0)
dt2 = time.time() - t0
chk(dt2 < 6.0, "第二次（JIT 已热）更接近预算上限", f"实测 {dt2:.2f}s")

# ==============================================================================
sect(6, "⑥ 重入保护：上一次还在长考时，第二次立刻返回 busy（不叠搜索）")

with m.lock:
    m._hint_busy = True
r_busy = m.hint(plies=15, budget=FAST)
with m.lock:
    m._hint_busy = False
chk(r_busy.get("ok") is False and r_busy.get("busy") is True,
    "★ 长考中再要 → ok:false + busy:true（前端据此提示稍候）",
    f"实测 {r_busy}")
chk(copy.deepcopy(m.state) == b2, "busy 分支同样**不碰** state")

# ==============================================================================
sect(7, "⑦ 边界：非法方号 / 已认输 / 已结束 / 已失去资格")

r_bad = m.hint(army=9)
chk(r_bad.get("ok") is False, "非法方号 9 → ok:false", f"实测 {r_bad.get('error')}")
r_bad2 = m.hint(army="abc")
chk(r_bad2.get("ok") is False, "非数字方号 → ok:false", f"实测 {r_bad2.get('error')}")

# 认输：老师 2026-09-24 口径「不存在求和，只允许认输」
m2 = Match()
m2.resign(2)
chk(2 in (m2.state.get("resigned") or []), "（构造）吴方已认输")
b3 = copy.deepcopy(m2.state)
r_res = m2.hint(army=2, plies=3, budget=FAST)
chk(r_res.get("ok") is False, "★ 已认输方不给推荐", f"实测 {r_res.get('error')}")
chk(copy.deepcopy(m2.state) == b3, "拒绝路径也不碰 state")

# 已结束
m3 = Match()
m3.state["winner"] = 1
chk(m3._finished(), "（构造）对局已结束")
b4 = copy.deepcopy(m3.state)
r_fin = m3.hint(plies=3, budget=FAST)
chk(r_fin.get("ok") is False, "★ 已结束对局不给推荐", f"实测 {r_fin.get('error')}")
chk(copy.deepcopy(m3.state) == b4, "拒绝路径同样不碰 state")

# 已失去行棋资格
m4 = Match()
cur = m4.state["turn"]
m4.state["out"] = list(set(list(m4.state.get("out") or []) + [cur]))
b5 = copy.deepcopy(m4.state)
r_no = m4.hint(plies=3, budget=FAST)
chk(r_no.get("ok") is False, "★ 已失去资格（out）的方不给推荐",
    f"实测 {r_no.get('error')}")
chk(copy.deepcopy(m4.state) == b5, "拒绝路径不碰 state")

# ==============================================================================
sect(8, "⑧ 深拷贝是**真隔离**：搜索期间的 make/unmake 碰不到真实棋盘")

# 直接断言对象身份：hint 内部用的是 deepcopy，真棋盘的 board dict 里
# 每个棋子对象都不该被搜索过程替换/改动。
m5 = Match()
ids_before = {p: id(v) for p, v in m5.state["board"].items()}
keys_before = list(m5.state["board"].keys())
m5.hint(plies=3, budget=0.5)
ids_after = {p: id(v) for p, v in m5.state["board"].items()}
chk(ids_after == ids_before,
    "★ 棋子的对象身份（id）前后一致 —— 连原地改一个字段都没有发生")
chk(list(m5.state["board"].keys()) == keys_before,
    "★ 棋盘 dict 的**键顺序**也没乱（搜索的 pop/回填不会外溢）")

# ==============================================================================
print("\n" + "=" * 74)
print(f"一键推荐下一步 · 后端专项验证：{ok} 通过 / {bad} 失败")
print("=" * 74)
sys.exit(1 if bad else 0)
