# -*- coding: utf-8 -*-
"""三人象棋 · 局面评估函数（从某一方视角打分）

【设计原则 —— 老师的博弈观】
    「下象棋基本思维博弈逻辑是尽可能最快实现干掉其它国的将」
    「其它子的死活不重要，关键是保住自己的将的同时先一步想办法干掉别国的将」

所以评估的核心**不是子力**，而是两个「计时器」：
    ① 我离敌帅有多近（威胁）  —— 越近越好
    ② 敌帅离我的帅有多近（危险）—— 越远越好
子力只作为「能否够到、够到之后能否活下来」的支撑项，权重远低于上面两项。

【AlphaZero 的「无为法」体现在哪】
    本文件的 DEFAULT_W 只是**起点**，不是答案。
    真正的权重由 selfplay.py 通过**自我对弈**进化出来（weights.json），
    全程不告诉它"什么是好棋"——只告诉它"这局谁赢了"。
    这就是"无为"：不预设棋理，让对局结果自己把权重推到该去的地方。
"""
import math

try:
    from ..engine import geometry_dxf as G
    from ..engine import rules_dxf as R
except ImportError:                      # 以 server/ 为工作目录直接跑本文件时
    import os as _os
    import sys as _sys
    _sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
    from engine import geometry_dxf as G
    from engine import rules_dxf as R

B = G.BOARD
VALUE = R.VALUE
GENERAL = R.GENERAL

# ---------------------------------------------------------------- 权重
# 起始权重（人工给的粗略起点，之后完全交给自我对弈调整）
#
# 【关键教训 —— 三人棋为什么会"和平对峙"】
#   三方对称的局面下，"主动进攻"会削弱自己、便宜第三方（渔翁得利），
#   所以**不进攻在博弈论上才是理性的**。纯风险中性的评估函数必然导向僵局
#   （实测：两个 1 层搜索 Bot 对下 200 手，只有 2 步出现过吃子机会）。
#
#   所以评估函数必须内建**打破对称的机制**：
#     ① pressure 明显高于 danger（进攻的边际收益 > 被进攻的边际损失）
#     ② urgency —— 进攻权重随对局进行而上升。
#        棋理上也说得通：时间是一种资源，长久僵持对谁都没好处，
#        下到中后盘必须有人先动手，否则永远分不出胜负。
# 【权重的正确量级 —— 一个踩过的坑】
#   评估项的"绝对值"毫无意义，Bot 只在乎**走一步带来的边际变化**：
#       pressure 的绝对值 = w × 240（开局三方各自的压强总和）
#       pressure 的边际值 = w × 子力价值 × 1 步
#   用绝对值定权重（w=0.05 → 12 分）看起来够大，
#   但边际只有 0.45 分 —— 比探索噪声（0.8）还小，
#   于是"走向通道口"的信号被噪声完全淹没，Bot 走不到位、永不接战。
#   正确做法：按**边际**定权 —— 让"车走一步"值 2 分左右 → w ≈ 0.25。
DEFAULT_W = {
    "pressure":   0.250,   # 我方对敌帅的进攻压强（★核心，非对称）
    "danger":     0.100,   # 敌对我方帅的压强（低于 pressure 的一半）
    "urgency":    0.050,   # 进攻压力随对局进行增长（打破僵局的主引擎）
    "material":   0.100,   # 子力差 —— 刻意压低：老师的原则是
                           # 「其它子的死活不重要，关键是干掉别国的将」
    "check":    120.00,    # ★将军（强制对方应对 —— 打破僵局最有力的机制）
    "close1":   400.00,    # 有子贴到敌帅 1 步之内（能吃帅）
    "close2":    80.00,    # 有子离敌帅 2 步（一步之遥）
    "mobility":   0.02,    # 机动性
    "deputy":     6.00,    # 手握副帅（专利版：主帅失守仍保留战斗力）
    "gen_lost":  50.00,    # 自家主帅已被吃
}
W_KEYS = tuple(DEFAULT_W)

# 图上任意两点的最大图距离（实测 111↔211 = 15）
MAX_DIST = 15


