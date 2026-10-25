# -*- coding: utf-8 -*-
"""12 plies 是否已饱和？—— 逐层搜索对照实验（老师 2026-10-01 提问）

老师原话：「如果 12 plies 已经饱和，我就没必要用最费时间最高档」

为什么必须实测、不能想当然：
  · "12 plies 饱和"这个说法只有在**同一局面下更深一层不改变选招**时才成立；
  · 我们已有的数据只有"耗时"（12 plies 42s、15 plies 约 10 分钟），
    **没有**"选招是否变化"的数据 —— 而那才是"饱和"的定义。

做法（一次搜索拿全部层的结果）：
  对每个局面，逐层调用 JIT 内核（3 → 6 → 9 → 12 → 15），
  记下**每一层选出的着法**，然后看：
    ① 相邻层之间选招有没有变（变了几次、在第几层变的）
    ② 12 层选的招，在 15 层的根着法榜单（ranked）里排第几、分数差多少
    ③ 每层的节点数与耗时（复核"12→15 放大 8~27 倍"这个旧结论）

跑法：
  cd server && python ../tests/_bench_ply_saturation.py --games 2 --max 15 --budget 900
  （--max 12 先跑快版；--max 15 才是完整口径）
输出：tests/_bench_ply_sat.json（逐层原始数据）+ 屏上表格
"""
import argparse
import copy
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "server"))

from agents.search_bot import SearchBot, ROOT_KEEP, _jit_warmup   # noqa: E402
from engine import game_dxf as GA                                 # noqa: E402

AP = argparse.ArgumentParser()
AP.add_argument("--games", type=int, default=2, help="局面数")
AP.add_argument("--max", type=int, default=15, help="逐层跑到几 plies")
AP.add_argument("--budget", type=float, default=900.0, help="每个局面的总时间上限（秒）")
AP.add_argument("--warm", type=int, default=24, help="自走多少手来制造中局局面")
AP.add_argument("--seed", type=int, default=20261001)
AP.add_argument("--out", default=os.path.join(HERE, "_bench_ply_sat.json"))
A = AP.parse_args()


def make_position(n_moves, seed):
    """用低深度搜索自走 N 手，造一个**真实合理的**中局局面。

    ⚠️ 不用随机走子：随机局面子力位置混乱，分支数与耗时都失真，
       测出来的"饱和点"不能代表老师实战遇到的局面。
    """
    m = SearchBot(depth=2, time_limit=1.0, seed=seed)
    st = GA.new_game(first=1 + (seed % 3))    # 起手方轮换，避免固定"魏先动"偏差
    for _ in range(n_moves):
        legal = GA.legal_moves(st, st["turn"])
        if not legal:
            GA._advance(st)
            legal = GA.legal_moves(st, st["turn"])
            if not legal:
                break
        res = m.choose(st, legal, "", GA.ARMY_CN[st["turn"]])
        mv = res.get("move")
        if not mv:
            break
        f, t = mv.split("-")[0], mv.split("-")[1]
        GA.apply(st, f, t)
    return st


