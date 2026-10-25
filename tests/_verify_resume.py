# -*- coding: utf-8 -*-
"""续局（重启后接着下）专项验证 —— 独立 Match 实例 + **临时目录**，不碰运行中的服务

老师 2026-10-01：
  「注意如何设计能否重启网页后继续之前的棋局继续下？」
  ⇒ 答案 = 每手落盘（Match._autosave）+ 启动恢复（Match.restore）。

⚠️ 本脚本**绝不允许**触碰 `server/data/autosave.json`（那是老师的真实存档）：
   所有读写都在 `tempfile.mkdtemp()` 出来的临时目录里。第 ③ 节还专门断言
   "裸 Match() 不落盘" —— 这条要是破了，跑一次回归就会把老师的对局冲掉。

运行：python tests/_verify_resume.py
"""
import json
import os
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "server"))

from match import Match, SAVE_VERSION, SAVE_FILE   # noqa: E402
import engine.game_dxf as GA                       # noqa: E402

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


TMP = tempfile.mkdtemp(prefix="sanchi_resume_")
SAVE = os.path.join(TMP, "sub", "autosave.json")     # 故意带不存在的子目录，测 makedirs


def fresh(human=(1,), allow_undo=True, undo_per=3):
    m = Match(auto=False)
    m.alive = False                        # 让 daemon 线程立刻退出
    m.human_armies = set(human)
    m.allow_undo = allow_undo
    m.undo_per_side = undo_per
    m.undo_left = {1: undo_per, 2: undo_per, 3: undo_per}
    m.undo_used = {1: 0, 2: 0, 3: 0}
    return m


def walk(m, n):
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
    return {p: (v["kind"], v["army"], v.get("home"), v.get("deputy"))
            for p, v in m.state["board"].items()}


print("=" * 74)
print("续局 —— 重启网页后接着下（老师 2026-10-01）")
print("=" * 74)

# ============================================================================
sect(1, "① 写盘：原子写 + 目录自动创建 + 无 .tmp 残留")

m = fresh()
walk(m, 5)
chk(not os.path.exists(SAVE), "开自动存盘前，存档不存在", f"路径 {SAVE}")
r = m.enable_autosave(SAVE, restore=False)
chk(os.path.exists(SAVE), "★ enable_autosave 后存档已生成（含自动建子目录）")
chk(not os.path.exists(SAVE + ".tmp"), "★ 无 .tmp 残留（os.replace 已改名）")
chk(m.autosave_path == SAVE, "autosave_path 已就位")
chk(m.saved_at and m.saved_at > 0, "saved_at 已记录", f"实际 {m.saved_at}")
chk(r.get("restored") is False, "restore=False ⇒ 不恢复，只落盘", f"实际 {r}")
d = json.load(open(SAVE, encoding="utf-8"))
chk(d.get("version") == SAVE_VERSION, f"存档 version = {SAVE_VERSION}",
    f"实际 {d.get('version')}")
size = os.path.getsize(SAVE)
print(f"      └ 存档体积：{size / 1024:.1f} KB（5 手局面）")

# ============================================================================
sect(2, "② ★ 恢复：盘面 / 轮次 / 手数 / 统计 / 悔棋次数逐项一致")

ply_before = m.state["ply"]
turn_before = m.state["turn"]
board_before = board_of(m)
left_before = dict(m.undo_left)
used_before = dict(m.undo_used)
replay_before = [x["ply"] for x in m.replay]
snaps_before = len(m.snapshots)

m2 = fresh(human=(9,))                     # 故意用不同席位，验证能被存档覆盖
m2.alive = False
rr = m2.restore(SAVE)
chk(rr.get("restored") is True, "★ 恢复成功", f"实际 {rr}")
chk(m2.state["ply"] == ply_before, f"ply = {ply_before}",
    f"实际 {m2.state['ply']}")
chk(m2.state["turn"] == turn_before, f"turn = {turn_before}",
    f"实际 {m2.state['turn']}")
