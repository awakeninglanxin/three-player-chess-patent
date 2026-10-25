# -*- coding: utf-8 -*-
"""自我对弈 · 权重进化（"无为法"的工程实现）

【借鉴 AlphaZero 什么】
    AlphaZero 的"无为"在于：**不告诉程序什么是好棋**。
    它只做两件事 —— 自己跟自己下、用胜负结果反过来修正决策。
    棋理不是人写进去的，是从对局里长出来的。

    Pikafish（象棋版 Stockfish）背后的 Pika Xiangqi Zero 用的也是同一套：
    神经网络的数据全部来自自我对弈，而不是人类棋谱。

【本文件怎么落地 —— CEM（交叉熵法）】
    完整 AlphaZero 需要 神经网络 + MCTS + 数百万局，跑不起。
    但它的**方法论**可以移植：

      ① 采样：围绕当前最优权重加高斯噪声，生成一批候选
      ② 自我对弈：每个候选权重各跑若干局（三方都用它，局面天然对称）
      ③ 用**对局结果**打分：斩帅 >> 吃子 > 交火时间（不看人写的棋理）
      ④ 保留前 20% 作为新中心，收窄噪声，回到 ①

    这就是"让对局结果自己把权重推到该去的地方"。

【诚实说明 —— 这不是完整的 AlphaZero】
    真正的 AlphaZero 会用搜索的着法分布训练一个策略网络，
    本文件调的是**手工评估函数的权重**（维度只有 10 个）。
    但"不预设棋理、只让结果说话"这一层，是同构的。

【借鉴 Pikafish/Fishtest 的地方】
    Fishtest 用大规模自对弈 + 统计检验（SPRT）来判断一个改动
    是否真的提升棋力。本文件同样不靠"作者觉得好"，
    而是**每代都真跑对局、用数字排名**。

用法：
    python agents/selfplay.py                 # 默认 4 代 × 8 候选 × 2 局
    python agents/selfplay.py 6 12 3          # 代数 候选数 每候选局数
    python agents/selfplay.py 6 12 3 --save   # 并把最优权重写入 weights.json
"""
import copy
import json
import os
import random
import sys
import time

try:
    from ..engine import game_dxf as GA
    from ..engine import geometry_dxf as G
    from . import eval_dxf as E
    from .search_bot import SearchBot, WEIGHTS_FILE
except ImportError:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from engine import game_dxf as GA
    from engine import geometry_dxf as G
    import eval_dxf as E
    from search_bot import SearchBot, WEIGHTS_FILE

ARMY = G.ARMY_CN

# 可进化的权重（其余固定 —— 它们是量纲锚点，跟着一起漂会失控）
TUNE = ("pressure", "danger", "urgency", "material", "close1", "close2", "check")

# 每个参数的搜索步长（按各自量级设定）
STD0 = {
    "pressure": 0.08, "danger": 0.03, "urgency": 0.02,
    "material": 0.05, "close1": 80.0, "close2": 20.0, "check": 40.0,
}
# 参数的有效下界（不允许跑成负数）
FLOOR = {k: 0.0 for k in TUNE}


def _push_depth(s):
    """对局结束时，三方各自对敌帅的进攻压强之和 —— 衡量"推进到了多深"

    为什么需要这一项：僵持局面下「吃子/斩帅/跨界」全是 0，
    适应度失去区分度（实测所有候选都是 0 分并列）。
    而"离敌帅多近"即使一子未吃也在持续变化，
    于是它成了僵局阶段唯一能分辨优劣的梯度 —— 这正是我们从
    "不预设棋理、只让结果说话"里能提取到的最细信号。
    """
    if not s["board"]:
        return 0.0
    gens, _dep, pieces, _mat = E._split(s)
    dist = E.distances()
    tot = 0.0
    for a in (1, 2, 3):
        for enemy, gpos in gens.items():
            if enemy == a:
                continue
            tot += E.pressure_of(pieces.get(a, []), gpos, dist)
    return tot


def battle_score(s, kills, slain, cross):
    """用**对局结果**给权重打分 —— 不看人写的棋理

    老师的硬要求是「必须打到只剩一方的将」，所以斩帅权重最高；
    其次是吃子（真的交火了）与跨界（子敢过界）；
    再次是子力损失（战斗激烈）；
    最后是推进深度（僵局时唯一还有区分度的信号）。
    """
    sc = 0.0
    sc += len(slain) * 1000.0            # 斩帅
    if s["winner"]:
        sc += 600.0                      # 终局只剩一将：最高荣誉
    sc += kills * 25.0                   # 吃子
    sc += cross * 3.0                    # 跨界
    sc += (48 - len(s["board"])) * 8.0   # 子力损失
    sc += _push_depth(s) * 0.6           # 推进深度（僵局阶段的梯度）
    return sc


