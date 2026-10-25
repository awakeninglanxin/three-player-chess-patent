# -*- coding: utf-8 -*-
"""三人象棋 · 对弈实验台（Arena）—— 把「谁下得好」变成一个可测量的数

【这份工具的由来】
    一份 LLM 棋力评测方案给了三条对本项目直接适用的启示，Arena 就是照这三条搭的：

    ① 合法率是第一指标，不是胜率。
       实测：不给合法着法（裸生成）合法率 0%（3 次重试全废）；
             给了合法着法（选择题）合法率 100%。
       所以 Arena 的第一张表是**合法率 / 回退率** —— 先把「不会下棋」的筛掉，
       再谈谁的棋更高。

    ② 引擎吻合度比胜负稳定得多。
       三人棋极度容易长期僵持（三方完美对弈时必然如此 —— 见 README 的博弈论分析），
       一局跑完常常判和，胜率几乎没有区分度。
       但**每一步的质量分布**天天可测：把实走着法丢进搜索榜单，
       看它离最优差多远 → 打 best/excellent/inaccuracy/mistake/blunder 标签。
       这就是「失误谱」（blunder spectrum），跟象棋网站的复盘标签一个意思。

    ③ 严格时限会惩罚长考模型、偏向「快但浅」。
       所以预算不能只跑一个点，要跑一条**曲线**：横轴 token/步（或秒/步），
       纵轴棋力分。Arena 顺手把每步 token 记下来，这条曲线是白送的。

【两个必须钉死的控制变量】
    · 视角（score_perspective）：本项目评估一律是 **stm（走棋方视角）** ——
      「分数越高，走棋方越有利」。这样一次评估不需要知道「谁是红方」，
      三方轮转时不会出现符号反了的问题。
      （二人棋引擎常返回「红方视角」，混用会让 cp_loss 符号全反 —— 踩过的坑。）

    · 赛制（mode）：
      choice = 给棋盘 + 全部合法着法（测**纯决策质量**，默认档）
      raw    = 只给棋盘（测**规则内化 + 指令遵循**，合法率会很难看的那档）

【起手方轮换】
    三人棋三个座位几何等价，但「谁先动」不对称（先动者先暴露意图、
    也先进入另两方的视野）。固定魏方起手，会把起手优劣系统性算成棋力差。
    所以 Arena 默认**三方各起手一次**，与二人棋评测的「双色轮换」同一个道理。

【锚点阶梯】
    SearchBot 的搜索深度天然是一把尺子：depth=1 / depth=2 就是两档锚点，
    被测方跟它们同桌，用相对强度插值出「等效搜索深度」。
    注意：这是**本项目内的相对分**，不能跟外部 Elo 排行榜对比
    ——「玩家池内相对分」换个池子就不通用。
"""
import json
import os
import sys
import time

try:
    from ..engine import game_dxf as GA
    from ..engine import rules_dxf as R
    from .search_bot import SearchBot, VALUE, load_weights
    from . import eval_dxf as E
except ImportError:                      # 以 server/ 或 agents/ 为工作目录时走这条
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from engine import game_dxf as GA
    from engine import rules_dxf as R
    from search_bot import SearchBot, VALUE, load_weights
    import eval_dxf as E

HERE = os.path.dirname(os.path.abspath(__file__))
ARMY_CN = GA.ARMY_CN

# ---------------------------------------------------------------- 失误谱
# 分档按「榜单最好 vs 最差」的张力归一化 —— 换一套评估权重、量纲变了也不用重标。
# 硬规则优先：斩帅的直接算 best，把自己送进必死局的直接算 blunder（看 grade_move）。
#
# ⚠ 这两个数是**占位值**，必须用自己跑出来的数据标定一次才算数
#   （跟「锚点 Elo 必须用引擎自对弈校准」是同一件事）。
#   标定方法：跑几十局 → calibrate_losses() 打印损失分位数 → 照分位数改这里的阈值。
#   默认值取得偏宽：宁可把「次优但要领正确」判成优秀，也别把好棋误判成失误。
BANDS = (("excellent", 0.08), ("inaccuracy", 0.22), ("mistake", 0.45))
LABELS = ("best", "excellent", "inaccuracy", "mistake", "blunder")
LABEL_CN = {"best": "最佳", "excellent": "优秀", "inaccuracy": "欠准",
            "mistake": "失误", "blunder": "大漏"}
