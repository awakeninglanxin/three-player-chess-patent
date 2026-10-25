# -*- coding: utf-8 -*-
"""JIT 搜索 ↔ Python 搜索 等效性 + 性能（方案 ① 第二段门禁）

【为什么不能只对拍「着法生成」】
    着法集合一致只证明「规则没抄错」，不证明「搜索没抄错」。
    搜索里还有 PVS 窗口、剪枝、历史/杀手、宽度限制、迭代加深 ——
    任何一处抄错都会让 bot 变傻（而不是变错），规则测试完全抓不到。

【怎么验】
    同一局面、同一 plies、同一权重，两边各搜一次：
      · `best_score` 差异 → 必须极小（浮点求和顺序不同，末位 ~1e-12 允许）
      · `best_move`       → 允许「并列分」处不同（镜像局面常见），但要报一致率
      · 根着法排名榜单     → 分数逐项比对（容差内）
    如果 best_score 差很多 ⇒ 剪枝/PVS 有 bug（不是浮点问题）。
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
            print(f"  ✗ {msg}  {detail}")


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
    """直接调 Python 版的根搜索（绕过 `_choose` 的迭代加深/时间预算）

    ⚠️ **必须 exact=True（全窗口）才能与 JIT 比分数**：
       `exact=False` 时根着法用 (alpha, INF) 窗口，alpha 是**累计**的，
       没超过 alpha 的着法返回的是**上界不是精确值**；而 alpha 又依赖剪枝路径，
       两边路径不可能逐节点相同 ⇒ 上界天然不同（实测差 0.27，纯属口径差异）。
       全窗口下每个根着法都是精确评估，两边必须一致。
    """
    bot._deadline = time.time() + 600.0
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
    print("=" * 72)
    print("JIT 搜索 ↔ Python 搜索 等效性（方案 ① 第二段门禁）")
    print("=" * 72)

    bot = SearchBot(depth=1)
    w = bot.w

    sec_positions = random_positions(8)
    sec_positions.insert(0, ("开局", GA.new_game(first=1)))

    for plies in (3, 6):
        print(f"\n=== plies = {plies} ===")
        n_same = 0
        n_tot = 0
        max_dsc = 0.0
        for tag, s in sec_positions:
            for me in (1, 2, 3):
                legal = list(GA.legal_moves(s, me))
                if not legal:
                    continue
                # ---- Python 版 ----
                bot.w = w
                t0 = time.time()
                pmv, psc, pranked, pnodes = py_root(bot, s, plies, me)
                pt = time.time() - t0
                # ---- JIT 版 ----
                # ⚠️ reset=True：历史/杀手表必须与 Python 侧一样**每次从空开始**。
                #    否则上一局的脏排序会改变宽度截断的位置 → 结果发散。
                t0 = time.time()
                bmv, bsc, branked, bnodes, ab = NB.search_plies(
                    s["board"], me, plies, w, legal,
                    ply_no=int(s.get("ply", 0) or 0),
                    time_limit=600.0, exact=True, reset=True)
                bt = time.time() - t0
                if ab:
                    chk(False, f"{tag}·{D.ARMY_CN[me]} JIT 意外超时")
                    continue

                n_tot += 1
                dsc = abs(psc - bsc)
                max_dsc = max(max_dsc, dsc)
                same = (pmv == bmv)
                n_same += 1 if same else 0
                # 分数必须几乎相等（浮点末位差异允许）；偏差大 = 剪枝抄错
                chk(dsc < 1e-6, f"{tag}·{D.ARMY_CN[me]} 分数一致",
                    f"Python={psc:.6f} JIT={bsc:.6f} Δ={dsc:.3e}")
                # 根着法榜单：分数集合应一致
                pmap = {(f, t): sc for sc, (f, t) in pranked}
                bmap = {(f, t): sc for f, t, sc in branked}
                chk(set(pmap) == set(bmap), f"{tag}·{D.ARMY_CN[me]} 根着法集合一致",
                    f"仅Python={len(set(pmap) - set(bmap))} 仅JIT={len(set(bmap) - set(pmap))}")
                if set(pmap) == set(bmap):
                    worst = max(abs(pmap[k] - bmap[k]) for k in pmap)
                    chk(worst < 1e-6, f"{tag}·{D.ARMY_CN[me]} 根着法分数逐一一致",
                        f"最大偏差 {worst:.3e}")
                if not same:
                    print(f"    · {tag}·{D.ARMY_CN[me]}：并列分处选了不同着法 "
                          f"Python={pmv[0]}-{pmv[1]} JIT={bmv[0]}-{bmv[1]}"
                          f"（Δscore={dsc:.2e}）")
                # 速度
                print(f"    · {tag}·{D.ARMY_CN[me]}  plies={plies}  "
                      f"Py {pt:6.2f}s/{pnodes:>7d}节点  "
                      f"JIT {bt:6.3f}s/{bnodes:>7d}节点  "
                      f"提速 {pt / max(bt, 1e-6):6.1f}×")
        print(f"  → plies={plies} 汇总：着法完全一致 {n_same}/{n_tot}，"
              f"最大分数偏差 {max_dsc:.2e}")

    print()
    print("=" * 72)
    print(f"结果：OK={OK}  FAIL={FAIL}")
    if FAILS:
        print("\n失败明细：")
        for m in FAILS:
            print("  ✗ " + m)
    print("=" * 72)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
