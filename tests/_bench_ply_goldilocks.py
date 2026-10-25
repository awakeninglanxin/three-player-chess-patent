# -*- coding: utf-8 -*-
"""搜索深度的「金发姑娘区」—— 分清**真变招**与**噪声变招**（老师 2026-10-01 提问）

老师原话：「搜索树深度能否再优化一下，不一定非要用到 15 plies，
           从而找到一个黄金分割点/金发姑娘区，推荐人的下一步用」

【为什么不能只看"变没变招"】
  已有的 `_bench_ply_sat.json` 显示：12→15 有时会换招。但**换招不等于变好** ——
  换招有两种，价值天差地别：
    · **噪声变招**：浅层对这两手本来就分不清（差距在自己的一纸裕度之内），
      深一层换成哪一手都无所谓 ⇒ 这一层"加深"白花钱。
    · **真变招**：浅层**自信地**选错（差距远超自己的裕度），深一层才纠正 ⇒ 加深值钱。
  ⇒ 必须用「该层**自己**的判据裕度」当标尺，衡量它和更深一层的分歧有多大。

【核心指标 gap_ratio】
  设 L 层选 A、L+3 层选 B（都用 L 层的全宽榜单打分）：
      gap_L    = score_L(A) − score_L(B)     ← L 层"自己"认为 A 比 B 好多少
      margin_L = score_L(top1) − score_L(top2)   ← L 层榜首与次席之差 = 该层的判据裕度
      ratio    = gap_L / margin_L
    · ratio ≤ ~1  ⇒ **噪声变招**（分歧在自己裕度之内，加深无收益）
    · ratio ≫ 1  ⇒ **真变招**（自信选错，加深有收益）
  注意 gap_L ≤ 0 表示 L 层其实也认为 B 不差 ⇒ 同样是噪声。

【另一个必看的量：幻视（hallucination）】
  同一手在相邻两层的**绝对分**若相差一个量级（实测局面#1：9 plies 估值 4031、
  12 plies 只剩 52.83），说明浅层在**臆想一条必胜线** —— 这是地平线效应，
  属于"必须加深"的硬理由，跟裕度无关。单独统计。

跑法（本机，多进程）：
    python tests/_bench_ply_goldilocks.py --positions 16 --max 12 --workers 6
输出：tests/_bench_ply_gold.json + 屏上结论表
"""
import argparse
import copy
import json
import multiprocessing as mp
import os
import statistics as st
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRV = os.path.join(ROOT, "server")
for _p in (SRV, os.path.join(SRV, "engine")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

#: 每次生成局面时的自走手数档（覆盖开局/中局/残局，避免只在一种局面上取样）
WARM_TIERS = (6, 12, 20, 30, 40, 55)


def _warm():
    from agents.search_bot import _jit_warmup
    _jit_warmup()


def make_position(n_moves, seed):
    """低深度自走 N 手造真实中局（随机走子会失真，见旧脚本说明）。"""
    from agents.search_bot import SearchBot
    from engine import game_dxf as GA
    m = SearchBot(depth=2, time_limit=1.0, seed=seed)
    st = GA.new_game(first=1 + (seed % 3))
    for _ in range(n_moves):
        legal = GA.legal_moves(st, st["turn"])
        if not legal:
            GA._advance(st)
            continue
        mv = (m.choose(st, legal, "", GA.ARMY_CN[st["turn"]]) or {}).get("move")
        if not mv:
            break
        f, t = str(mv).split("-")[:2]
        GA.apply(st, f, t)
    return st


def ladder(state, max_plies, budget):
    """逐层搜上去。★ 把**每层的完整榜单**留下来 —— 这是算 gap 的前提。

    渐进加宽会让深层的榜单只含候选集，但浅层是全宽的：
      plies=3 时 ROOT_KEEP=99 ⇒ 覆盖全部合法着法（所以 `score_3(任意手)` 都有）。
    """
    from agents.search_bot import SearchBot, ROOT_KEEP
    from engine import game_dxf as GA
    me = state["turn"]
    legal = GA.legal_moves(state, me)
    board = copy.deepcopy(state["board"])
    bot = SearchBot(depth=max(1, max_plies // 3), time_limit=budget)
    bot._deadline = time.time() + budget
    bot.nodes = 0
    bot._ply = int(state.get("ply") or 0)
    bot._ur = 1.0 + bot._ply * bot.w.get("urgency", 0.0)
    cand, first, rows = list(legal), True, []
    for plies in range(3, max_plies + 1, 3):
        remain = bot._deadline - time.time()
        if remain <= 2.0:
            break
        t0 = time.time()
        mv, sc, ranked, nodes, aborted = bot._jit_search(
            board, me, plies, cand, remain, first)
        first = False
        dt = time.time() - t0
        row = {"plies": plies, "nodes": nodes, "sec": round(dt, 2),
               "aborted": bool(aborted),
               "mv": None if mv is None else f"{mv[0]}-{mv[1]}",
               "score": None if sc is None else round(float(sc), 2),
               # 完整榜单：[[from, to, score], ...]
               "ranked": [[f, t, round(float(s), 4)] for f, t, s in ranked]}
        rows.append(row)
        if aborted or mv is None:
            break
        keep = ROOT_KEEP.get(plies, 6)
        cand = [(f, t) for f, t, _s in ranked[:keep]]
    return rows, len(legal)


def _score_of(row, mv):
    for f, t, s in row["ranked"]:
        if f"{f}-{t}" == mv:
            return float(s)
    return None


def one_position(task):
    gi, warm, seed, max_plies, budget = task
    st = make_position(warm, seed)
    if not st["board"]:
        return None
    from engine import game_dxf as GA
    rows, nlegal = ladder(st, max_plies, budget)
    rec = {"idx": gi, "ply": st["ply"], "turn": st["turn"],
           "pieces": len(st["board"]), "legal": nlegal, "rows": rows}
    # ---- 逐对相邻深度算 gap / margin ----
    pairs = []
    byp = {r["plies"]: r for r in rows if r.get("mv")}
    for lo, hi in ((3, 6), (6, 9), (9, 12), (12, 15)):
        a, b = byp.get(lo), byp.get(hi)
        if not a or not b:
            continue
        mv_a, mv_b = a["mv"], b["mv"]
        sa, sb = _score_of(a, mv_a), _score_of(a, mv_b)
        rk = sorted(a["ranked"], key=lambda x: -x[2])
        m1 = rk[0][2] if rk else None
        m2 = rk[1][2] if len(rk) > 1 else None
        margin = (m1 - m2) if (m1 is not None and m2 is not None) else None
        if sa is None or sb is None:
            pairs.append({"lo": lo, "hi": hi, "mv_lo": mv_a, "mv_hi": mv_b,
                          "same": mv_a == mv_b, "comparable": False})
            continue
        gap = sa - sb
        ratio = (gap / margin) if (margin and abs(margin) > 1e-9) else None
        # 幻视：同一手在 lo/hi 两层的绝对分差（要同一手才能比）
        halluc = None
        if mv_a == mv_b:
            sb_h = _score_of(b, mv_a)
            if sb_h is not None:
                halluc = abs(sa - sb_h)
        pairs.append({"lo": lo, "hi": hi, "mv_lo": mv_a, "mv_hi": mv_b,
                      "same": mv_a == mv_b, "comparable": True,
                      "score_lo_at_lo": round(sa, 2),
                      "score_hi_at_lo": round(sb, 2),
                      "gap_at_lo": round(gap, 3),
                      "margin_lo": None if margin is None else round(margin, 4),
                      "ratio": None if ratio is None else round(ratio, 2),
                      "want_ratio": None if ratio is None else round(max(0.0, ratio), 2),
                      "halluc": None if halluc is None else round(halluc, 2)})
    rec["pairs"] = pairs
    return rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--positions", type=int, default=16)
    ap.add_argument("--max", type=int, default=12)
    ap.add_argument("--budget", type=float, default=400.0, help="每局面总预算")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--seed", type=int, default=20261001)
    ap.add_argument("--out", default=os.path.join(HERE, "_bench_ply_gold.json"))
    a = ap.parse_args()

    print("=" * 78)
    print(f"金发姑娘区实验：{a.positions} 个局面 × 逐层到 {a.max} plies   "
          f"{a.workers} 进程")
    print("=" * 78, flush=True)
    _warm()
    tasks = []
    for i in range(a.positions):
        warm = WARM_TIERS[i % len(WARM_TIERS)]
        tasks.append((i + 1, warm, a.seed + i * 7919, a.max, a.budget))
    t0 = time.time()
    with mp.get_context("fork" if "fork" in mp.get_all_start_methods() else None) \
            .Pool(a.workers) as pool:
        recs = [r for r in pool.map(one_position, tasks) if r]
    print(f"完成 {len(recs)} 个局面，用时 {time.time() - t0:.1f}s\n", flush=True)

    # ---------------- 汇总 ----------------
    print("=" * 96)
    print(f"{'局面':<5}{'ply':>5}{'子':>4}{'合法':>5}  "
          f"{'3':>9}{'6':>9}{'9':>9}{'12':>9}   相邻层是否变招")
    print("-" * 96)
    for r in recs:
        byp = {x["plies"]: x for x in r["rows"] if x.get("mv")}
        cells = []
        for L in (3, 6, 9, 12):
            cells.append(f"{byp[L]['mv']:>9}" if L in byp else f"{'-':>9}")
        ch = []
        for lo, hi in ((3, 6), (6, 9), (9, 12)):
            if lo in byp and hi in byp:
                ch.append(f"{lo}→{hi}:{'变' if byp[lo]['mv'] != byp[hi]['mv'] else '同'}")
        print(f"{r['idx']:<5}{r['ply']:>5}{r['pieces']:>4}{r['legal']:>5}  "
              + "".join(cells) + "   " + " ".join(ch))

    print("\n" + "=" * 96)
    print("逐对分析（gap_at_lo = lo 层自己认为「自己选的手」比「更深层选的手」好多少）")
    print("-" * 96)
    print(f"{'层':<20}{'变招次数':>9}{'可比对数':>9}{'噪声变招(ratio≤1)':>18}"
          f"{'真变招(ratio>1)':>16}{'中位 ratio':>12}")
    for lo, hi in ((3, 6), (6, 9), (9, 12)):
        ps = [p for r in recs for p in r["pairs"]
              if p["lo"] == lo and p["hi"] == hi and p.get("comparable")]
        changed = [p for p in ps if not p["same"]]
        noise = [p for p in changed if p["ratio"] is None or p["ratio"] <= 1.0]
        real = [p for p in changed if p["ratio"] is not None and p["ratio"] > 1.0]
        rt = [p["ratio"] for p in changed if p["ratio"] is not None]
        med = f"{st.median(rt):.2f}" if rt else "-"
        print(f"{str(lo) + ' → ' + str(hi) + ' plies':<20}{len(changed):>9}"
              f"{len(ps):>9}{len(noise):>18}{len(real):>16}{med:>12}")

    hs = [p for r in recs for p in r["pairs"]
          if p.get("halluc") is not None and p["halluc"] > 20]
    print(f"\n幻视（同一手在相邻两层绝对分差 > 20）：{len(hs)} 次")
    for p in hs[:8]:
        print(f"   {p['lo']}→{p['hi']} 手 {p['mv_lo']}："
              f"{p['score_lo_at_lo']:+.1f} → 更深层同手 {p['score_lo_at_lo'] - (p['gap_at_lo'] or 0):+.1f}")

    print("\n耗时（各层中位）")
    for L in (3, 6, 9, 12, 15):
        ss = [x["sec"] for r in recs for x in r["rows"] if x["plies"] == L]
        nn = [x["nodes"] for r in recs for x in r["rows"] if x["plies"] == L]
        if ss:
            print(f"   {L:>2} plies  中位 {st.median(ss):>8.2f}s   中位节点 "
                  f"{st.median(nn):>14,.0f}")

    with open(a.out, "w", encoding="utf-8") as f:
        json.dump({"args": vars(a), "records": recs}, f,
                  ensure_ascii=False, indent=1)
    print(f"\n原始数据 → {a.out}")


if __name__ == "__main__":
    main()
