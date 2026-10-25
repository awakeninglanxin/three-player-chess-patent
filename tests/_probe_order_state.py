# -*- coding: utf-8 -*-
"""探针⑥：`_order` 在**非空历史/杀手状态**下是否还一致？

【为什么必须单测它】
    探针②只比了「根层、历史表与杀手表**全空**」的 `_order` —— 那次 0 处不同。
    但探针⑤（逐层下降）给出了决定性结论：
        从**空表**出发、全窗口下，子树值两边一致（说明节点值本身没错）；
        而 `_root_search` 报告的值却不同 ⇒ 差异是被**累积的历史/杀手状态**带出来的。
    历史/杀手表改变的是**排序**，排序改变**宽度截断**截掉谁，截断改变 minimax 值。
    ⇒ 嫌疑直指「非空状态下 `_order` 的分数赋值/平局口径」。

【怎么做】
    对若干局面 × 每个方 × 几百次随机试验：
      · 随机给一部分着法灌历史分（含封顶值 90000）
      · 随机指定 k1/k2（在着法集合里挑）
      · 随机取 plies（1..6）
    两边各排一次，**逐项比对**。
    这能把「分数档赋值」「KV 价值表」「平局口径」三件事一次全覆盖。
"""
import os
import random
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "server"))
sys.path.insert(0, os.path.join(HERE, "..", "server", "agents"))

from engine import game_dxf as GA             # noqa: E402
from engine import geometry_dxf as D          # noqa: E402
from engine import nb_core as NB              # noqa: E402
from engine import rules_dxf as R             # noqa: E402
from search_bot import SearchBot              # noqa: E402


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


def py_side_moves(board, army):
    out = []
    for pos, pc in board.items():
        if pc["army"] != army:
            continue
        for q in R.moves_of(board, pos, pc):
            out.append((pos, q))
    return out


def main():
    # ---- 先看 KV 表与 Python VALUE 是否一致（这个是静态检查，最便宜）----
    print("=" * 74)
    print("0. JIT KV 表 ↔ Python VALUE（捕食档位就靠它）")
    print("=" * 74)
    bad = 0
    for kind, pyv in R.VALUE.items():
        if kind == "general":
            continue
        jv = NB.KV[NB.KIND_ID[kind]]
        flag = "✓" if abs(pyv - jv) < 1e-12 else "✗"
        if flag == "✗":
            bad += 1
        print(f"  {flag} {kind:<10} Python={pyv}  JIT={jv}")
    print(f"  → {'全部一致' if not bad else f'{bad} 项不一致'}")

    # ---- 非空状态下的 _order ----
    print()
    print("=" * 74)
    print("1. 非空 HIST/KILL 下的 `_order` 逐项对照")
    print("=" * 74)
    pos_list = random_positions(6)
    pos_list.insert(0, ("开局", GA.new_game(first=1)))

    bot = SearchBot(depth=1, noise=0.0)
    sc = NB._SEARCHSCR
    rng = random.Random(4242)
    H_CHOICES = [0.0, 1.0, 4.0, 16.0, 36.0, 100.0, 90000.0]
    TRIALS = 300

    n_bad = 0
    n_tot = 0
    first = None
    for tag, s in pos_list:
        board = s["board"]
        code = NB.encode_board(board)
        for army in (1, 2, 3):
            moves = py_side_moves(board, army)
            if not moves:
                continue
            jit_n = int(NB.gen_side(code, np.int32(army), sc.mvb, sc.stamp, sc.ctr))
            jit_moves = [(NB.IDX2POS[int(sc.mvb[i]) >> 8],
                          NB.IDX2POS[int(sc.mvb[i]) & 255])
                         for i in range(jit_n)]
            if set(moves) != set(jit_moves):
                print(f"  ✗ {tag}·{D.ARMY_CN[army]} 着法集合不一致（前置条件失败）")
                n_bad += 1
                continue
            mlist = list(moves)
            for _ in range(TRIALS):
                n_tot += 1
                plies = rng.randint(1, 6)
                hist = {}
                for mv in mlist:
                    if rng.random() < 0.35:
                        hist[mv] = rng.choice(H_CHOICES)
                k = []
                for _i in range(rng.randint(0, 2)):
                    k.append(rng.choice(mlist))
                bot._hist = dict(hist)
                bot._killers = {plies: list(k)} if k else {}
                pyr = bot._order(board, mlist, army, plies)
                # JIT
                sc.hist[:] = 0.0
                for mv, h in hist.items():
                    sc.hist[(NB.POS[mv[0]] << 8) | NB.POS[mv[1]]] = h
                sc.kill[:] = 0
                if k:
                    sc.kill[plies * 2] = (NB.POS[k[0][0]] << 8) | NB.POS[k[0][1]]
                if len(k) > 1:
                    sc.kill[plies * 2 + 1] = (NB.POS[k[1][0]] << 8) | NB.POS[k[1][1]]
                # 重新填 MVB（上一次 _order 已把它排过序 ⇒ 必须还原原始生成顺序）
                jit_n2 = int(NB.gen_side(code, np.int32(army), sc.mvb,
                                         sc.stamp, sc.ctr))
                NB._order(code, sc.mvb, sc.scb, 0, jit_n2, np.int32(army),
                          np.int32(plies), sc.hist, sc.kill)
                jitr = [(NB.IDX2POS[int(sc.mvb[i]) >> 8],
                         NB.IDX2POS[int(sc.mvb[i]) & 255]) for i in range(jit_n2)]
                if pyr != jitr:
                    n_bad += 1
                    if first is None:
                        i = next(i for i in range(min(len(pyr), len(jitr)))
                                 if pyr[i] != jitr[i])
                        first = (tag, army, plies, i, pyr[i], jitr[i],
                                 pyr[:6], jitr[:6])
    print(f"  → 共 {n_tot} 次随机试验，不一致 {n_bad} 次")
    if first:
        tag, army, plies, i, a, b, pa, ja = first
        print(f"  首个不一致：{tag}·{D.ARMY_CN[army]} plies={plies} 第{i}位 "
              f"Py={a} JIT={b}")
        print(f"    Py 前6: {pa}")
        print(f"    JIT前6: {ja}")

    print()
    print("=" * 74)
    print("判读：")
    print("  · 全 0 ⇒ `_order` 在任意状态下都一致 ⇒ 状态漂移另有原因"
          "（或纯属『截断本身对顺序极敏感』）")
    print("  · 有 >0 ⇒ 就是这里，按首个不一致的例子改 JIT")
    print("=" * 74)


if __name__ == "__main__":
    main()
