# -*- coding: utf-8 -*-
"""三人象棋 · Bot 难度档专项验证（老师 2026-09-25）

老师原话：
  ①「网页设置难度4个档，最低档不需要树状预判，属于新手，然后第二档，
      就是博弈树逐层 3 plies，第3档6 plies，第4档9 plies可以吗？」
  ②「bot挑战难度档位可以在网页里面选择，默认选第二档」
  ③「可以考虑让bot加更多挑战难度档，提高bot的智商，但不要烧钱，也不要卡死」

本文件验证 12 节：
  ① 档位表：plies = [0,3,6,9,12]，且 plies = 3 × depth（档1 无深度）
  ② apply() 不改原 cfg、标签正确、档1 清掉 depth/time_limit
  ③ 默认档 = 2（老师指定），且 agents.json 写的就是 2
  ④ Match 启动后三方确实按默认档建（SearchBot · 1 层）
  ⑤ 切档 1 → 三方 LocalBot（新手·不建树）
  ⑥ 切档 4 → SearchBot depth=3 / 45s
  ⑦ 切档 5 → SearchBot depth=4 / 60s（**最高档**）
  ⑧ **切档不动对局**：棋盘 / 手数 / 轮次 / 战绩全程不变
  ⑨ 人类接管设置不被切档影响
  ⑩ **真实大模型不被难度档覆盖**（且 skipped 如实上报）
  ⑪ /api/state 快照字段齐备（difficulty / levels / actual_plies / skipped）
  ⑫ **不卡死**：硬性 time_limit 真的会截断（给 1s 预算，实测不超 2.5s）

★ 2026-10-02 变更：第 6 档「传奇 · 15 plies」**已由老师撤除**
  （「去掉 15 piles 这第 6 档难度，因为时间太久，性价比不高，下棋太慢」）
  ⇒ 档位表上限从 15 plies 收到 12 plies、档数 6 → 5。
  本节 §①/§②/§③/§⑤/§⑪/§⑫ 的相关断言已同步改写，
  并新增「**上限守卫**」：断言最高档 = 12 plies，防止这一档被无意识加回。
"""
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "server"))

from agents import difficulty as D          # noqa: E402
from engine import game_dxf as GA           # noqa: E402
from match import Match                     # noqa: E402

PASS = []
FAIL = []


def chk(cond, name, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'✓' if cond else '✗'} {name}" + (f"   [{detail}]" if detail else ""))
    return bool(cond)


def sect(n, t):
    print(f"\n{'=' * 72}\n{n} {t}\n{'=' * 72}")


def fingerprint(m):
    """对局指纹：切档前后必须完全一致（证明「只换脑子，不动棋局」）"""
    s = m.state
    return {
        "board": dict(s["board"]),
        "ply": s["ply"],
        "turn": s["turn"],
        "out": sorted(s.get("out") or []),
        "kills": dict(m.kills),
        "slain": dict(m.slain),
        "wrong": dict(m.wrong),
    }


def label_of(m, k):
    return m.meta[k]["label"]


def agent_of(m, k):
    return m.agents[k].__class__.__name__


# ------------------------------------------------------------------ ①
sect(1, "① 档位表：plies = [0,3,6,9,12]，且 plies = 3 × depth")
lvs = D.all_levels()
chk([lv["plies"] for lv in lvs] == [0, 3, 6, 9, 12],
    "五档 plies = 0 / 3 / 6 / 9 / 12（0 = 新手不建树；15 plies 档已撤除）",
    f"{[lv['plies'] for lv in lvs]}")
bad = [lv["level"] for lv in lvs
       if lv["plies"] and D.get(lv["level"])["plies"] != 3 * D.get(lv["level"])["depth"]]
chk(not bad, "每一档都满足 plies = 3 × depth（三人棋一轮 = 三方各一步 = 3 plies）",
    f"异常档 {bad}" if bad else "全部满足")
chk(D.get(1)["model_id"] == "__local__"
    and all(D.get(i)["model_id"] == "__search__" for i in (2, 3, 4, 5)),
    "档1 走贪心（不建树）；档2~5 全走搜索（博弈树逐层）")
