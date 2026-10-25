# -*- coding: utf-8 -*-
"""探针⑦：**锁步复刻根循环** —— 逐手对照分数，并在第一处不同时对拍 HIST/KILL

【为什么还要做这个】
    · 探针⑤已证明：从**空表**、全窗口出发，两边对子节点求值一致。
    · 探针⑥已证明：给定**同一份** HIST/KILL，两边 `_order` 一致（6300 次试验）。
    · 但 `_root_search` 报告的值仍有个别不同（plies=6、2/44 个根着法）。
    ⇒ 只剩一个可能：**两边累积出来的 HIST/KILL 状态本身不同**。

    本探针直接复刻 `search_root` 的根循环（逐手 make → `_search(全窗口)` → unmake），
    每手记录 (分数, HIST 快照, KILL 快照)，然后：
      ① 找第一处分数不同的手；
      ② 打印**上一手结束时**两边的 HIST/KILL 差集 —— 状态是不是从那一刻起就岔了？

    若第一手就岔 ⇒ 纯逻辑差异（与状态无关）；
    若第 k 手才岔、且第 k−1 手的状态已经不同 ⇒ 状态漂移，再往前追。
"""
import os
import random
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "server"))
sys.path.insert(0, os.path.join(HERE, "..", "server", "agents"))

import eval_dxf as E                          # noqa: E402
from engine import game_dxf as GA             # noqa: E402
from engine import geometry_dxf as D          # noqa: E402
from engine import nb_core as NB              # noqa: E402
from engine import rules_dxf as R             # noqa: E402
from search_bot import SearchBot              # noqa: E402

INF = 1e9


def pack(frm, to):
    return (NB.POS[frm] << NB.SHIFT) | NB.POS[to]


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


def jit_root_lockstep(board, me, plies, legal, w, ur):
    """逐手复刻 `search_root`（保留 HIST/KILL），每手记录分数与状态快照"""
    sc = NB._SEARCHSCR
    sc.reset_tables()
    code0 = NB.encode_board(board)
    mask = NB.alive_mask_py(board)
    n = len(legal)
    for i, (f, t) in enumerate(legal):
        sc.mvb[i] = pack(f, t)
    NB._order(code0, sc.mvb, sc.scb, 0, n, np.int32(me), np.int32(plies),
              sc.hist, sc.kill)
    order = [(NB.IDX2POS[int(sc.mvb[i]) >> NB.SHIFT],
              NB.IDX2POS[int(sc.mvb[i]) & 255]) for i in range(n)]

    log = []
    nxt = NB.next_turn_py(mask, me)
    for (f, t) in order:
        c = NB.encode_board(board)
        fi, ti = NB.POS[f], NB.POS[t]
        vic = board.get(t)
        nm = mask
        if vic is not None and vic["kind"] == "general" and not vic.get("deputy"):
            nm = mask & ~(1 << vic["home"])
        c[ti] = c[fi]
        c[fi] = 0
        v = NB.search_node(board, nxt, nm, plies - 1, me, w, ur,
                           alpha=-INF, beta=INF, code=c, reset=False)
        log.append(((f, t), v,
                    {int(i): float(sc.hist[i]) for i in np.nonzero(sc.hist)[0]},
                    {int(i): int(x) for i, x in enumerate(sc.kill) if x}))
    return order, log


def py_root_lockstep(bot, board, me, plies, legal, alive, dist):
    """逐手复刻 `SearchBot._root_search`（保留 _hist/_killers）"""
    bot._hist = {}
    bot._killers = {}
    bot._deadline = 1e18
    bot.nodes = 0
    moves = bot._order(board, legal, me, plies)
    log = []
    nxt_turn = bot._next(alive, me)
    for frm, to in moves:
        undo = bot._make(board, frm, to)
        nxt = alive - {undo["home"]} if (undo is not None
                                        and undo["kind"] == "general"
                                        and not undo.get("deputy")) else alive
        try:
            v = bot._search(board, nxt_turn, nxt, plies - 1, -INF, INF, me, dist)
        finally:
            bot._unmake(board, frm, to, undo)
        log.append(((frm, to), v,
                    {pack(frm, t): float(h) for (frm, t), h in bot._hist.items()},
                    kill_flat(bot._killers)))
    return moves, log