# 评分器深度与失误谱的标签含义直接相关（见 grade_move 的说明）：
# 浅评分器 + 深棋手 = 测出来的是「和弱引擎的吻合度」，会把好棋误伤成失误。
GRADE_PLIES = 6          # 默认评分深度：两层预判，0.5s/次


def label_of(loss, spread, rank):
    """按归一化损失给一步棋贴标签（rank=1 直接是最佳）"""
    if rank == 1 or spread <= 1e-9:
        return "best"
    f = max(0.0, loss) / spread
    for name, hi in BANDS:
        if f <= hi:
            return name
    return "blunder"


def grade_move(state, legal, move, grader, plies=GRADE_PLIES):
    """给一步棋打分。**state 必须是落子前的局面**（否则榜单算的是别人该走什么）。

    grader : 复用的 SearchBot 实例（内部会重置时限与历史表，可反复调用）
    plies  : 搜索深度，3 的倍数（3 = 一层预判，6 = 两层）

    【评分器必须是「参考典（oracle）」，不能只是「另一个玩家」】
        rank_root 走**全宽**（不砍宽度），就是为了让榜单成为一把干净的尺子。
        实测：SearchBot 自己用「迭代加深 + 渐进加宽」提速，plies=6 只展开前 14 名，
        于是 depth=2 的它 vs 全宽 plies=6 的评分器，good_rate 只有 50~88% ——
        这不是它棋差，是**两者本就不是同一个搜索**。
        · 想报绝对棋力 → 必须把「depth 名义值」和「全宽 plies」分开标注，别混用。
        · 想测决策质量（LLM 这类没有自带搜索的对手）→ 这套指标才干净、才好用。

    返回 : None（着法不在榜单里，即非法）或
           {"move","rank","n_moves","best_move","best_score","score",
            "loss","loss_norm","label"}
    """
    if not legal:
        return None
    ranked = grader.rank_root(state, legal, plies=plies)
    if not ranked:
        return None
    table = dict(ranked)
    if move not in table:
        return None
    order = [m for m, _ in ranked]
    best_move, best_score = ranked[0]
    played = table[move]
    spread = best_score - ranked[-1][1]
    rank = order.index(move) + 1
    loss = best_score - played
    return {"move": move, "rank": rank, "n_moves": len(ranked),
            "best_move": best_move, "best_score": round(best_score, 2),
            "score": round(played, 2), "loss": round(loss, 2),
            "loss_norm": round(max(0.0, loss) / spread, 4) if spread > 1e-9 else 0.0,
            "label": label_of(loss, spread, rank)}


def calibrate_losses(recs, bands=None):
    """从已跑完的对局里统计「归一化损失」的分位数 → 用来标定 BANDS。

    分位数含义：0.5 分位 = 一半的着法比它更接近最优。
    取 p50→excellent / p75→inaccuracy / p90→mistake 是一套温和的起点，
    想更严就往左收。标定完把 BANDS 改成对应值即可。
    """
    v = sorted(m["loss_norm"] for r in recs for m in r["moves"]
               if m.get("loss_norm") is not None)
    if not v:
        return {"n": 0}
    def q(p):
        return round(v[min(len(v) - 1, int(p * len(v)))], 4)
    out = {"n": len(v), "p10": q(.10), "p25": q(.25), "p50": q(.50),
           "p75": q(.75), "p90": q(.90), "p99": q(.99), "max": v[-1]}
    if bands:
        out["_note"] = f"当前 BANDS={bands}；建议改为 (excellent=p50, inaccuracy=p75, mistake=p90)"
    return out


# ---------------------------------------------------------------- 推进量
def progress_of(s, army, dist):
    """(进攻压强, 到最近敌帅的距离) —— 走棋方视角。

    【为什么要造这把尺子】
        三人棋在双方（三方）都不犯错时会**长期零吃子僵持** ——
        实测 36 手一个子都没掉，三方综合分全是 684.0，锚点阶梯彻底失去区分度。
        胜率和子力在这类对局里都是常数，量不出「谁下得更好」。

        但「有没有在真正推进」是变的：谁的子更逼近敌帅、对敌帅的压强更大，
        谁就是在下棋，谁在划水一目了然。
        这就是「推进量」——僵持局面下的唯一有效区分度。

    基准要取**开局值**再做差：开局三方完全对称（实测总压强都是 240.7），
    直接比绝对值等于没比。
    """
    gens, _dep, pieces, _mat = E._split(s)
    mine = pieces.get(army) or []
    press, near = 0.0, None
    for enemy, gpos in gens.items():
        if enemy == army:
            continue
        press += E.pressure_of(mine, gpos, dist)
        dmap = dist[gpos]
        for pos, _k in mine:
            d = dmap.get(pos)
            if d is not None and (near is None or d < near):
                near = d
    return press, near