#   ★ 上限守卫（2026-10-02）：15 plies 那一档已由老师撤除，不允许被无意识加回。
#     想加回来 ⇒ 先重做 16 局面标定（`tests/_analyze_gold.py`），再改这里与
#     `difficulty._selftest()` ⑤，两处必须同时改。
chk(max(lv["plies"] for lv in lvs) == 12 and len(lvs) == 5,
    "★ 上限守卫：最高档 = 12 plies、共 5 档（15 plies 档 2026-10-02 已撤除）",
    f"最高 {max(lv['plies'] for lv in lvs)} plies / {len(lvs)} 档")
chk([lv["level"] for lv in lvs] == [1, 2, 3, 4, 5],
    "档位号连续 1..5（前端按钮按下标高亮，跳号会错位）",
    str([lv["level"] for lv in lvs]))
#   硬性时间上限必须逐档递增（高档必须给更多预算，否则名不副实）
tls = [D.get(i).get("time_limit") or 0 for i in (2, 3, 4, 5)]
chk(tls == sorted(tls) and all(t > 0 for t in tls),
    "档2~5 都有**硬性时间上限**且逐档递增（这就是「不卡死」的保证）",
    f"{tls} 秒")

# ------------------------------------------------------------------ ②
sect(2, "② apply() 不改原 cfg / 标签正确 / 档1 清掉 depth+time_limit")
src = {"army": "魏", "model_id": "__local__", "url": "http://x", "api_key": "k"}
a2, a1, a5 = D.apply(src, 2), D.apply(src, 1), D.apply(src, 5)
chk(src["model_id"] == "__local__" and "depth" not in src,
    "原 cfg 对象**未被修改**（纯函数，多次切档不会互相污染）")
chk(a2["model_id"] == "__search__" and a2["depth"] == 1 and a2["time_limit"] == 3.0,
    "档2 → __search__ / depth=1 / 3.0s")
chk(a5["model_id"] == "__search__" and a5["depth"] == 4 and a5["time_limit"] == 60.0,
    "档5 → __search__ / depth=4 / 60.0s（最高档）")
chk("depth" not in a1 and "time_limit" not in a1,
    "档1 → 清掉 depth/time_limit（贪心 Bot 不看这两个键，留着是误导）")
chk(a2["label"] == "魏方·入门（3 plies）" and a1["label"] == "魏方·新手（不预判）",
    "标签随档位变化（战报/排名表里一眼能看出当前难度）",
    f"{a1['label']} / {a2['label']}")
chk(a2["url"] == "http://x" and a2["api_key"] == "k",
    "apply 保留原 cfg 的其它字段（url / api_key 不丢）")

# ------------------------------------------------------------------ ③
sect(3, "③ 默认档 = 2（老师指定），agents.json 也写着 2")
chk(D.DEFAULT_LEVEL == 2, "difficulty.DEFAULT_LEVEL == 2")
chk(D.norm(None) == 2 and D.norm("x") == 2 and D.norm(0) == 1 and D.norm(99) == 5,
    "非法输入安全兜底（None/乱码→2；0→1；99→5 上限）",
    f"norm(None)={D.norm(None)} norm(0)={D.norm(0)} norm(99)={D.norm(99)}")
#   ★ 老存档里可能写着 difficulty=6（撤档前的局）⇒ 必须被**夹到 5**，不能崩
chk(D.norm(6) == 5,
    "★ 老存档兼容：difficulty=6（撤档前的存档）被夹到 5（宗师），不报错、不越界",
    f"norm(6)={D.norm(6)}")
import json                                    # noqa: E402
with open(os.path.join(ROOT, "server", "agents", "agents.json"), encoding="utf-8") as f:
    aj = json.load(f)
chk(aj["options"].get("difficulty") == 2,
    "agents.json → options.difficulty = 2",
    str(aj["options"].get("difficulty")))

# ------------------------------------------------------------------ ④
sect(4, "④ Match 启动后按默认档建三方")
m = Match()                                    # 用真实 agents.json
m.pause()
chk(m.difficulty == 2, "Match.difficulty == 2（默认第二档）", str(m.difficulty))
chk(all(agent_of(m, k) == "SearchBot" for k in (1, 2, 3)),
    "三方 agent 都是 SearchBot（不是一步贪心）",
    str([agent_of(m, k) for k in (1, 2, 3)]))
chk(all(m.agents[k].depth_layers == 1 for k in (1, 2, 3)),
    "depth_layers = 1 ⇒ 3 plies（档2 的口径）",
    str([m.agents[k].depth_layers for k in (1, 2, 3)]))