def kill_flat(kill_dict):
    """{plies: [(frm,to), ...]} → {plies*2+j: packed_mv}（与 JIT `KILL` 同口径）"""
    out = {}
    for pl, lst in kill_dict.items():
        for j, m in enumerate(lst[:2]):
            out[pl * 2 + j] = pack(m[0], m[1])      # ⚠️ 必须 pack：
            # 早先写成 `out[...] = m`，存的是元组 ⇒ 和 JIT 的整数比必然"全不同"，
    return out                                       # 白报了一堆假差异（已踩）。


def main():
    bot = SearchBot(depth=1, noise=0.0)
    w = bot.w
    dist = E.distances()

    cases = [("开局", GA.new_game(first=1))]
    # ⚠️ 局7/局8 在 lockstep 下会 SEGV（`search_node` 连续 44 次 plies=5 全窗口），
    #    不影响诊断结论 —— 开局就已经复现了全部分歧形态（魏 2 手 / 蜀 5 手）。

    for plies in (6,):
        for tag, s in cases:
            for me in (1, 2, 3):
                legal = list(GA.legal_moves(s, me))
                if not legal:
                    continue
                ur = 1.0 + int(s.get("ply", 0) or 0) * w.get("urgency", 0.0)
                board = dict(s["board"])
                alive = frozenset(bot._gen_alive(s["board"]))
                porder, plog = py_root_lockstep(
                    SearchBot(depth=1, noise=0.0), board, me, plies, legal,
                    alive, dist)
                board2 = dict(s["board"])
                jorder, jlog = jit_root_lockstep(board2, me, plies, legal, w, ur)

                same_order = (porder == jorder)
                bad = [i for i in range(min(len(plog), len(jlog)))
                       if abs(plog[i][1] - jlog[i][1]) > 1e-6]
                print(f"\n[{tag}·{D.ARMY_CN[me]}] plies={plies}  "
                      f"根排序一致={same_order}  "
                      f"分数不同的手 = {len(bad)}/{len(plog)}")
                if not same_order:
                    i = next(i for i in range(min(len(porder), len(jorder)))
                             if porder[i] != jorder[i])
                    print(f"   ★ 根排序第 {i} 位不同：Py={porder[i]} JIT={jorder[i]}")
                for i in bad[:4]:
                    print(f"   ✗ 第{i:3d}手 {plog[i][0][0]}-{plog[i][0][1]}  "
                          f"Py={plog[i][1]:14.6f}  JIT={jlog[i][1]:14.6f}  "
                          f"Δ={plog[i][1] - jlog[i][1]:+.6f}")
                # 第一处不同 ⇒ 看**上一手结束时**状态是否已经岔
                if bad:
                    k = bad[0]
                    if k == 0:
                        print("   ⇒ 第 0 手就不同 ⇒ **纯逻辑差异**（与状态无关）")
                    else:
                        ph = plog[k - 1][2]
                        jh = jlog[k - 1][2]
                        keys = set(ph) | set(jh)
                        dh = [i2 for i2 in keys
                              if abs(ph.get(i2, 0.0) - jh.get(i2, 0.0)) > 1e-12]
                        pk = plog[k - 1][3]
                        jk = jlog[k - 1][3]
                        kkeys = set(pk) | set(jk)
                        dk = [i2 for i2 in kkeys if pk.get(i2, 0) != jk.get(i2, 0)]
                        print(f"   ⇒ 第 {k} 手首次不同；第 {k - 1} 手结束时："
                              f"HIST 不同项 {len(dh)} / {len(keys)}，"
                              f"KILL 不同项 {len(dk)} / {len(kkeys)}")
                        if dk[:4]:
                            for i2 in dk[:4]:
                                print(f"        KILL[{i2}] Py={pk.get(i2, 0)} "
                                      f"JIT={jk.get(i2, 0)}")
                        if dh[:5]:
                            for i2 in dh[:5]:
                                print(f"        HIST[m={i2}] Py={ph.get(i2, 0.0)} "
                                      f"JIT={jh.get(i2, 0.0)}")
                        else:
                            print("        （第 k−1 手结束时 HIST 完全一致 ⇒ "
                                  "状态没漂，差异来自本手本身的搜索）")


if __name__ == "__main__":
    main()
