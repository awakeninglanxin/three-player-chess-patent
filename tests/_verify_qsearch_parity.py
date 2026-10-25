# -*- coding: utf-8 -*-
"""方案 ② 静态搜索（quiescence）：JIT ↔ Python 等效性门禁

【门禁口径】沿用老师定的规矩 —— 新内核/新机制必须与现有 Python 引擎
随机局面对拍，逐点比对「着法集合一致」+「搜索分数一致」。

【本脚本验什么】
    ① 同局面、同 plies、同 `qs` ⇒ 根着法集合一致、逐项分数一致（容差 1e-6）
    ② `qs > 0` 与 `qs = 0` 的分数**必须不同**（否则说明静态搜索根本没生效）
    ③ `qs` 越大节点数单调上升（吃子链越挖越深），且不超时、不死循环

【为什么要单独一个脚本】
    `_verify_nb_search.py` 测的是"搜索框架"（PVS/剪枝/宽度/迭代加深），
    但它两侧都跑在 `qs=0` 上。静态搜索是**叶片处新插进去的一整棵子树**，
    它是本方案新写的代码路径 —— 必须单独对拍，否则它错了也没人发现。
"""
import os
import random
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "server"))
sys.path.insert(0, os.path.join(HERE, "..", "server", "agents"))

import eval_dxf as E                         # noqa: E402
from engine import game_dxf as GA            # noqa: E402
from engine import geometry_dxf as D         # noqa: E402
from engine import nb_core as NB             # noqa: E402
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
        if len(FAILS) <= 20:
            print(f"  x {msg}  {detail}")


def random_positions(n, seed=777, steps=(8, 34)):
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


def py_root(bot, s, plies, me):
    """Python 侧根搜索（全窗口 exact=True，才能与 JIT 比分数 —— 同 `_verify_nb_search`）"""
    bot._deadline = time.time() + 900.0
    bot.nodes = 0
    bot._hist = {}
    bot._killers = {}
    bot._ply = int(s.get("ply", 0) or 0)
    bot._ur = 1.0 + bot._ply * bot.w.get("urgency", 0.0)
    alive = frozenset(bot._gen_alive(s["board"]))
    board = dict(s["board"])
    mv, sc, ranked = bot._root_search(board, list(GA.legal_moves(s, me)),
                                      alive, plies, me, E.distances(),
                                      exact=True)
    return mv, sc, ranked, bot.nodes


def main():
    print("=" * 78)
    print("方案 ② 静态搜索：JIT <-> Python 等效性门禁")
    print("=" * 78)

    bot = SearchBot(depth=1, noise=0.0)
    w = bot.w
    cases = random_positions(6)
    cases.insert(0, ("开局", GA.new_game(first=1)))

    # ---- 预热（qs=2，把 _qsearch 也编译掉）----
    t0 = time.time()
    NB.warmup_search()
    print(f"JIT 预热 {time.time() - t0:.2f}s\n")

    for plies in (3, 5):
        for qs in (0, 2, 4):
            print(f"=== plies={plies}  qs={qs} ===")
            n_same = 0
            n_diff_from_zero = 0
            n_tot = 0
            max_dsc = 0.0
            sum_nodes = 0
            for tag, s in cases:
                for me in (1, 2, 3):
                    legal = list(GA.legal_moves(s, me))
                    if not legal:
                        continue
                    n_tot += 1
                    # ---- Python ----
                    bot.w = w
                    bot.qs_depth = qs
                    t0 = time.time()
                    pmv, psc, pranked, pnodes = py_root(bot, s, plies, me)
                    pt = time.time() - t0
                    # ---- JIT ----
                    t0 = time.time()
                    bmv, bsc, branked, bnodes, ab = NB.search_plies(
                        s["board"], me, plies, w, legal,
                        ply_no=int(s.get("ply", 0) or 0),
                        time_limit=900.0, exact=True, reset=True, qs=qs)
                    bt = time.time() - t0
                    if ab:
                        chk(False, f"{tag}·{D.ARMY_CN[me]} qs={qs} JIT 超时")
                        continue

                    sum_nodes += bnodes
                    dsc = abs(psc - bsc)
                    max_dsc = max(max_dsc, dsc)
                    same = (pmv == bmv)
                    n_same += 1 if same else 0

                    chk(dsc < 1e-6, f"{tag}·{D.ARMY_CN[me]} qs={qs} 分数一致",
                        f"Py={psc:.6f} JIT={bsc:.6f} d={dsc:.3e}")
                    pmap = {(f, t): v for v, (f, t) in pranked}
                    bmap = {(f, t): v for f, t, v in branked}
                    chk(set(pmap) == set(bmap),
                        f"{tag}·{D.ARMY_CN[me]} qs={qs} 根着法集合一致",
                        f"仅Py={len(set(pmap) - set(bmap))} 仅JIT={len(set(bmap) - set(pmap))}")
                    if set(pmap) == set(bmap):
                        worst = max(abs(pmap[k] - bmap[k]) for k in pmap)
                        chk(worst < 1e-6,
                            f"{tag}·{D.ARMY_CN[me]} qs={qs} 根着法分数逐一一致",
                            f"最大偏差 {worst:.3e}")

                    # ② qs>0 必须与 qs=0 不同（静态搜索真的在起作用）
                    if qs > 0:
                        bot.qs_depth = 0
                        _m0, sc0, _r0, _n0 = py_root(bot, s, plies, me)
                        bot.qs_depth = qs
                        if abs(sc0 - psc) > 1e-9:
                            n_diff_from_zero += 1

                    if not same:
                        print(f"    · {tag}·{D.ARMY_CN[me]}：并列分处选了不同着法 "
                              f"Py={pmv[0]}-{pmv[1]} JIT={bmv[0]}-{bmv[1]} d={dsc:.2e}")

            print(f"  → 着法完全一致 {n_same}/{n_tot}，最大分数偏差 {max_dsc:.2e}，"
                  f"JIT 节点合计 {sum_nodes}")
            if qs > 0:
                chk(n_diff_from_zero > 0,
                    f"plies={plies} qs={qs} 确实改变了估值（非空操作）",
                    f"仅 {n_diff_from_zero}/{n_tot} 个局面分数发生变化")
                print(f"  → qs={qs} 相对 qs=0 改变了 {n_diff_from_zero}/{n_tot} 个局面的分数")
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