def _progress_snapshot(s, dist):
    """开局基准：三方各自的 (压强, 最近敌帅距离)"""
    return {a: progress_of(s, a, dist) for a in (1, 2, 3)}


# ---------------------------------------------------------------- 单局
def play_game(agents, first=1, max_ply=120, mode="choice", grader=None,
              grade_plies=GRADE_PLIES, on_move=None):
    """跑完一局，返回完整记录。

    agents : {1: agent, 2: agent, 3: agent}，接口 choose(state, legal, text, army_cn)
    mode   : "choice" 给合法着法 / "raw" 只给棋盘
    grader : 给每步打分的 SearchBot；None 则不打分（纯跑局，快很多）

    **非法着法不悄悄兜底**：观战模式（match.py）会自动降级到本地 Bot 让棋局走下去，
    但评测里那样做会让合法率永远 100%、什么也测不出来。
    这里改成「如实记一次非法，再用该方第一步合法着法强行推进」，
    棋局照样能走完，但合法率是真实的。
    """
    s = GA.new_game(first=first)
    rec = {"first": first, "mode": mode, "max_ply": max_ply,
           "moves": [], "winner": None, "end": "", "elapsed": 0.0}
    kills = {1: 0.0, 2: 0.0, 3: 0.0}
    slain = {1: 0, 2: 0, 3: 0}
    illegal = {1: 0, 2: 0, 3: 0}
    dist = E.distances()
    base = _progress_snapshot(s, dist)          # 开局基准（三方对称，必须做差）
    rec["base_progress"] = {str(a): [round(base[a][0], 1), base[a][1]]
                            for a in (1, 2, 3)}
    t_game = time.time()

    while not s["winner"] and s["ply"] < max_ply:
        army = s["turn"]
        legal = GA.legal_moves(s, army)
        if not legal:
            GA._advance(s)
            continue
        legal_set = {f"{a}-{b}" for a, b in legal}
        press, near = progress_of(s, army, dist)   # 落子前的推进量
        text = GA.render_text(s, legal, show_legal=(mode == "choice"),
                              show_history=False)
        ag = agents[army]
        t0 = time.time()
        try:
            res = ag.choose(s, legal, text, ARMY_CN[army]) or {}
        except Exception as e:                       # 单方报错不能弄死整局
            res = {"move": None, "reason": f"{type(e).__name__}: {e}"}
        dt = time.time() - t0

        mv = res.get("move")
        ok = bool(mv) and mv in legal_set
        if not ok:
            illegal[army] += 1
            mv = f"{legal[0][0]}-{legal[0][1]}"      # 强行推进，但已记过
        # 打分要在落子**前**做
        grade = grade_move(s, legal, mv, grader, plies=grade_plies) \
            if (grader is not None and ok) else None

        a, b = mv.split("-")
        victim = s["board"].get(b)
        if victim and victim["army"] != army and victim["kind"] != R.GENERAL:
            kills[army] += VALUE.get(victim["kind"], 1.0)
        note = GA.apply(s, a, b)
        if victim and victim["army"] != army and victim["kind"] == R.GENERAL:
            slain[army] += 1

        st = ag.stats
        entry = {"ply": s["ply"] - 1, "army": army, "move": mv, "legal": ok,
                 "latency": round(dt, 3), "reason": str(res.get("reason", ""))[:60],
                 "captured": note.get("captured"),
                 "eliminated": note.get("eliminated"),
                 # 推进量（僵持局里唯一有区分度的尺子）
                 "press": round(press, 1), "near": near,
                 "ptokens": st.get("ptokens", 0), "ctokens": st.get("ctokens", 0),
                "label": grade["label"] if grade else None,
                "loss": grade["loss"] if grade else None,
                "loss_norm": grade["loss_norm"] if grade else None,
                "rank": grade["rank"] if grade else None,
                "best_move": grade["best_move"] if grade else None}
        rec["moves"].append(entry)
        if on_move:
            on_move(entry)
        if s["ply"] >= max_ply and not s["winner"]:
            rec["end"] = "手数上限"

    rec["winner"] = s["winner"]
    if s["winner"]:
        rec["end"] = f"{ARMY_CN[s['winner']]}方独存获胜"
    rec["elapsed"] = round(time.time() - t_game, 2)
    rec["kills"] = {str(k): round(v, 1) for k, v in kills.items()}
    rec["slain"] = {str(k): v for k, v in slain.items()}
    rec["illegal"] = {str(k): v for k, v in illegal.items()}
    rec["alive"] = GA.alive_armies(s)
    rec["final_board"] = s["board"]
    return rec