def play_one(w, maxply, tl, seed):
    """用权重 w 跑一局（三方同一套权重 —— 保持公平与对称）"""
    s = GA.new_game()
    bots = {k: SearchBot(depth=1, time_limit=tl, seed=seed * 17 + k, weights=w)
            for k in (1, 2, 3)}
    kills = cross = 0
    slain = []
    for _ in range(maxply):
        if s["winner"]:
            break
        cur = s["turn"]
        legal = GA.legal_moves(s, cur)
        if not legal:
            GA._advance(s)
            continue
        r = bots[cur].choose(s, legal, "", ARMY[cur])
        mv = r.get("move")
        if not mv or tuple(mv.split("-")) not in legal:
            mv = f"{legal[0][0]}-{legal[0][1]}"
        f, t = mv.split("-")
        if G.parse(f)[0] != G.parse(t)[0]:
            cross += 1
        note = GA.apply(s, f, t)
        if note.get("captured"):
            kills += 1
        if note.get("eliminated"):
            slain.append((s["ply"], note["army"], note["eliminated"]))
    return s, kills, slain, cross


def evaluate(w, games, maxply, tl, seed0):
    """一个权重候选的适应度 = 若干局的平均分"""
    tot = 0.0
    detail = []
    for g in range(games):
        s, kills, slain, cross = play_one(w, maxply, tl, seed0 + g)
        sc = battle_score(s, kills, slain, cross)
        tot += sc
        detail.append((s["ply"], kills, len(slain), cross, len(s["board"])))
    return tot / games, detail


def cem(generations=4, pop=8, games=2, maxply=120, tl=0.10,
        save=False, seed=20260923, verbose=True):
    """交叉熵法：采样 → 自对弈 → 保留优者 → 收窄噪声 → 迭代"""
    rng = random.Random(seed)
    mean = {k: float(E.DEFAULT_W[k]) for k in TUNE}
    std = dict(STD0)
    best = (None, -1e18, dict(mean))

    if verbose:
        print("=" * 86)
        print("自我对弈 · 权重进化（CEM）—— 不预设棋理，只让对局结果说话")
        print(f"  代 {generations} × 候选 {pop} × 每候选 {games} 局 × 上限 {maxply} 手")
        print("=" * 86)

    for gen in range(1, generations + 1):
        t0 = time.time()
        cands = []
        for i in range(pop):
            if i == 0:
                w = dict(mean)                       # 第 0 号永远保留当前中心
            else:
                w = {k: max(FLOOR[k], mean[k] + rng.gauss(0, std[k])) for k in TUNE}
            cands.append(w)
        results = []
        for i, w in enumerate(cands):
            full = dict(E.DEFAULT_W)
            full.update(w)
            fit, detail = evaluate(full, games, maxply, tl, seed0=seed + gen * 100 + i)
            results.append((fit, w, detail))
        results.sort(key=lambda x: -x[0])

        # 保留前 20% 作为新的中心
        elite_n = max(1, pop // 5)
        elites = [w for _, w, _ in results[:elite_n]]
        for k in TUNE:
            vals = [w[k] for w in elites]
            mean[k] = sum(vals) / len(vals)
        # 收窄噪声（后期精调）
        for k in TUNE:
            std[k] = max(STD0[k] * 0.35, std[k] * 0.72)

        f0, w0, d0 = results[0]
        if f0 > best[1]:
            best = (gen, f0, dict(mean))
        if verbose:
            print(f"\n第 {gen} 代（{time.time()-t0:.0f}s）")
            print(f"  最优适应度 {f0:8.1f}   "
                  f"（手数/吃子/斩帅/跨界/剩余子 = {d0[0]}）")
            print("  权重中心: " + "  ".join(f"{k}={mean[k]:.3f}" for k in TUNE))

    return best, mean


def main():
    argv = [a for a in sys.argv[1:] if not a.startswith("--")]
    save = "--save" in sys.argv
    gens = int(argv[0]) if len(argv) > 0 else 4
    pop = int(argv[1]) if len(argv) > 1 else 8
    games = int(argv[2]) if len(argv) > 2 else 2

    best, mean = cem(generations=gens, pop=pop, games=games, save=save)
    gen, fit, w = best
    print()
    print("=" * 86)
    print(f"进化结束：第 {gen} 代出现最优适应度 {fit:.1f}")
    print("最优权重：")
    for k in TUNE:
        mark = "  ← 改动" if abs(w[k] - E.DEFAULT_W[k]) > 1e-6 else ""
        print(f"    {k:<10s} {E.DEFAULT_W[k]:>8.3f}  →  {w[k]:>8.3f}{mark}")
    if save:
        data = {"weights": w, "meta": {
            "source": "selfplay CEM", "generation": gen, "fitness": fit,
            "time": time.strftime("%Y-%m-%d %H:%M:%S")}}
        with open(WEIGHTS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"\n已写入 {WEIGHTS_FILE}   （SearchBot 下次启动自动加载）")
    else:
        print("\n（加 --save 才会写入 weights.json）")
    return w


if __name__ == "__main__":
    main()
