# -*- coding: utf-8 -*-
"""探针②：分歧到底来自「宽度截断」还是「叶评估 / 着法生成」？

【实验设计】
    把**两边**的宽度限制都设成无穷大（等价于纯 alpha-beta，不截断任何着法），
    再看分数：
      · 若一致到 1e-14  ⇒ 分歧**只**来自宽度截断路径（排序/历史/杀手在深层岔了）
      · 若仍差         ⇒ 分歧来自 leaf 或 gen_side（与宽度无关）

    这是二分法的第一刀 —— 把"搜索框架"与"树内截断"彻底切开。

补充：同样的对照在 **plies=1/2/3** 上跑一遍（层数越浅，越接近纯叶评估），
      用来看偏差是随层数**放大**（⇒ 截断累积）还是**恒定**（⇒ 单点系统偏差）。
"""
import collections
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


def run(pos_list, plies, width_on):
    # ⚠️ noise 必须关：默认 0.5 会让 Python 返回的 best_score 带 0~0.5 随机偏移
    #    （`_root_search`: `best_score = sc + rng.random()*noise`），
    #    污染分数比对。见 `_verify_nb_search.py` 同名注释。
    bot = SearchBot(depth=1, noise=0.0)
    w = bot.w
    if width_on:
        bot.width = dict(SearchBot(depth=1).width)
        wd = None
    else:
        bot.width = collections.defaultdict(lambda: BIG)
        wd = np.full(NB.MAX_PLY + 1, BIG, dtype=np.int32)
    worst = 0.0
    n_tot = 0
    n_set = 0
    details = []
    for tag, s in pos_list:
        for me in (1, 2, 3):
            legal = list(GA.legal_moves(s, me))
            if not legal:
                continue
            bot._deadline = 1e18
            bot.nodes = 0
            bot._hist = {}
            bot._killers = {}
            bot._ply = int(s.get("ply", 0) or 0)
            bot._ur = 1.0 + bot._ply * bot.w.get("urgency", 0.0)
            alive = frozenset(bot._gen_alive(s["board"]))
            board = dict(s["board"])
            _pmv, psc, pranked = bot._root_search(
                board, legal, alive, plies, me, E.distances(), exact=True)
            _bmv, bsc, branked, _bn, ab = NB.search_plies(
                s["board"], me, plies, w, legal,
                ply_no=int(s.get("ply", 0) or 0),
                time_limit=600.0, exact=True, reset=True, width=wd)
            if ab:
                continue
            n_tot += 1
            d = abs(psc - bsc)
            worst = max(worst, d)
            pmap = {(f, t): v for v, (f, t) in pranked}
            bmap = {(f, t): v for f, t, v in branked}
            if set(pmap) == set(bmap):
                n_set += 1
            if d > 1e-6:
                details.append(f"{tag}·{D.ARMY_CN[me]} Py={psc:.6f} JIT={bsc:.6f} Δ={d:.3e}")
    return worst, n_tot, n_set, details


def main():
    pos_list = random_positions(6)
    pos_list.insert(0, ("开局", GA.new_game(first=1)))

    # ⚠️ 关宽度时分支数 ~40/方 ⇒ 40^6 ≈ 4e9，plie=6 会跑到天荒地老。
    #    所以只在**浅层**比 —— 已经足够回答"不给截断会不会差"这个问题。
    print("=" * 76)
    print("关宽度（纯 alpha-beta，不截断任何着法）")
    print("=" * 76)
    for plies in (1, 2, 3, 4):
        worst, n, ns, det = run(pos_list, plies, width_on=False)
        print(f"  plies={plies}: 最大偏差 {worst:.3e}   "
              f"根着法集合一致 {ns}/{n}   超差项 {len(det)}")
        for d in det[:8]:
            print("     ✗ " + d)

    print()
    print("=" * 76)
    print("开宽度（正常口径）—— 对照组")
    print("=" * 76)
    for plies in (1, 2, 3, 4, 6):
        worst, n, ns, det = run(pos_list, plies, width_on=True)
        print(f"  plies={plies}: 最大偏差 {worst:.3e}   "
              f"根着法集合一致 {ns}/{n}   超差项 {len(det)}")

    print()
    print("=" * 76)
    print("判读：")
    print("  · 关宽度全 1e-14、开宽度才差 ⇒ 分歧在『深度 ≥ lim 时截掉谁』这一步")
    print("    （排序平局口径已排除 ⇒ 嫌疑指向 HIST/KILL 的**深层状态演化**）")
    print("  · 关宽度也差、且偏差随层数**不放大** ⇒ 单点系统偏差，查 leaf")
    print("=" * 76)


if __name__ == "__main__":
    main()