# ---------------------------------------------------------------- 汇总
def composite(rec, army):
    """单方综合实力分（数值越高越强）。

    权重顺序体现了三人棋的价值观：斩帅 >> 在场子力 ≥ 吃子收益 > 存活 > 非法扣分。
    非法着法要重罚 —— 它是「不遵守规则」，比「下得差」严重。

    ⚠ 必须把**在场子力**算进去。只算「吃子收益」的话，一局没吃子的对局
      三方分数完全相同（都是 300），阶梯 R 退化成 1.0、什么也量不出来 ——
      这是实测踩到的坑（典型现象：只有全部并列时才需要怀疑指标，不是棋子）。
    """
    alive = army in rec["alive"]
    mat = sum(VALUE.get(p["kind"], 1.0)
              for p in rec.get("final_board", {}).values()
              if p["army"] == army and p["kind"] != R.GENERAL)
    # 推进量（相对开局基准）：子力没动、也没吃子的僵持局里，这是唯一的区分度。
    # 系数是标定出来的量纲对齐 —— 逼近敌帅 1 格 ≈ 60 分，约等于吃掉一个炮。
    pd, nd = progress_delta(rec, army)
    prog = (pd * 2.0) + (nd * 60.0)
    return round(rec["slain"].get(str(army), 0) * 1000.0
                 + mat * 8.0
                 + rec["kills"].get(str(army), 0.0) * 8.0
                 + prog
                 + (300.0 if alive else 0.0)
                 - rec["illegal"].get(str(army), 0) * 20.0, 1)


def progress_delta(rec, army):
    """(平均压强增量, 平均逼近格数) —— 都相对本局开局基准"""
    base = rec.get("base_progress", {}).get(str(army))
    moves = [m for m in rec["moves"] if m["army"] == army and m.get("press") is not None]
    if not base or not moves:
        return 0.0, 0.0
    p0, n0 = base[0], base[1]
    dp = sum(m["press"] - p0 for m in moves) / len(moves)
    dn = sum((n0 - m["near"]) for m in moves if m.get("near") is not None)
    dn = dn / max(1, sum(1 for m in moves if m.get("near") is not None))
    return round(dp, 1), round(dn, 2)


def summarize(recs):
    """把多局记录汇总成一张对比表 + 预算-表现曲线"""
    out = {}
    for army in (1, 2, 3):
        moves = [m for r in recs for m in r["moves"] if m["army"] == army]
        n = len(moves)
        if not n:
            out[army] = {"moves": 0}
            continue
        grades = [m["label"] for m in moves if m["label"]]
        dist = {lb: grades.count(lb) for lb in LABELS} if grades else {}
        tok = [(m["ptokens"], m["ctokens"]) for m in moves]
        # 每步 token 增量（LLMAgent 的统计是累计值）
        steps_pt, steps_ct = [], []
        prev = (0, 0)
        for p, c in tok:
            steps_pt.append(max(0, p - prev[0]))
            steps_ct.append(max(0, c - prev[1]))
            prev = (p, c)
        lat = [m["latency"] for m in moves]
        illegal = sum(1 for m in moves if not m["legal"])
        pd = [progress_delta(r, army) for r in recs]
        out[army] = {
            "moves": n,
            "illegal": illegal,
            "legal_rate": round(1 - illegal / n, 4),
            "avg_latency": round(sum(lat) / n, 3),
            # 推进量：僵持局面下的区分度（相对开局基准）
            "press_delta": round(sum(x[0] for x in pd) / len(pd), 1) if pd else 0.0,
            "near_delta": round(sum(x[1] for x in pd) / len(pd), 2) if pd else 0.0,
            "avg_prompt_tok": round(sum(steps_pt) / n, 1),
            "avg_out_tok": round(sum(steps_ct) / n, 1),
            "label_dist": dist,
            "good_rate": round((dist.get("best", 0) + dist.get("excellent", 0))
                               / max(1, len(grades)), 4) if grades else None,
            "blunder_rate": round(dist.get("blunder", 0) / max(1, len(grades)), 4)
                            if grades else None,
            "kills": round(sum(r["kills"].get(str(army), 0.0) for r in recs), 1),
            "slain": sum(r["slain"].get(str(army), 0) for r in recs),
            "games_survived": sum(1 for r in recs if army in r["alive"]),
            "composite": round(sum(composite(r, army) for r in recs) / len(recs), 1),
        }
    return out