# ------------------------------------------------------------------ ⑤⑥⑦
sect(5, "⑤⑥⑦ 切档：1 → LocalBot ｜ 4 → depth3/45s ｜ 5 → depth4/60s")
r1 = m.set_difficulty(1)
chk(r1["ok"] and m.difficulty == 1, "set_difficulty(1) 返回 ok，档位已变")
chk(all(agent_of(m, k) == "LocalBot" for k in (1, 2, 3)),
    "档1 → 三方 LocalBot（一步贪心，**完全不建搜索树**）",
    str([agent_of(m, k) for k in (1, 2, 3)]))
chk(all("新手" in label_of(m, k) for k in (1, 2, 3)),
    "档1 标签含「新手」", label_of(m, 1))

m.set_difficulty(4)
chk(all(agent_of(m, k) == "SearchBot" and m.agents[k].depth_layers == 3
        and m.agents[k].time_limit == 45.0 for k in (1, 2, 3)),
    "档4 → SearchBot depth=3（= 9 plies）/ 45s",
    f"{[m.agents[k].depth_layers for k in (1,2,3)]} / {m.agents[1].time_limit}s")
chk(all("大师" in label_of(m, k) for k in (1, 2, 3)), "档4 标签含「大师」", label_of(m, 1))

m.set_difficulty(5)
chk(all(m.agents[k].depth_layers == 4 and m.agents[k].time_limit == 60.0
        for k in (1, 2, 3)),
    "档5 → SearchBot depth=4（= 12 plies）/ 60s（**最高档**）",
    f"{[m.agents[k].depth_layers for k in (1,2,3)]} / {m.agents[1].time_limit}s")
chk(all("宗师" in label_of(m, k) for k in (1, 2, 3)), "档5 标签含「宗师」", label_of(m, 1))
#   ★ 越界请求（老前端 / 老存档发 level=6）⇒ 夹到最高档 5，不崩、不静默变默认档2
r6 = m.set_difficulty(6)
chk(r6["ok"] and m.difficulty == 5 and D.norm(6) == 5,
    "★ 越界请求 level=6（撤档前的老前端/老存档）⇒ 夹到最高档 5，不报错",
    f"difficulty={m.difficulty}")

# ------------------------------------------------------------------ ⑧
sect(8, "⑧ **切档不动对局**（棋盘 / 手数 / 轮次 / 战绩全程不变）")
m.set_difficulty(2)
#   手动走 3 手（直接改 state，绕开后台线程，保证同步）
for _ in range(3):
    lg = GA.legal_moves(m.state, m.state["turn"])
    if not lg:
        break
    GA.apply(m.state, lg[0][0], lg[0][1])
before = fingerprint(m)
chk(before["ply"] == 3, "先走 3 手，ply = 3", f"ply={before['ply']}")

for lv in (1, 3, 5, 4, 2):                      # 来回切 5 次
    m.set_difficulty(lv)
after = fingerprint(m)
chk(before == after,
    "连切 5 次档位后，棋盘 / 手数 / 轮次 / 战绩**完全一致**",
    "一致" if before == after else "★有差异")
chk(len(m.agents) == 3 and sorted(m.agents) == [1, 2, 3],
    "切档只替换 agent 对象，不产生多余/缺失的方")
# 【2026-10-01 口径变更】老师：「开局默认，人类掌控魏国棋子，打勾」
#   ⇒ agents.json 的 options.human_armies 现为 [1]，不再默认空集（三方全 Bot）。
chk(m.human_armies == {1},
    "默认 human_armies = [1]（魏归人类，读 agents.json 配置）",
    str(sorted(m.human_armies)))

# ------------------------------------------------------------------ ⑨
sect(9, "⑨ 人类接管设置不被切档影响")
m.set_human([1])
chk(m.human_armies == {1}, "set_human([1]) → 人类走魏方", str(sorted(m.human_armies)))
snap_before = m.snapshot()["human_armies"]
m.set_difficulty(5)
chk(m.human_armies == {1} and m.snapshot()["human_armies"] == snap_before,
    "切到档5 后 human_armies 仍为 [1]（人类接管不受难度档影响）",
    str(m.snapshot()["human_armies"]))
m.set_human([])