# ---------------------------------------------------------------- 全源距离
_DIST = None


def distances():
    """预计算全部 135 点的两两图距离（BFS 全源最短路）。

    评估函数里要反复问「某子离敌帅几步」，用查表 O(1) 取代每次 BFS。
    """
    global _DIST
    if _DIST is not None:
        return _DIST
    from collections import deque
    d = {}
    for src in B.xy:
        dist = {src: 0}
        q = deque([src])
        while q:
            cur = q.popleft()
            for nb in B.adj.get(cur, ()):
                if nb not in dist:
                    dist[nb] = dist[cur] + 1
                    q.append(nb)
        d[src] = dist
    _DIST = d
    return d


# ---------------------------------------------------------------- 局面拆解
def _split(s):
    """一次性把局面拆成 (主帅位, 副帅位, 各子列表)

    返回：
        gens      {army: pos}            —— 主力帅
        deputies  {army: [pos, ...]}     —— 副帅
        pieces    {army: [(pos, kind)]}  —— 该方所有子（含收编来的）
        mat       {army: 子力总值}
    """
    gens, deputies, pieces, mat = {}, {}, {}, {}
    for pos, pc in s["board"].items():
        a = pc["army"]
        if pc["kind"] == GENERAL:
            if pc.get("deputy"):
                deputies.setdefault(pc["home"], []).append(pos)
            else:
                gens[pc["home"]] = pos
            continue
        pieces.setdefault(a, []).append((pos, pc["kind"]))
        mat[a] = mat.get(a, 0.0) + VALUE[pc["kind"]]
    return gens, deputies, pieces, mat


def pressure_of(pieces, target, dist, maxd=None):
    """进攻压强 = Σ(子力价值 × 逼近量)

       逼近量 = MAX_DIST - 该子到 target 的图距离

    为什么用"求和"而不是"取最近的一颗"：
      取最近的会被**单颗尖兵刷分** —— 派一个兵冲到河界就能拿满分，
      于是 Bot 只需要一个兵往前顶，其余子在家守着，永远打不起来（实测如此）。
      求和则要求**多颗子一起压上**，才形成真正的攻势 —— 这也符合象棋常识：
      车马炮一起扑上去才能构成杀势，一颗孤兵什么也做不了。

    车（9）的贡献是兵（1）的 9 倍，所以 Bot 会优先把大子推向前线。
    """
    dmap = dist.get(target)
    if not dmap:
        return 0.0
    maxd = MAX_DIST if maxd is None else maxd
    tot = 0.0
    for pos, kind in pieces:
        d = dmap.get(pos)
        if d is not None:
            # 用 sqrt(子力) 加权而非线性加权：
            # 线性加权时，丢一个车会让 pressure 骤降 9×(15-d)，
            # 于是"车换兵"被判为灾难性亏损，Bot 宁死不出门。
            # sqrt 把它压缩到 3×(15-d)，仍然"车比兵值钱"，但不再一票否决进攻。
            tot += _SQRT_VALUE[kind] * (maxd - d)
    return tot


# sqrt 子力表（模块载入时算一次）
_SQRT_VALUE = {k: math.sqrt(v) for k, v in VALUE.items()}


def threat_of(pieces, target, dist, scale=0.30):
    """「威胁度」= 该方所有子对 target 的综合威胁

    单项 = 子力价值 / (1 + scale × 步数)
      · 车（9）比兵（1）危险得多 → 用价值加权
      · 距离每多一步就衰减 → 逼近会自然涨分，退开自然掉分
    这就是「最快够到敌帅」在评估里的数学形式。
    """
    tot = 0.0
    dmap = dist.get(target)
    if not dmap:
        return 0.0
    for pos, kind in pieces:
        d = dmap.get(pos)
        if d is None:
            continue
        tot += VALUE[kind] / (1.0 + scale * d)
    return tot