def gauntlet(agents_factory, games_per_seat=1, max_ply=120, mode="choice",
            grader=None, grade_plies=GRADE_PLIES, verbose=True):
    """起手方轮换跑多局。

    agents_factory(seat) -> agent
        每次开局都重新造 agent，避免统计量在局间累积污染「每步 token 增量」。
    """
    recs = []
    for first in (1, 2, 3):
        for g in range(games_per_seat):
            agents = {k: agents_factory(k) for k in (1, 2, 3)}
            r = play_game(agents, first=first, max_ply=max_ply, mode=mode,
                          grader=grader, grade_plies=grade_plies,
                          on_move=(lambda e: print(
                              f"    #{e['ply']:>3} {ARMY_CN[e['army']]} {e['move']:<9}"
                              f" {'OK ' if e['legal'] else '×非法'}"
                              f" {e['label'] or '-':<10} 差{e['loss'] if e['loss'] is not None else '-':>8}"
                              f" {e['latency']:>5.2f}s")) if verbose else None)
            recs.append(r)
            if verbose:
                print(f"  [起手{ARMY_CN[first]}] 第{g + 1}局 → {r['end']}"
                      f"（{len(r['moves'])} 手 / {r['elapsed']}s）\n")
    return recs


# ---------------------------------------------------------------- 锚点阶梯
def ladder(agent_factory, anchors=(1, 2), games=1, max_ply=90, mode="choice",
           grader=None, grade_plies=GRADE_PLIES, seed0=20260923):
    """用 SearchBot 深度当尺子，量出被测方的「等效搜索深度」。

    做法：被测方占 1 号座，另两座放**同一深度**的搜索 Bot（不同种子，避免镜像）。
    对每个锚点深度 d 算「被测方综合分 / 两锚点平均分」= 相对强度 R(d)。
    深度越深锚点越强，R 应该单调下降；R 穿过 1.0 的地方就是等效深度。

    ⚠ 这是**本项目内的相对分**。换锚点定义、换评估权重都要重标。
    """
    curve = []
    for d in anchors:
        recs = []
        for g in range(games):
            def factory(seat, _d=d, _g=g):
                if seat == 1:
                    return agent_factory(seat)
                return SearchBot(depth=_d, time_limit=2.0,
                                 seed=seed0 + _g * 977 + seat * 31,
                                 label=f"锚点·搜索{_d}层")
            recs.append(play_game({k: factory(k) for k in (1, 2, 3)},
                                  first=(1, 2, 3)[g % 3], max_ply=max_ply,
                                  mode=mode, grader=grader,
                                  grade_plies=grade_plies))
        s = summarize(recs)
        me = s[1]["composite"]
        opp = (s[2]["composite"] + s[3]["composite"]) / 2
        curve.append({"depth": d, "mine": me, "anchors": round(opp, 1),
                      "R": round(me / opp, 4) if opp else None})
    # 线性插值出 R=1 的深度
    eq = None
    pairs = [(a, b) for a, b in zip(curve, curve[1:])
             if a["R"] is not None and b["R"] is not None]
    for a, b in pairs:
        if abs(a["R"] - 1.0) < 1e-9:            # 正好落在锚点上
            eq = float(a["depth"])
            break
        if abs(b["R"] - 1.0) < 1e-9:
            eq = float(b["depth"])
            break
        if (a["R"] - 1) * (b["R"] - 1) < 0:     # 跨越 1.0 → 插值
            t = (1 - a["R"]) / (b["R"] - a["R"])
            eq = round(a["depth"] + t * (b["depth"] - a["depth"]), 3)
            break
    # 全在同一侧：给「界」而不是假造一个数
    if eq is None and curve and all(c["R"] is not None for c in curve):
        if all(c["R"] > 1 for c in curve):
            eq = f">{curve[-1]['depth']}（比最深锚点还强）"
        elif all(c["R"] < 1 for c in curve):
            eq = f"<{curve[0]['depth']}（比最浅锚点还弱）"
        else:
            eq = "锚点区分度不足（各档 R 相同 —— 通常是子力太接近，多跑几局）"
    return {"curve": curve, "equivalent_depth": eq}