# ------------------------------------------------------------------ ⑩
sect(10, "⑩ 真实大模型不被难度档覆盖（skipped 如实上报）")
roster = {
    "players": {
        "1": {"army": "魏", "model_id": "__search__", "depth": 1,
              "time_limit": 3.0, "label": "魏方·入门（3 plies）"},
        "2": {"army": "吴", "model_id": "__local__", "label": "吴方·新手（不预判）"},
        "3": {"army": "蜀", "model_id": "deepseek-v4-flash", "label": "蜀方·DeepSeek"},
    },
    "options": {"difficulty": 2, "grade_moves": False, "max_ply": 300},
}
m2 = Match(roster)
m2.pause()
chk(agent_of(m2, 3) == "LLMAgent", "蜀方初始为 LLMAgent（真实大模型）", agent_of(m2, 3))
r = m2.set_difficulty(5)
chk(m2.roster["players"]["3"]["model_id"] == "deepseek-v4-flash",
    "切档**没有改** roster 里蜀方的 model_id（原配置零污染）")
chk(m2.meta[3]["model"] == "deepseek-v4-flash",
    "蜀方 meta 仍是 deepseek-v4-flash（未被换成本地 Bot）")
chk(all(m2.agents[k].__class__.__name__ == "SearchBot" for k in (1, 2)),
    "魏/吴（本地 Bot）已切到档5 的 SearchBot")
chk(r.get("skipped") == ["蜀"],
    "返回值如实上报 skipped = ['蜀']（前端据此提示「不受难度档影响」）",
    str(r.get("skipped")))

# ------------------------------------------------------------------ ⑪
sect(11, "⑪ /api/state 快照字段齐备")
m.set_difficulty(2)                            # 第9节切到过档5，这里切回默认档再验
snap = m.snapshot()
chk(snap.get("difficulty") == 2, "snapshot.difficulty = 2", str(snap.get("difficulty")))
chk(len(snap.get("difficulty_levels") or []) == 5,
    "snapshot.difficulty_levels 含 5 档（前端据此动态画按钮，增档不用改前端）",
    f"{len(snap.get('difficulty_levels') or [])} 档")
chk(set((snap.get("difficulty_meta") or {}).keys())
    >= {"level", "name", "plies", "brief", "desc", "depth", "time_limit"},
    "snapshot.difficulty_meta 字段完整（名称 / plies / 上限 / 说明）",
    str(sorted((snap.get("difficulty_meta") or {}).keys())))
chk("actual_plies" in snap and "difficulty_skipped" in snap,
    "snapshot 带 actual_plies（实到深度）与 difficulty_skipped（大模型方）")

# ------------------------------------------------------------------ ⑫
sect(12, "⑫ **不卡死**：硬性 time_limit 真的会截断（给 1s 预算）")
# ⚠️【2026-09-26 · JIT 内核（方案 ①）接入后必须预热】
#   numba 的 `@njit(cache=True)` 首次调用要**现场编译**（本机实测 ~20s）。
#   不预热的话，下面测到的 dt 里含编译开销 ⇒ 必然超 2.5s ⇒ 被误判成"卡死"。
#   生产路径同理：`app.py` 启动时用**后台线程**预热，老师的第一手棋才不卡。
from search_bot import _jit_warmup                    # noqa: E402
t_warm = time.time()
_jit_warmup()
print(f"  （JIT 预热 {time.time() - t_warm:.1f}s，一次性；计入预热才不会误判）")
s = GA.new_game()
for _ in range(9):                              # 制造中局（分支多、更贵）
    lg = GA.legal_moves(s, s["turn"])
    if not lg:
        break
    GA.apply(s, lg[0][0], lg[0][1])
b = m.agents[1]                                 # 当前档2 的 SearchBot
b.depth_layers = 4                              # 强行拉到最高档（档5）的深度
b.time_limit = 1.0                              # 但只给 1 秒
t0 = time.time()
res = b.choose(s, GA.legal_moves(s, s["turn"]), "", "魏")
dt = time.time() - t0
chk(dt < 2.5, "预算 1.0s（depth 拉到 4 层）→ 实测 %.2fs 就返回，**没有卡死**" % dt,
    f"{dt:.2f}s")
chk(res.get("move") and res.get("ok"),
    "超时截断后仍给出**可用的着法**（迭代加深保证永远有答案）",
    str(res.get("move")))
chk(b.last_info.get("plies") in (3, 6, 9, 12),
    "last_info.plies 如实记录**实际搜到的深度**（15 plies 档已撤除 ⇒ 不再出现）",
    f"实到 {b.last_info.get('plies')} plies")

