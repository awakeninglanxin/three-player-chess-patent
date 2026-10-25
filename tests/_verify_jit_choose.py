# -*- coding: utf-8 -*-
"""JIT 接入 `SearchBot` 后的 `choose()` 层双门禁（方案 ① 第三段门禁）

【与 `_verify_nb_search.py` 的分工】
    那个脚本直接调 `bot._root_search` / `NB.search_plies` —— 是**根层**对拍，
    绕过了迭代加深、时间外推、渐进加宽；
    本脚本走**完整 `choose()`**，也就是老师真正调用 bot 的那条路：
        `SearchBot(use_jit=False).choose(...)`  vs  `SearchBot(use_jit=True).choose(...)`
    它能抓到只在 `_choose` ↔ `_choose_jit` 之间才存在的分歧：
      · 迭代加深的**层数**不同步（一边 6 plies、一边只到 3 plies）
      · 时间外推把某一层**砍掉**（ratio / est / 1.15 余量口径不一致）
      · 渐进加宽的**候选集**不同（`ranked[:keep]` 的 keep 表或 ranked 顺序不同）
      · 节点计数口径不同（累计 vs 每层重置 —— 2026-09-26 刚修过一个）

【为什么必须 noise=0】
    `SearchBot.__init__` 的 noise 默认 **0.5**，`_root_search` 返回的 best_score 是
    `sc + rng.random() * noise`；JIT 侧虽然是 numpy RNG（不同随机流），
    但两边都乘 0 时结果都是纯 sc —— 只有 noise=0 两边才逐位可比。
    （这也是实际对局里的"探索噪声"，正式运行时保留即可。）

【为什么 time_limit 给得很大】
    迭代加深的"时间外推"会在 `est * 1.15 > 剩余预算` 时**提前 break**。
    若预算卡在临界，Python 与 JIT 的 est 不同（速度差 16×）⇒ 开的层数不同 ⇒
    看起来"结果不一致"，其实是**预算触发的合法差异**，不是 bug。
    给足预算（60s）让两边都跑满 `depth_layers`，才能逐层比对。
"""
import os
import random
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "server"))
sys.path.insert(0, os.path.join(HERE, "..", "server", "agents"))

from engine import game_dxf as GA            # noqa: E402
from engine import geometry_dxf as D         # noqa: E402
from search_bot import SearchBot             # noqa: E402

OK = 0
FAIL = 0
FAILS = []


def chk(cond, msg, detail=""):
    global OK, FAIL
    if cond:
        OK += 1
    else:
        FAIL += 1
        FAILS.append(msg + (f"  [{detail}]" if detail else ""))
        if len(FAILS) <= 25:
            print(f"  x {msg}  {detail}")


def random_positions(n, seed=777, steps=(8, 34)):
    """与 `_verify_nb_search.py` 同 seed 同口径，保证两段门禁测的是同一批局面"""
    rng = random.Random(seed)
    out = []
    for i in range(n):
        s = GA.new_game(first=1 + (i % 3))
        target = rng.randint(*steps)
        for _ in range(target):
            lm = GA.legal_moves(s, s["turn"])
            if not lm:
                break
            frm, to = rng.choice(lm)
            try:
                GA.apply(s, frm, to)
            except Exception:
                break
            if GA.status(s).get("winner"):
                break
        out.append((f"局{i + 1}/{target}步", s))
    return out


def force_turn(state, me):
    """复制局面并强制该方走棋（覆盖三方，而不只是历史走到的那个 turn）"""
    s = dict(state)
    s["board"] = dict(state["board"])
    s["turn"] = me
    return s


def main():
    print("=" * 78)
    print("JIT 接入 SearchBot 后的 choose() 层双门禁（方案 ① 第三段）")
    print("=" * 78)

    depth = int(os.environ.get("VJC_DEPTH", "2"))        # 2 层 = 6 plies
    tlim = float(os.environ.get("VJC_TLIM", "60"))       # 给足预算，两边都跑满

    py_bot = SearchBot(depth=depth, time_limit=tlim, noise=0.0, use_jit=False)
    jt_bot = SearchBot(depth=depth, time_limit=tlim, noise=0.0, use_jit=True)
    if not jt_bot.use_jit:
        print("!! JIT 内核不可用（numba 缺失或 CHESS_NO_JIT=1），本脚本无意义")
        return 0
    print(f"JIT 可用: True   depth={depth}层({depth * 3} plies)   time_limit={tlim}s   noise=0.0")

    # 预热：把 numba 编译开销**排除**在计时之外（否则第一局 JIT "慢" 是编译）
    from search_bot import _jit_warmup
    t0 = time.time()
    _jit_warmup()
    print(f"JIT 预热耗时 {time.time() - t0:.2f}s（一次性，之后是缓存）\n")

    cases = random_positions(8)
    cases.insert(0, ("开局", GA.new_game(first=1)))

    n_same = 0
    n_tot = 0
    t_py = 0.0
    t_jt = 0.0

    for tag, s0 in cases:
        for me in (1, 2, 3):
            s = force_turn(s0, me)
            legal = list(GA.legal_moves(s, me))
            if not legal:
                continue
            n_tot += 1

            t0 = time.time()
            py_res = py_bot.choose(s, legal)
            dt_py = time.time() - t0
            t_py += dt_py

            t0 = time.time()
            jt_res = jt_bot.choose(s, legal)
            dt_jt = time.time() - t0
            t_jt += dt_jt

            p_mv = py_res.get("move")
            j_mv = jt_res.get("move")
            p_info = py_bot.last_info
            j_info = jt_bot.last_info

            same = (p_mv == j_mv)
            n_same += 1 if same else 0

            # ① 着法必须完全一致（noise=0 时不该有"并列分随意选"）
            chk(same, f"{tag}·{D.ARMY_CN[me]} choose() 着法一致",
                f"Py={p_mv} JIT={j_mv}")
            # ② 迭代加深到达的层数必须一致
            chk(p_info.get("plies") == j_info.get("plies"),
                f"{tag}·{D.ARMY_CN[me]} 到达层数一致",
                f"Py={p_info.get('plies')} JIT={j_info.get('plies')}")
            # ③ 分数必须一致（last_info 里是 round 到 2 位，容差取半个分位 0.011）
            dsc = abs(float(p_info.get("score", 0)) - float(j_info.get("score", 0)))
            chk(dsc <= 0.011, f"{tag}·{D.ARMY_CN[me]} 分数一致",
                f"Py={p_info.get('score')} JIT={j_info.get('score')}")

            print(f"    · {tag}·{D.ARMY_CN[me]:<2s}  "
                  f"Py {dt_py:6.2f}s/{p_info.get('nodes', 0):>7d}节点/{p_info.get('plies'):>2}plies "
                  f"sc={p_info.get('score')!s:>7s}  {p_mv}   |   "
                  f"JIT {dt_jt:6.3f}s/{j_info.get('nodes', 0):>7d}节点/{j_info.get('plies'):>2}plies "
                  f"sc={j_info.get('score')!s:>7s}  {j_mv}   "
                  f"{'一致' if same else '<<< 不一致'}")

    print()
    print(f"  → 汇总：着法完全一致 {n_same}/{n_tot}")
    print(f"  → 总耗时：Python {t_py:.2f}s   JIT {t_jt:.2f}s   提速 {t_py / max(t_jt, 1e-6):.1f}x")
    print()
    print("=" * 78)
    print(f"结果：OK={OK}  FAIL={FAIL}")
    if FAILS:
        print("\n失败明细：")
        for m in FAILS:
            print("  x " + m)
    print("=" * 78)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
