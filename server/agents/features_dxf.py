# -*- coding: utf-8 -*-
"""三人象棋 · 局面特征提取（AlphaZero 化第一步）

【为什么要这个文件 —— 老师 2026-10-01 的决定】
    「我建议用 alphazero 的算法，不用这种旧的估值权重」

AlphaZero 的 value head 不是"更聪明的算术"，而是**特征 → 胜率**的映射。
所以把旧的手调权重换掉，第一步不是写 MCTS，而是**把特征补齐**。

【★ 关键诊断：旧估值函数的致命缺口】
    看 `eval_dxf.evaluate()` 的全部计分项：
        pressure / danger / urgency / material / check / close1 / close2
        / mobility / deputy / gen_lost
    —— **没有任何一项能表达「我的子正被白吃」。**
    · pressure 用的是 sqrt(子力) 加权（作者注释：怕"车换兵被判灾难"）
    · material 权重只有 0.10，且只跟**最强的那个对手**比
    所以"魏车让开、马被炮白打"在这套式子里**分数不动**（实测：送马边际 +0.91 > 丢马 −0.40）。

    ★ 换成 AlphaZero 也救不了 —— 如果**输入里没有这个信号**，
      网络要么学不出来，要么得烧掉几百万局 + GPU 才隐式学到。
      ⇒ 先补特征，再谈算法。本文件就是补特征的那一层。

【两个版本】
    · `extract(s, me)`            —— 完整版，含攻击关系（慢，训练/离线分析用）
    · `extract_fast(s, me, ...)`  —— 复用调用方已算好的派生量（搜索时用）

【特征口径】
    全部**从 me 方视角**，且对三方对称（把 me 换成任一方，语义不变）。
    归一化后大致落在 [-3, +3]，量纲统一，便于网络学习。
"""
import os
import sys

try:
    from ..engine import geometry_dxf as G
    from ..engine import rules_dxf as R
    from . import eval_dxf as E
except ImportError:                      # 以 server/ 为工作目录直接跑时
    _here = os.path.dirname(os.path.abspath(__file__))
    _root = os.path.dirname(_here)
    for _p in (os.path.join(_root, "engine"), _root, _here):
        if _p not in sys.path:
            sys.path.insert(0, _p)
    from engine import geometry_dxf as G
    from engine import rules_dxf as R
    import eval_dxf as E

BOARD = G.BOARD
VALUE = R.VALUE
GENERAL = R.GENERAL
_ARMIES = (1, 2, 3)

# 特征名（顺序 = 向量下标，改顺序必须同步改 FEATURE_NAMES 与已训模型）
FEATURE_NAMES = (
    # ---- ① 子力（5）----
    "mat_me", "mat_top_enemy", "mat_sum_enemy", "mat_diff_top", "mat_diff_mean",
    # ---- ② 攻防态势（8）----
    "press_me", "press_enemy", "near_my2enemy_gen", "near_enemy2my_gen",
    "near1_me", "near1_enemy", "check_on_me", "check_by_me",
    # ---- ③ 结构（6）----
    "mob_me", "mob_enemy", "dep_me", "dep_enemy", "gen_alive", "enemies_left",
    # ---- ④ ★ 新增：子力安危（当前估值函数**完全没有**的一组）----
    "my_hanging_val", "enemy_hanging_val",      # 被攻击且无人保的子力总值
    "my_attacked_val", "enemy_attacked_val",    # 被攻击的子力总值（含有人保的）
    "my_bad_trade", "enemy_bad_trade",          # 换子净亏（我值 − 最便宜的攻击者）
    "my_cheap_attacked", "enemy_cheap_attacked",  # 被"便宜子"攻击的个数（坏交易笔数）
    "my_hanging_cnt", "enemy_hanging_cnt",      # 悬子个数
    "risk_balance",                             # （我受威胁 − 敌受威胁）/归一
    # ---- ⑤ 进程（2）----
    "ply_frac", "in_check",
)
NFEAT = len(FEATURE_NAMES)
IDX = {n: i for i, n in enumerate(FEATURE_NAMES)}