chk(board_of(m2) == board_before, "★★ 48 个点位逐点比对：kind/army/home/deputy 全等")
chk(dict(m2.undo_left) == left_before, "悔棋剩余次数一致", f"{m2.undo_left}")
chk(dict(m2.undo_used) == used_before, "悔棋已用次数一致", f"{m2.undo_used}")
chk(sorted(m2.human_armies) == [1], "★ 人类席位被存档纠正为 [1]（魏）",
    f"实际 {sorted(m2.human_armies)}")
chk(m2.allow_undo is True, "allow_undo 一致")
chk(m2.difficulty == m.difficulty, f"难度档一致（{m2.difficulty}）")
chk(m2.restored_from and m2.restored_from > 0, "restored_from 已记录存档时间",
    f"实际 {m2.restored_from}")
chk([x["ply"] for x in m2.replay] == replay_before,
    "★ 回看缓冲完整恢复（索引 == ply 的契约未被破坏）",
    f"{len(m2.replay)} 项")
chk(len(m2.snapshots) == snaps_before, f"悔棋存档 {snaps_before} 条已恢复",
    f"实际 {len(m2.snapshots)}")
chk(m2.state.get("chain_limit") == m.state.get("chain_limit")
    and m2.state.get("steps_per_turn") == m.state.get("steps_per_turn"),
    "规则约定（连吃上限 / 每回合步数）一致")

# ============================================================================
sect(3, "③ ★★ 红线：裸 Match() **绝不落盘** —— 否则跑测试就冲掉老师的对局")

existed = os.path.exists(SAVE_FILE)
mt_before = os.path.getmtime(SAVE_FILE) if existed else None
for _ in range(3):
    mm = Match(auto=False)
    mm.alive = False
    walk(mm, 4)                            # 走棋会触发 _autosave()，但 path=None
    mm.set_chain_limit(2)                  # 配置类入口同样不该落盘
    mm.apply_difficulty(3)
mt_after = os.path.getmtime(SAVE_FILE) if os.path.exists(SAVE_FILE) else None
chk(mt_after == mt_before,
    f"★ 真实存档 {os.path.basename(SAVE_FILE)} 未被触碰",
    f"mtime {mt_before} → {mt_after}")
chk(Match(auto=False).autosave_path is None,
    "新 Match 的 autosave_path 默认为 None（必须 app.py 显式开启）")

# ============================================================================
sect(4, "④ ★ 恢复后 int 键字段没被 JSON 变成字符串键（否则会静默下错棋）")

m3 = fresh()
m3.alive = False
walk(m3, 3)
m3.enable_autosave(os.path.join(TMP, "b.json"), restore=False)
m4 = fresh()
m4.alive = False
m4.restore(os.path.join(TMP, "b.json"))
for f in ("vitality", "combat", "annexed", "deputies", "chain"):
    v = m4.state.get(f)
    if isinstance(v, dict) and v:
        chk(all(isinstance(k, int) for k in v),
            f"state[{f!r}] 的键仍是 int（{list(v)[:3]}）",
            f"实际 {[type(k).__name__ for k in v][:3]}")
    else:
        chk(isinstance(v, dict), f"state[{f!r}] 仍是 dict（空表也算过）", f"实际 {v!r}")
# 语义级验证：把战斗力关掉再往返一次，看是否还能读出来
m5 = fresh()
m5.alive = False
walk(m5, 3)
m5.state["combat"][1] = False
m5.enable_autosave(os.path.join(TMP, "c.json"), restore=False)
m6 = fresh()
m6.alive = False
m6.restore(os.path.join(TMP, "c.json"))
chk(m6.state["combat"].get(1) is False,
    "★★ 语义级：combat[1]=False 往返后仍能读到 False（不是被字符串键吞掉）",
    f"实际 {m6.state['combat']}")

# ============================================================================
sect(5, "⑤ 恢复后能接着下棋、也能悔棋（跨重启不丢功能）")