# ---------------------------------------------------------------- 主评估
def evaluate(s, me, w=None, ply=0):
    """从 me 方视角给局面打分（分越高，me 越有利）

    ply 用于"进攻压力"：对局越往后，进攻的权重越大（见 DEFAULT_W 的说明）。
    """
    w = w or DEFAULT_W
    gens, deputies, pieces, mat = _split(s)

    # ① 我方主帅已经没了 —— 出局，极低分
    if me not in gens:
        return -1e6 + mat.get(me, 0.0)

    dist = distances()
    my_gen = gens[me]
    my_pieces = pieces.get(me, [])
    ur = 1.0 + ply * w.get("urgency", 0.0)      # 进攻压力随对局进行上升

    sc = 0.0

    # ② 进攻压强：我对每个敌帅压得有多紧（★核心，带 urgency）
    c1 = ur * w.get("close1", 0.0)
    c2 = ur * w.get("close2", 0.0)
    wchk = ur * w.get("check", 0.0)
    shim = {"board": s["board"]}
    for enemy, gpos in gens.items():
        if enemy == me:
            continue
        sc += ur * w["pressure"] * pressure_of(my_pieces, gpos, dist)
        # ★将军：规则上被将军方必须解将、第三方停走 —— 这是**强制性**的，
        #   是三人棋里唯一能逼对手就范、打破平衡的手段。
        if wchk and R.attacked(shim, gpos, {me}):
            sc += wchk
        # 贴脸奖励：有子抵近敌帅，是"最快够到敌将"最直接的信号
        dmap = dist[gpos]
        for pos, _k in my_pieces:
            d = dmap.get(pos)
            if d is None:
                continue
            if d <= 1:
                sc += c1
            elif d == 2:
                sc += c2

    # ③ 被进攻压强：每个敌人对我方帅压得有多紧（负分，不带 urgency）
    for enemy in gens:
        if enemy == me:
            continue
        sc -= w["danger"] * pressure_of(pieces.get(enemy, []), my_gen, dist)

    # ④ 子力：只和**最强的那个对手**比 —— 三人棋里最强者才是最终对手
    my_mat = mat.get(me, 0.0)
    top_enemy = 0.0
    for enemy in gens:
        if enemy == me:
            continue
        top_enemy = max(top_enemy, mat.get(enemy, 0.0))
    sc += w["material"] * (my_mat - top_enemy)

    # ⑤ 专利版：手握副帅 = 主帅虽失，仍保有战斗力
    sc += w["deputy"] * len(deputies.get(me, []))

    # ⑥ 机动性（轻量）：能走的步数越多，选择余地越大
    mobility = 0
    for pos, _ in my_pieces:
        mobility += len(R.pseudo_moves(s, pos))
    sc += w["mobility"] * mobility

    return sc


def evaluate_fast(s, me, w, gens, pieces, dist):
    """给搜索用的轻量版：调用方已经拆好局面，避免重复拆解"""
    if me not in gens:
        return -1e6
    my_gen = gens[me]
    my_pieces = pieces.get(me, [])
    sc = 0.0
    for enemy, gpos in gens.items():
        if enemy == me:
            continue
        sc += w["threat"] * threat_of(my_pieces, gpos, dist)
        sc -= w["danger"] * threat_of(pieces.get(enemy, []), my_gen, dist)
    return sc


# ---------------------------------------------------------------- 自检
if __name__ == "__main__":
    import sys
    import time
    sys.path.insert(0, ".")
    from engine import game_dxf as GA

    t0 = time.time()
    distances()
    print(f"全源距离表：135 点，耗时 {time.time() - t0:.2f}s")

    s = GA.new_game()
    t0 = time.time()
    for a in (1, 2, 3):
        print(f"  {G.ARMY_CN[a]}方开局评分 = {evaluate(s, a):+9.2f}")
    dt = (time.time() - t0) / 3
    print(f"单次评估耗时 {dt * 1000:.2f} ms")
    print()
    print("=== 三方对称性检查（开局应该三方差值很接近）===")
    v = [evaluate(s, a) for a in (1, 2, 3)]
    print(f"  评分 {[round(x, 2) for x in v]}   极差 {max(v) - min(v):.2f}")