# ---------------------------------------------------------------- 攻击关系
def attack_map(board):
    """一次遍历算出全盘攻击关系。

    返回 `{点: [(攻击者的点, 攻击者的方), ...]}`

    ⚠️ 关键：**不检查目标点自己的归属**。
       · 攻击者的方 ≠ 目标点的方 ⇒ 这是"攻击"
       · 攻击者的方 == 目标点的方 ⇒ 这是"保护（defend）"
       两件事用同一张表，靠归属现判 —— 否则要跑两遍。
    （`_hit` 本身只看阻挡条件，不看到达点归谁；这正是我们要的语义。）
    """
    out = {}
    hit = getattr(R, "_hit", None)
    for q, specs in R.ATK_BY.items():
        lst = []
        for pos, spec_list in specs.items():
            pc = board.get(pos)
            if pc is None or pos == q:
                continue
            k = pc["kind"]
            for kind, extra in spec_list:
                if kind != k:
                    continue
                if hit is None or hit(board, pos, pc, kind, extra, q):
                    lst.append((pos, pc["army"]))
                    break
        if lst:
            out[q] = lst
    return out


def _risk_stats(board, me, amap):
    """从 me 视角统计"子力安危"

    返回 (悬子值, 被攻值, 坏交易值, 被便宜子攻击数, 悬子数)
      · 悬子   = 被敌方攻击、且**没有任何己方子保护**
      · 被攻值 = 被敌方攻击的所有子力总值（不管有没有保护）
      · 坏交易 = max(0, 我的子力值 − 最便宜的那个攻击者值)  —— 换了就亏
    """
    hang_val = atk_val = bad = 0.0
    cheap_cnt = 0
    hang_cnt = 0.0
    for q, pc in board.items():
        if pc["army"] != me or pc["kind"] == GENERAL:
            continue
        atk = amap.get(q)
        if not atk:
            continue
        enemy_attackers = [p for p, a in atk if a != me]
        if not enemy_attackers:
            continue
        my_defenders = [p for p, a in atk if a == me]
        v = VALUE[pc["kind"]]
        atk_val += v
        if not my_defenders:
            hang_val += v
            hang_cnt += 1
        cheapest = min(VALUE[board[p]["kind"]] for p in enemy_attackers)
        if cheapest < v:
            bad += (v - cheapest)
            cheap_cnt += 1
    return hang_val, atk_val, bad, cheap_cnt, hang_cnt


