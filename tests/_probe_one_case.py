# -*- coding: utf-8 -*-
"""探针④：解剖 plies=1 那唯一一处失配（局4/16步·吴）

【为什么盯 plies=1】
    plies=1 时根分数 = **根着法走完后的纯 leaf 值**（`_search(plies=0) → _leaf`），
    中间没有任何搜索逻辑 —— 既没有剪枝、没有 PVS、没有宽度、没有历史表。
    ⇒ 这里出现的差异，只可能来自 `leaf` 或「走完那一步之后的盘面」。

    实测该局面 Δ=22.35（`_probe_width_off.py`）。

【做法】
    ① 两边各跑一次 plies=1（关宽度、关噪声），逐着法对照分数；
    ② 对**分数不同的那些着法**，手工把该步做在盘上，直接调
       `bot._leaf` 与 `NB.leaf_py`，看是不是 leaf 本身就差；
    ③ 若 leaf 一致，则问题在「走完之后 JIT 的 CODE 与 Python 的 board 不一致」
       ⇒ 打印两边的盘面做逐点对照（这才是真凶）。
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

BIG = 10 ** 6


def make_case():
    """复现 局4/16步（seed=777，i=3）"""
    rng = random.Random(777)
    for i in range(4):
        s = GA.new_game(first=1 + (i % 3))
        target = rng.randint(8, 34)
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
    return s, target


def board_str(board):
    return {p: (pc["kind"], pc["army"], pc["home"], bool(pc.get("deputy")))
            for p, pc in board.items()}


def main():
    s, target = make_case()
    me = 2
    print(f"局面：局4/{target}步  me={D.ARMY_CN[me]}  ply={s.get('ply')}")
    legal = list(GA.legal_moves(s, me))
    print(f"根着法数 = {len(legal)}")

    import collections
    bot = SearchBot(depth=1, noise=0.0)
    bot.width = collections.defaultdict(lambda: BIG)
    bot.w = dict(SearchBot(depth=1, noise=0.0).w)
    w = bot.w
    bot._deadline = 1e18
    bot.nodes = 0
    bot._hist = {}
    bot._killers = {}
    bot._ply = int(s.get("ply", 0) or 0)
    bot._ur = 1.0 + bot._ply * bot.w.get("urgency", 0.0)
    alive = frozenset(bot._gen_alive(s["board"]))
    board = dict(s["board"])
    pmv, psc, pranked = bot._root_search(board, legal, alive, 1, me,
                                        E.distances(), exact=True)

    huge = np.full(NB.MAX_PLY + 1, BIG, dtype=np.int32)
    bmv, bsc, branked, bnodes, ab = NB.search_plies(
        s["board"], me, 1, w, legal, ply_no=bot._ply,
        time_limit=600.0, exact=True, reset=True, width=huge)

    print(f"\nPython best = {psc:.6f} ({pmv[0]}-{pmv[1]})")
    print(f"JIT    best = {bsc:.6f} ({bmv[0]}-{bmv[1]})")
    print(f"Δ = {abs(psc - bsc):.6f}")

    pmap = {(f, t): v for v, (f, t) in pranked}
    bmap = {(f, t): v for f, t, v in branked}
    print(f"\n根着法集合：Py {len(pmap)} / JIT {len(bmap)}  "
          f"仅Py={sorted(set(pmap) - set(bmap))} 仅JIT={sorted(set(bmap) - set(pmap))}")

    diffs = [(k, pmap[k], bmap[k]) for k in pmap if k in bmap
             and abs(pmap[k] - bmap[k]) > 1e-9]
    print(f"分数不同的着法：{len(diffs)} / {len(pmap)}")
    for k, pv, bv in sorted(diffs, key=lambda x: -abs(x[1] - x[2]))[:12]:
        print(f"   {k[0]}-{k[1]}   Py={pv:14.6f}  JIT={bv:14.6f}  Δ={pv - bv:+.6f}")

    # ---- 对差异着法直接做盘上，比 leaf ----
    print("\n" + "=" * 72)
    print("对差异着法直接比 leaf（走完之后）")
    print("=" * 72)
    dist = E.distances()
    for k, pv, bv in sorted(diffs, key=lambda x: -abs(x[1] - x[2]))[:6]:
        b2 = dict(s["board"])
        bot._make(b2, k[0], k[1])
        py = bot._leaf(dict(b2), me, dist)
        nb = NB.leaf_py(b2, me, w, ply=bot._ply)
        same_board = board_str(b2)
        print(f"   {k[0]}-{k[1]}  Py说={pv:.6f} JIT说={bv:.6f} | "
              f"直接 leaf: Py={py:.6f} JIT={nb:.6f} "
              f"{'（leaf 一致）' if abs(py - nb) < 1e-6 else '（★ leaf 就不一致）'}")

    # ---- 检查 JIT 内部：把 CODE 走一步后逐点对照 Python 盘面 ----
    print("\n" + "=" * 72)
    print("JIT 内部盘面 vs Python 盘面（对差异着法逐步走）")
    print("=" * 72)
    code = NB.encode_board(s["board"])
    dec0 = NB.decode_board(code)
    if board_str(dec0) != board_str(s["board"]):
        print("  ✗ 开局编码往返就不一致！")
    for k, pv, bv in sorted(diffs, key=lambda x: -abs(x[1] - x[2]))[:4]:
        code2 = NB.encode_board(s["board"])
        frm = NB.POS[k[0]]
        to = NB.POS[k[1]]
        vic = int(code2[to])
        code2[to] = code2[frm]
        code2[frm] = 0
        b2 = dict(s["board"])
        bot._make(b2, k[0], k[1])
        dec = NB.decode_board(code2)
        if board_str(dec) != board_str(b2):
            print(f"  ✗ {k[0]}-{k[1]} 走完之后盘面不一致！")
            only_py = {p: v for p, v in board_str(b2).items()
                       if board_str(dec).get(p) != v}
            print(f"      仅在 Python 侧不同/缺失：{only_py}")
        else:
            print(f"  ✓ {k[0]}-{k[1]} 走完盘面一致")

    print("\n" + "=" * 72)
    print("判读：")
    print("  · 若某个着法「直接 leaf」两边不一致 ⇒ 那是 leaf 的隐藏分支")
    print("  · 若「直接 leaf」都一致、但搜索报的分数不同 ⇒ 搜索那边算的不是这个 leaf")
    print("=" * 72)


if __name__ == "__main__":
    main()
