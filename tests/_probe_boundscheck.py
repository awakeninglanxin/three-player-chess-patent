# -*- coding: utf-8 -*-
"""探针⑧：用 `NUMBA_BOUNDSCHECK=1` 抓越界 —— 诊断 SEGV 与深层分歧

【原理】
    numba 的 njit 默认 `boundscheck=False` —— 越界读写**不报错**，
    直接踩内存：轻则静默算出错值（"plies≤4 全对、plies≥6 才岔"），
    重则 SEGV（本探针系列已出现两次 Segmentation fault）。
    把 `NUMBA_BOUNDSCHECK=1` 打开，任何越界立刻抛 `IndexError` 并给出位置。

    用法（由命令行设置环境变量后运行本脚本）：
        set NUMBA_BOUNDSCHECK=1 && python tests/_probe_boundscheck.py

【本脚本做什么】
    跑一遍"会出问题"的负载：开局 + 若干随机局面，plies=6，逐方搜一次。
    另外把 leaf / gen_side / under_attack 也在随机局面上压一遍。
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


def main():
    print("NUMBA_BOUNDSCHECK =", os.environ.get("NUMBA_BOUNDSCHECK"))
    print("=" * 74)
    from search_bot import SearchBot
    bot = SearchBot(depth=1, noise=0.0)
    w = bot.w
    sc = NB._SEARCHSCR

    pos_list = [("开局", GA.new_game(first=1))] + random_positions(6)

    # ---- ① gen_side / gen_point / under_attack / leaf ----
    print("① 着法生成 / 攻击表 / 叶评估 压测")
    for tag, s in pos_list:
        board = s["board"]
        code = NB.encode_board(board)
        for a in (1, 2, 3):
            n = int(NB.gen_side(code, np.int32(a), sc.mvb, sc.stamp, sc.ctr))
            for i in range(n):
                NB.gen_point(code, np.int32(int(sc.mvb[i]) >> NB.SHIFT),
                             sc.out_mv, sc.stamp, sc.ctr)
            NB.leaf_py(board, a, w, ply=int(s.get("ply", 0) or 0))
        for t in D.BOARD.ids:
            for a in (1, 2, 3):
                NB.under_attack(code, np.int32(NB.POS[t]), np.int32(a))
        print(f"   · {tag} OK")

    # ---- ② 搜索（这正是 SEGV/分歧出现的地方）----
    print("② plies=6 搜索压测")
    for tag, s in pos_list:
        for me in (1, 2, 3):
            legal = list(GA.legal_moves(s, me))
            if not legal:
                continue
            NB.search_plies(s["board"], me, 6, w, legal,
                            ply_no=int(s.get("ply", 0) or 0),
                            time_limit=600.0, exact=True, reset=True)
        print(f"   · {tag} OK")

    # ---- ③ 状态累积路径（锁步场景，正是 SEGV 现场）----
    print("③ 状态累积路径（search_node reset=False × 根手数）")
    s = GA.new_game(first=1)
    for me in (1, 2, 3):
        legal = list(GA.legal_moves(s, me))
        sc.reset_tables()
        code0 = NB.encode_board(s["board"])
        mask = NB.alive_mask_py(s["board"])
        for i, (f, t) in enumerate(legal):
            sc.mvb[i] = (NB.POS[f] << NB.SHIFT) | NB.POS[t]
        NB._order(code0, sc.mvb, sc.scb, 0, len(legal), np.int32(me),
                  np.int32(6), sc.hist, sc.kill)
        nxt = NB.next_turn_py(mask, me)
        for i in range(len(legal)):
            f = NB.IDX2POS[int(sc.mvb[i]) >> NB.SHIFT]
            t = NB.IDX2POS[int(sc.mvb[i]) & 255]
            c = NB.encode_board(s["board"])
            fi, ti = NB.POS[f], NB.POS[t]
            c[ti] = c[fi]
            c[fi] = 0
            NB.search_node(s["board"], nxt, mask, 5, me, w, 1.0,
                           code=c, reset=False)
        print(f"   · 开局·{D.ARMY_CN[me]} OK")

    print()
    print("=" * 74)
    print("若无 IndexError ⇒ 至少这条路径上不存在越界下标")
    print("=" * 74)


if __name__ == "__main__":
    main()