# ------------------------------------------------------------------ ⑬
sect(13, "⑬ 长考档健壮性：长考中**快照不被阻塞** + 思考中重开一局**不污染新局**")
import threading                              # noqa: E402

m3 = Match()
m3.pause()
# ⚠️ 必须清空人类席位：agents.json 默认 `human_armies: [1]`（魏归老师），
#   而 step() 对"人类接管的方"直接 return 不代走 ⇒ 本节要验"长考中快照不被阻塞"
#   就永远等不到 thinking（假失败）。本节前提是三方全 Bot。
m3.human_armies = set()
m3.set_difficulty(4)                          # 档4：depth=3 / 45s
for k in (1, 2, 3):
    # ⚠️【2026-09-26 · numba 内核接入后必须改这两个数】
    #   本节要验的是「长考进行中，快照/重开不被阻塞」，前提是**真的在长考**。
    #   旧值是 time_limit=3.0s：JIT 内核下 3 plies 0.01s、6 plies 0.29s，
    #   而 9 plies 的**时间外推**估算 est = n_last×ratio/nps ≈ 5.8s > 剩余预算
    #   ⇒ `_choose_jit` 直接 break，**整手 0.30s 就返回** ⇒ `time.sleep(0.35)` 后
    #     `thinking` 已是 None，本节的"已进入思考态"会误报失败（实测如此）。
    #   改成 15.0s：est 5.8s 远小于预算 ⇒ 9 plies 能开 ⇒ 整手约 2.6s，
    #   0.35s 时确实处于长考中，本节才测到它想测的东西。
    m3.agents[k].time_limit = 15.0
    m3.agents[k].depth_layers = 3

ep_before = m3.epoch
done = {}


def _run_step():
    try:
        m3.step()
    except Exception as e:                    # noqa: BLE001
        done["err"] = f"{type(e).__name__}: {e}"
    done["ok"] = True


th = threading.Thread(target=_run_step, daemon=True)
th.start()
time.sleep(0.35)                              # 让它进入长考
chk(m3.thinking in (1, 2, 3), "已进入思考态（thinking=%s）" % m3.thinking,
    str(m3.thinking))

#   —— 长考进行中，取快照（= 网页每 800ms 轮询走的路径）
lat = []
for _ in range(8):
    t0 = time.time()
    m3.snapshot()
    lat.append(time.time() - t0)
    time.sleep(0.05)
worst = max(lat)
chk(worst < 0.5,
    "长考**进行中**取 8 次快照，最慢仅 %.3fs ⇒ 页面轮询/finished 判定不被阻塞"
    % worst, f"max={worst:.3f}s")

#   —— 长考进行中，重开一局（老师等不及时的真实操作）
m3.reset()
chk(m3.epoch == ep_before + 1, "reset() 使世代号 +1（%d → %d）"
    % (ep_before, m3.epoch), str(m3.epoch))
chk(m3.state["ply"] == 0, "新局 ply = 0", str(m3.state["ply"]))

th.join(timeout=20)
chk(done.get("ok") and not done.get("err"),
    "长考线程正常结束（没有异常逃逸）", str(done))
moves_in_new_log = [e for e in m3.log if e.get("type") == "move"]
chk(not moves_in_new_log,
    "★ 新局战报里**没有**旧局的幽灵着法（世代号校验整手丢弃）",
    f"{len(moves_in_new_log)} 条" if moves_in_new_log else "0 条")
chk(m3.state["ply"] == 0,
    "思考结束回写后，新局 ply 仍为 0（旧手没有落到新局）",
    f"ply={m3.state['ply']}")
chk(all(v == 0 for v in m3.kills.values())
    and all(v == 0 for v in m3.slain.values())
    and all(v == 0 for v in m3.wrong.values()),
    "新局战绩 kills / slain / wrong 全为 0（全局统计未被旧手污染）",
    f"kills={dict(m3.kills)}")
chk(m3.thinking is None, "thinking 已复位为 None（页面不会一直显示「长考中…」）",
    str(m3.thinking))

# ------------------------------------------------------------------ 汇总
print(f"\n{'=' * 72}")
print(f"难度档专项验证：{len(PASS)} 通过 / {len(FAIL)} 失败")
if FAIL:
    print("失败项：")
    for f in FAIL:
        print("  ✗", f)
print("=" * 72)
sys.exit(1 if FAIL else 0)