# ---------------------------------------------------------------- 主提取
def extract(s, me, amap=None, dist=None, split=None):
    """完整特征提取。

    amap / dist / split 可外部传入复用（批量训练时省掉重复计算）。
    """
    board = s["board"]
    if amap is None:
        amap = attack_map(board)
    if dist is None:
        dist = E.distances()
    if split is None:
        split = E._split(s)

    gens, deputies, pieces, mat = split
    my_pieces = pieces.get(me, [])
    my_mat = mat.get(me, 0.0)

    enemies = [a for a in _ARMIES if a != me]
    enemy_mats = [mat.get(a, 0.0) for a in enemies]
    top_enemy = max(enemy_mats) if enemy_mats else 0.0
    sum_enemy = sum(enemy_mats)
    mean_enemy = sum_enemy / len(enemies) if enemies else 0.0

    f = [0.0] * NFEAT
    f[IDX["mat_me"]] = my_mat / 100.0
    f[IDX["mat_top_enemy"]] = top_enemy / 100.0
    f[IDX["mat_sum_enemy"]] = sum_enemy / 100.0
    f[IDX["mat_diff_top"]] = (my_mat - top_enemy) / 20.0
    f[IDX["mat_diff_mean"]] = (my_mat - mean_enemy) / 20.0

    # ---- 攻防态势 ----
    if me not in gens:
        f[IDX["gen_alive"]] = 0.0
    else:
        f[IDX["gen_alive"]] = 1.0
        my_gen = gens[me]
        # 我对每个敌帅的压强
        pr_me = 0.0
        for e in enemies:
            gp = gens.get(e)
            if gp:
                pr_me += E.pressure_of(my_pieces, gp, dist)
                dmap = dist[gp]
                for pos, _k in my_pieces:
                    d = dmap.get(pos)
                    if d is not None and d <= 1:
                        f[IDX["near1_me"]] += 1.0
        f[IDX["press_me"]] = pr_me / 100.0
        # 敌人对我帅的压强
        pr_en = 0.0
        for e in enemies:
            pr_en += E.pressure_of(pieces.get(e, []), my_gen, dist)
        f[IDX["press_enemy"]] = pr_en / 100.0
        # 最近的接敌距离（用"逼近量"，越近越大）
        best_me = 0.0
        for e in enemies:
            gp = gens.get(e)
            if not gp:
                continue
            dmap = dist[gp]
            for pos, _k in my_pieces:
                d = dmap.get(pos)
                if d is not None:
                    best_me = max(best_me, (E.MAX_DIST - d))
        f[IDX["near_my2enemy_gen"]] = best_me / max(1, E.MAX_DIST)
        best_en = 0.0
        for e in enemies:
            dmap = dist.get(my_gen)
            if not dmap:
                continue
            for pos, _k in pieces.get(e, []):
                d = dmap.get(pos)
                if d is not None:
                    best_en = max(best_en, (E.MAX_DIST - d))
        f[IDX["near_enemy2my_gen"]] = best_en / max(1, E.MAX_DIST)
        # 1 步内贴脸数（敌子离**我帅** 1 步）
        dmap_my = dist.get(my_gen)
        if dmap_my:
            for e in enemies:
                for pos, _k in pieces.get(e, []):
                    d = dmap_my.get(pos)
                    if d is not None and d <= 1:
                        f[IDX["near1_enemy"]] += 1.0
    # 将军关系（用反向查表版，快）
    for e in enemies:
        gp = gens.get(e)
        if gp and R.under_attack(board, gp, me):
            f[IDX["check_by_me"]] += 1.0
    if me in gens:
        for e in enemies:
            if R.under_attack(board, gens[me], e):
                f[IDX["check_on_me"]] += 1.0
        if f[IDX["check_on_me"]] > 0:
            f[IDX["in_check"]] = 1.0
    f[IDX["check_by_me"]] /= 2.0
    f[IDX["check_on_me"]] /= 2.0

    # ---- 结构 ----
    mob_me = 0
    for pos, _ in my_pieces:
        mob_me += len(R.pseudo_moves(s, pos))
    mob_en = 0
    for e in enemies:
        for pos, _ in pieces.get(e, []):
            mob_en += len(R.pseudo_moves(s, pos))
    f[IDX["mob_me"]] = mob_me / 200.0
    f[IDX["mob_enemy"]] = mob_en / 400.0
    f[IDX["dep_me"]] = float(len(deputies.get(me, [])))
    dep_en = sum(len(deputies.get(e, [])) for e in enemies)
    f[IDX["dep_enemy"]] = float(dep_en)
    f[IDX["enemies_left"]] = float(len(enemies)) / 2.0

    # ---- ★ 子力安危（新增）----
    hv, av, bad, cc, hc = _risk_stats(board, me, amap)
    f[IDX["my_hanging_val"]] = hv / 50.0
    f[IDX["my_attacked_val"]] = av / 50.0
    f[IDX["my_bad_trade"]] = bad / 50.0
    f[IDX["my_cheap_attacked"]] = cc / 5.0
    f[IDX["my_hanging_cnt"]] = hc / 5.0

    ehv = eav = ebad = 0.0
    ecc = ehc = 0.0
    for e in enemies:
        a, b, c, d, g = _risk_stats(board, e, amap)
        ehv += a
        eav += b
        ebad += c
        ecc += d
        ehc += g
    f[IDX["enemy_hanging_val"]] = ehv / 50.0
    f[IDX["enemy_attacked_val"]] = eav / 50.0
    f[IDX["enemy_bad_trade"]] = ebad / 50.0
    f[IDX["enemy_cheap_attacked"]] = ecc / 5.0
    f[IDX["enemy_hanging_cnt"]] = ehc / 5.0
    f[IDX["risk_balance"]] = (av - eav / max(1, len(enemies))) / 50.0

    # ---- 进程 ----
    f[IDX["ply_frac"]] = min(1.0, s.get("ply", 0) / 300.0)

    # 兜底：任何非有限值一律归零（训练时 NaN 会毁掉整批）
    for i, v in enumerate(f):
        if v != v or v in (float("inf"), float("-inf")):
            f[i] = 0.0
    return f


if __name__ == "__main__":
    from engine import game_dxf as GA
    import time
    s = GA.new_game(first=1)
    t0 = time.time()
    amap = attack_map(s["board"])
    t1 = time.time()
    print(f"攻击表：{len(amap)} 个点，耗时 {(t1 - t0) * 1000:.1f} ms")
    for a in (1, 2, 3):
        t0 = time.time()
        v = extract(s, a, amap=amap)
        print(f"  {G.ARMY_CN[a]}方 特征 {NFEAT} 维，耗时 {(time.time() - t0) * 1000:.1f} ms")
        print(f"    {[round(x, 3) for x in v]}")
    print(f"\n特征名（{NFEAT} 维）：")
    for i, n in enumerate(FEATURE_NAMES):
        print(f"  [{i:>2}] {n}")