m7 = fresh()
m7.alive = False
walk(m7, 3)
m7.enable_autosave(os.path.join(TMP, "d.json"), restore=False)
m8 = fresh()
m8.alive = False
m8.restore(os.path.join(TMP, "d.json"))
turn0, ply0 = m8.state["turn"], m8.state["ply"]
legal = GA.legal_moves(m8.state, turn0)
a, b = legal[0]
res = m8.manual_move(a, b)
chk(res.get("ok") is True, f"★ 恢复后接着走 {a}-{b} 成功", f"实际 {res}")
chk(m8.state["ply"] == ply0 + 1, "ply 正常递增", f"实际 {m8.state['ply']}")
r2 = m8.undo_last()
chk(r2.get("ok") is True, "★ 恢复后仍可悔棋（snapshots 被完整带回来了）",
    f"实际 {r2}")
chk(m8.state["ply"] == ply0, "悔棋后 ply 回到恢复时的值",
    f"实际 {m8.state['ply']}")
chk(r2.get("rolled_back", 0) >= 1, "新口径的「连带退回」在恢复后的实例上照常工作",
    f"退 {r2.get('rolled_back')} 手")

# ============================================================================
sect(6, "⑥ 存档损坏 / 版本不匹配 → 弃用 + 备份 + 不抛异常（绝不能启动不了）")

p_bad = os.path.join(TMP, "broken.json")
open(p_bad, "w", encoding="utf-8").write("{这不是合法 JSON!!")
m9 = fresh()
m9.alive = False
r9 = m9.restore(p_bad)
chk(r9.get("restored") is False, "损坏存档 → 不恢复", f"实际 {r9}")
chk("损坏" in (r9.get("reason") or ""), "原因写明是损坏", f"实际 {r9.get('reason')}")
chk(not os.path.exists(p_bad), "原文件已被移走")
bads = [f for f in os.listdir(TMP) if f.startswith("broken.json.bad_")]
chk(len(bads) == 1, "★ 生成了 .bad_<时间戳> 备份（可事后排查）", f"实际 {bads}")
chk(m9.state["ply"] == 0, "该实例仍是可用的新局（ply=0）", f"实际 {m9.state['ply']}")

p_old = os.path.join(TMP, "oldver.json")
json.dump({"version": SAVE_VERSION - 1, "state": GA.new_game(1)},
          open(p_old, "w", encoding="utf-8"), ensure_ascii=False)
m10 = fresh()
m10.alive = False
r10 = m10.restore(p_old)
chk(r10.get("restored") is False, "★ 版本不匹配 → 弃用（不硬兼容）",
    f"实际 {r10}")
chk("版本" in (r10.get("reason") or ""), "原因写明版本问题",
    f"实际 {r10.get('reason')}")
chk(len([f for f in os.listdir(TMP) if f.startswith("oldver.json.bad_")]) == 1,
    "同样留了备份")

p_nostate = os.path.join(TMP, "nostate.json")
json.dump({"version": SAVE_VERSION, "saved_at": time.time()},
          open(p_nostate, "w", encoding="utf-8"))
m11 = fresh()
m11.alive = False
r11 = m11.restore(p_nostate)
chk(r11.get("restored") is False and "盘面" in (r11.get("reason") or ""),
    "state 缺失 → 明确拒绝", f"实际 {r11}")

# ============================================================================
sect(7, "⑦ 无存档 / restore=False 的行为")

m12 = fresh()
m12.alive = False
r12 = m12.restore(os.path.join(TMP, "not_exist.json"))
chk(r12.get("restored") is False and r12.get("reason") == "无存档",
    "文件不存在 → 静默开新局（不是报错）", f"实际 {r12}")

# ============================================================================
sect(8, "⑧ discard_save：丢存档 + 开新局，文件被删")