def ladder(state, max_plies, budget):
    """逐层搜上去，返回每层的 {plies, move, score, nodes, sec, aborted, ranked}"""
    me = state["turn"]
    legal = GA.legal_moves(state, me)
    # ★防御性拷贝：`_choose` 里也用 `board = dict(state["board"])` ——
    #   dict 的插入顺序会被 pop/回填打乱，浮点末位差会让 alpha-beta 的相等比较翻转。
    board = copy.deepcopy(state["board"])
    bot = SearchBot(depth=max(1, max_plies // 3), time_limit=budget)
    bot._deadline = time.time() + budget
    bot.nodes = 0
    bot._ply = int(state.get("ply") or 0)
    bot._ur = 1.0 + bot._ply * bot.w.get("urgency", 0.0)
    cand = list(legal)
    first = True
    rows = []
    for plies in range(3, max_plies + 1, 3):
        remain = bot._deadline - time.time()
        if remain <= 1.0:
            rows.append({"plies": plies, "aborted": True, "reason": "预算用尽"})
            break
        t0 = time.time()
        mv, sc, ranked, nodes, aborted = bot._jit_search(
            board, me, plies, cand, remain, first)
        first = False
        dt = time.time() - t0
        row = {"plies": plies, "nodes": nodes, "sec": round(dt, 2),
               "aborted": bool(aborted),
               "mv": None if mv is None else f"{mv[0]}-{mv[1]}",
               "score": None if sc is None else round(float(sc), 2)}
        if mv is not None and not aborted:
            keep = ROOT_KEEP.get(plies, 6)
            row["ranked"] = [[f, t, round(float(s), 2)] for f, t, s in ranked[:keep + 4]]
            cand = [(f, t) for f, t, _s in ranked[:keep]]
        rows.append(row)
        print(f"      {plies:>2} plies  mv={row['mv']}  score={row['score']}  "
              f"nodes={nodes:,}  {dt:.1f}s" + ("  [aborted]" if aborted else ""))
        if aborted or mv is None:
            break
    return rows


def main():
    print("=" * 78)
    print(f"12 plies 饱和性对照实验：games={A.games} 逐层到 {A.max} plies  "
          f"预算 {A.budget:.0f}s/局面")
    print("=" * 78)
    print("  [numba] 预热中…")
    _jit_warmup()
    print("  [numba] 预热完成")

    all_games = []
    for gi in range(A.games):
        print(f"\n--- 局面 #{gi + 1}（自走 {A.warm} 手制造中局）---")
        st = make_position(A.warm, A.seed + gi * 7919)
        n_legal = len(GA.legal_moves(st, st["turn"]))
        print(f"      轮到 {GA.ARMY_CN[st['turn']]}方，ply={st['ply']}，"
              f"子力 {len(st['board'])} 枚，合法着法 {n_legal} 条")
        t0 = time.time()
        rows = ladder(st, A.max, A.budget)
        all_games.append({
            "idx": gi + 1, "ply": st["ply"], "turn": st["turn"],
            "pieces": len(st["board"]), "legal": n_legal,
            "rows": rows, "total_sec": round(time.time() - t0, 2),
        })
        print(f"      小计：{time.time() - t0:.1f}s")

    # ---------------- 汇总 ----------------
    print("\n" + "=" * 78)
    print("汇总")
    print("=" * 78)
    for g in all_games:
        rows = [r for r in g["rows"] if r.get("mv")]
        chain = " → ".join(f"{r['plies']}:{r['mv']}" for r in rows)
        print(f"  局面#{g['idx']}（ply={g['ply']}，{g['pieces']} 子）：{chain}")
        # 相邻层是否变招
        changes = [f"{rows[i]['plies']}→{rows[i+1]['plies']}"
                   for i in range(len(rows) - 1)
                   if rows[i]["mv"] != rows[i + 1]["mv"]]
        print(f"      变招发生在：{changes if changes else '（全程未变）'}")
        # 12 → 之后的层
        r12 = next((r for r in rows if r["plies"] == 12), None)
        deepest = rows[-1] if rows else None
        if r12 and deepest and deepest["plies"] > 12:
            same = r12["mv"] == deepest["mv"]
            print(f"      12 plies 选 {r12['mv']}，{deepest['plies']} plies 选 "
                  f"{deepest['mv']} ⇒ {'相同' if same else '**不同**'}")
            rk = deepest.get("ranked") or []
            pos = next((i + 1 for i, x in enumerate(rk)
                        if f"{x[0]}-{x[1]}" == r12["mv"]), None)
            if pos and rk:
                d = rk[0][2] - next((x[2] for x in rk
                                     if f'{x[0]}-{x[1]}' == r12["mv"]), 0)
                print(f"      12 选的那手在 {deepest['plies']} plies 榜单里排第 "
                      f"{pos}/{len(rk)}，与榜首差 {d:+.2f} 分")
        # 耗时放大
        for i in range(len(rows) - 1):
            a, b = rows[i], rows[i + 1]
            if a["sec"] > 0.05:
                print(f"      {a['plies']}→{b['plies']} plies："
                      f"{a['sec']:.1f}s → {b['sec']:.1f}s（×{b['sec'] / a['sec']:.1f}），"
                      f"节点 ×{b['nodes'] / max(a['nodes'], 1):.1f}")

    with open(A.out, "w", encoding="utf-8") as f:
        json.dump({"args": vars(A), "games": all_games}, f,
                  ensure_ascii=False, indent=1)
    print(f"\n原始数据已写：{A.out}")


if __name__ == "__main__":
    main()
