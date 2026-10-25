# -*- coding: utf-8 -*-
"""探针⑨：状态快照对照 —— 只用**已验证的入口**（`search_plies` / `_root_search`）

【动机】
    探针⑦（锁步）能给出结论但会踩 numba 的递归入口坑（SEGV）。
    其实只要把**根着法列表截断成前 k 个**，调一次 `search_plies(reset=True)`
    就等价于"跑完前 k 手之后的状态" —— 全程走的是生产代码路径，稳。
    再和 Python 的 `_root_search(root=list[:k])` 比 HIST/KILL 快照。

【为什么盯这个】
    探针⑦已给出关键事实（开局·蜀）：
        第 2 手分数首次不同，而**第 1 手结束时 HIST 完全一致**。
    两个可能：
      A) KILL 表在第 1 手结束时已分岔（探针⑦的 KILL 比对当时有显示 bug，未证）
      B) 状态确实一致，分歧来自搜索本身
    本探针把 A/B 一次判死：逐 k 比对 HIST 与 KILL。
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
from search_bot import SearchBot              # noqa: E402


def pack(frm, to):
    return (NB.POS[frm] << NB.SHIFT) | NB.POS[to]


def py_state(bot, board, me, plies, root, alive, dist):
    bot._hist = {}
    bot._killers = {}
    bot._deadline = 1e18
    bot.nodes = 0
    bot._root_search(dict(board), list(root), alive, plies, me, dist, exact=True)
    hist = {pack(f, t): float(h) for (f, t), h in bot._hist.items()}
    kill = {}
    for pl, lst in bot._killers.items():
        for j, m in enumerate(lst[:2]):
            kill[pl * 2 + j] = pack(m[0], m[1])
    return hist, kill


def jit_state(board, me, plies, root, w, ur):
    NB._SEARCHSCR.reset_tables()
    NB.search_plies(board, me, plies, w, list(root),
                    ply_no=int(ur[1]), time_limit=600.0, exact=True, reset=True)
    sc = NB._SEARCHSCR
    hist = {int(i): float(sc.hist[i]) for i in np.nonzero(sc.hist)[0]}
    kill = {int(i): int(x) for i, x in enumerate(sc.kill) if x}
    return hist, kill


def jit_root_order_only(board, me, plies, legal):
    """只做根排序（**先清表**，否则上一次搜索留下的 HIST/KILL 会污染排序）"""
    sc = NB._SEARCHSCR
    sc.reset_tables()
    code = NB.encode_board(board)
    for i, (f, t) in enumerate(legal):
        sc.mvb[i] = pack(f, t)
    NB._order(code, sc.mvb, sc.scb, 0, len(legal), np.int32(me),
              np.int32(plies), sc.hist, sc.kill)
    return [(NB.IDX2POS[int(sc.mvb[i]) >> NB.SHIFT],
             NB.IDX2POS[int(sc.mvb[i]) & 255]) for i in range(len(legal))]


def main():
    bot0 = SearchBot(depth=1, noise=0.0)
    w = bot0.w
    dist = E.distances()

    cases = [("开局", GA.new_game(first=1))]
    for i in (0,):
        rng = random.Random(777)
        for _j in range(i + 1):
            s = GA.new_game(first=1 + (_j % 3))
            target = rng.randint(8, 34)
            for _ in range(target):
                lm = GA.legal_moves(s, s["turn"])
                if not lm:
                    break
                fr, to = rng.choice(lm)
                try:
                    GA.apply(s, fr, to)
                except Exception:
                    break
                if GA.status(s).get("winner"):
                    break
        cases.append((f"局{i + 1}/{target}步", s))

    print("=" * 76)
    print("第一段：**只跑第 1 手**，逐层找最小的出问题层数（二分）")
    print("=" * 76)
    for tag, s in cases:
        for me in (1, 2, 3):
            legal = list(GA.legal_moves(s, me))
            if not legal:
                continue
            ply = int(s.get("ply", 0) or 0)
            bot = SearchBot(depth=1, noise=0.0)
            bot._ply = ply
            bot._ur = 1.0 + ply * w.get("urgency", 0.0)
            alive = frozenset(bot._gen_alive(s["board"]))
            for plies in (2, 3, 4, 5, 6):
                bot._hist = {}
                bot._killers = {}
                porder = bot._order(dict(s["board"]), legal, me, plies)
                jorder = jit_root_order_only(s["board"], me, plies, legal)
                if porder != jorder:
                    print(f"  [{tag}·{D.ARMY_CN[me]} plies={plies}] "
                          f"根排序不一致（探针前提失败）")
                    continue
                root1 = porder[:1]
                ph, pk = py_state(bot, s["board"], me, plies, root1, alive, dist)
                jh, jk = jit_state(s["board"], me, plies, root1, w, (bot._ur, ply))
                keys = set(ph) | set(jh)
                kkeys = set(pk) | set(jk)
                dh = [i2 for i2 in keys
                      if abs(ph.get(i2, 0.0) - jh.get(i2, 0.0)) > 1e-12]
                dk = [i2 for i2 in kkeys if pk.get(i2, 0) != jk.get(i2, 0)]
                flag = "✓" if (not dh and not dk) else "✗"
                print(f"  {flag} [{tag}·{D.ARMY_CN[me]}] plies={plies}  "
                      f"跑完第 1 手（{root1[0][0]}-{root1[0][1]}）："
                      f"HIST 不同 {len(dh)}/{len(keys)}  KILL 不同 {len(dk)}/{len(kkeys)}")
                if dh or dk:
                    for i2 in dh[:3]:
                        print(f"        HIST[m={i2}] Py={ph.get(i2, 0.0)} "
                              f"JIT={jh.get(i2, 0.0)}  "
                              f"moves {NB.IDX2POS[i2 >> NB.SHIFT]}-"
                              f"{NB.IDX2POS[i2 & 255]}")
                    for i2 in dk[:3]:
                        print(f"        KILL[{i2}] Py={pk.get(i2, 0)} "
                              f"JIT={jk.get(i2, 0)}")
                    break

    print()
    print("=" * 76)


if __name__ == "__main__":
    main()