p_d = os.path.join(TMP, "keep.json")
m13 = fresh()
m13.alive = False
walk(m13, 3)
m13.enable_autosave(p_d, restore=False)
chk(os.path.exists(p_d), "先有存档")
rd = m13.discard_save()
chk(rd.get("ok") is True, "丢弃成功", f"实际 {rd}")
chk(m13.state["ply"] == 0, "回到开局", f"实际 {m13.state['ply']}")
chk(m13.restored_from is None, "restored_from 已清空（不再显示「已恢复」）",
    f"实际 {m13.restored_from}")

# ============================================================================
sect(9, "⑨ 终局也能恢复（不丢结果，网页能直接看到终局画面）")

m14 = fresh()
m14.alive = False
walk(m14, 3)
GA.resign(m14.state, 2)
m14.drawn = True
p_e = os.path.join(TMP, "ended.json")
m14.enable_autosave(p_e, restore=False)
m15 = fresh()
m15.alive = False
r15 = m15.restore(p_e)
chk(r15.get("restored") is True, "★ 终局存档照样恢复", f"实际 {r15}")
chk(m15.drawn is True, "drawn 标志被带回来了", f"实际 {m15.drawn}")
chk(2 in m15.state.get("resigned", []), "认输记录也在",
    f"实际 {m15.state.get('resigned')}")

# ============================================================================
sect(10, "⑩ /api/state 的续局字段")

m16 = fresh()
m16.alive = False
walk(m16, 3)
m16.enable_autosave(os.path.join(TMP, "snap.json"), restore=False)
snap = m16.snapshot()
chk(snap.get("autosave") is True, "autosave=True", f"实际 {snap.get('autosave')}")
chk(snap.get("restored") is False, "本实例不是恢复来的 ⇒ restored=False")
chk(snap.get("saved_at"), "saved_at 有值", f"实际 {snap.get('saved_at')}")
chk(snap.get("save_error") == "", "无存盘错误", f"实际 {snap.get('save_error')!r}")
m17 = fresh()
m17.alive = False
m17.restore(os.path.join(TMP, "snap.json"))
chk(m17.snapshot().get("restored") is True, "★ 恢复来的实例 restored=True")
chk(m17.snapshot().get("restored_from"), "restored_from 有值（前端显示存档时间）")

# ============================================================================
sect(11, "⑪ 存盘失败不影响下棋（把路径设成非法）")

m18 = fresh()
m18.alive = False
m18.autosave_path = os.path.join(TMP, "no_such_dir\x00bad", "x.json")  # NUL 非法
res18 = m18.manual_move(*GA.legal_moves(m18.state, m18.state["turn"])[0])
chk(res18.get("ok") is True, "★ 存盘失败时走棋依然成功（不因 I/O 拖垮对局）",
    f"实际 {res18}")
chk(m18.save_error != "", "失败原因被记进 save_error 供排查",
    f"实际 {m18.save_error!r}")

# ============================================================================
sect(12, "⑫ 反复存读 20 轮：状态不漂移（幂等）")

m19 = fresh()
m19.alive = False
walk(m19, 4)
p_i = os.path.join(TMP, "iter.json")
m19.enable_autosave(p_i, restore=False)
ref = json.dumps(m19._save_payload()["state"], sort_keys=True, ensure_ascii=False)
drift = []
for i in range(20):
    a = fresh()
    a.alive = False
    a.restore(p_i)
    a.autosave_path = p_i
    a.save()                                # 再写一次
    nxt = json.dumps(json.load(open(p_i, encoding="utf-8"))["state"],
                     sort_keys=True, ensure_ascii=False)
    if nxt != ref:
        drift.append(i)
        ref = nxt
chk(drift == [], "★ 20 轮存→读→存 完全幂等（state 无漂移）", f"漂移轮次 {drift}")

# ============================================================================
print("\n" + "=" * 74)
print(f"结果：OK = {ok}   FAIL = {bad}")
print(f"（测试全程使用临时目录 {TMP}；真实存档 {SAVE_FILE} 未被触碰）")
print("=" * 74)
shutil.rmtree(TMP, ignore_errors=True)
sys.exit(1 if bad else 0)