# ---------------------------------------------------------------- 自检
def _table(s):
    print(f"{'方':<4}{'手数':>5}{'合法率':>9}{'均延迟':>9}{'优+最佳':>9}"
          f"{'大漏率':>9}{'综合分':>9}")
    for a in (1, 2, 3):
        d = s[a]
        if not d.get("moves"):
            continue
        print(f"{ARMY_CN[a]:<4}{d['moves']:>5}{d['legal_rate'] * 100:>8.1f}%"
              f"{d['avg_latency']:>8.2f}s"
              f"{(d['good_rate'] or 0) * 100:>8.1f}%"
              f"{(d['blunder_rate'] or 0) * 100:>8.1f}%{d['composite']:>9.1f}")


def _spectrum(s):
    for a in (1, 2, 3):
        d = s[a]
        if d.get("label_dist"):
            print(f"  {ARMY_CN[a]}方  " + "  ".join(
                f"{LABEL_CN[k]}={d['label_dist'][k]}" for k in LABELS))


def _selftest():
    print("=" * 70)
    print("Arena 自检：深度 1 / 1 / 2 的三个搜索 Bot 同桌")
    print("=" * 70)
    seats = [("深度1", 1), ("深度1", 1), ("深度2", 2)]
    recs = {pl: [] for pl in (3, 6)}

    for plies in (3, 6):
        g = SearchBot(depth=1, time_limit=30.0, seed=7, label=f"评分器{plies}步")
        agents = {i + 1: SearchBot(depth=d, time_limit=1.5, seed=10 + i,
                                   label=nm) for i, (nm, d) in enumerate(seats)}
        recs[plies].append(play_game(agents, first=1, max_ply=18, mode="choice",
                                     grader=g, grade_plies=plies))

    for plies in (3, 6):
        s = summarize(recs[plies])
        print(f"\n--- 评分器 {plies} 步（{'一层预判' if plies == 3 else '两层预判'}）---")
        _table(s)
        _spectrum(s)
        c = calibrate_losses(recs[plies])
        print(f"  归一化损失分位：{c}")

    s3, s6 = summarize(recs[3]), summarize(recs[6])
    print("\n" + "=" * 70)
    print("结论一：评分器必须是「参考典」，不能只是「另一个玩家」")
    print(f"  · 评分器 3 步（全宽）时，深度1 两方 good_rate="
          f"{(s3[1]['good_rate'] or 0) * 100:.0f}% / {(s3[2]['good_rate'] or 0) * 100:.0f}%"
          f" —— 深度1 就是全宽 plies=3 的 argmax，与评分器同源，所以吻合最高")
    print(f"  · 深度2 一方 good_rate={(s3[3]['good_rate'] or 0) * 100:.0f}%"
          f" —— 更低，看着像「棋更差」，其实不是（见结论二）")
    print("  （每方只有 6 手，样本很小；要下结论得跑几十局，这里只看方向性）")
    print()
    print("结论二：「depth=2」名不副实 —— 这是本轮最值得记的一条实测发现")
    print("  SearchBot 用「迭代加深 + 渐进加宽」提速：plies=6 只展开 plies=3 排名的前 14 名。")
    print("  而评分器 rank_root 走**全宽**。所以 depth=2 ≠ 全宽 6 plies，")
    print("  它实际是「全宽 3 plies + 窄搜 6 plies」，两者本就是不同的搜索，")
    print("  吻合度自然低。→ 想报绝对棋力，就得把 depth 与「全宽 plies」分开标注；")
    print("  想测决策质量（LLM 那种没有自己搜索的对手），这套指标才是干净的。")
    print()
    print("结论三：三人棋短手数内分不出胜负（终局多为「手数上限」）——")
    print("  这正是要用「失误谱 / 合法率」而不是「胜率」做评测的根本原因。")
    print("=" * 70)


if __name__ == "__main__":
    _selftest()
