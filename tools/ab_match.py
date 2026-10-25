# -*- coding: utf-8 -*-
"""价值网络**配方** A/B 对局台 —— 三人象棋专用的"一局三配置 + 座位轮转"设计。

【为什么不能像两人棋那样跑两批】
  三人象棋不是零和两人博弈：胜率被**座位耦合**严重污染 ——
  谁坐在"下游"（能被两家夹击的位置）、谁先手，对结果的影响可能远大于
  权重配方的差别。跑"第一批全用 A、第二批全用 B"，两批局面完全不同，
  胜率差里混着运气，几十局根本看不出来。

【本设计：同局三配置 + 轮转】
  一局里三个座位**各用一种配置**（天然对称：同一局面、同一对手、同一随机扰动）。
  再让三种配置**轮转坐遍三个座位**（同基础 seed，每 3 局一组）
  ⇒ 座位耦合、先手优势被完全对称化，剩下的差值才是"配方本身"。

      组 grp：  基础 seed = seed0 + grp
      局 g：    rot = g % 3      座位 army(1魏/2吴/3蜀) 用 cfg[(army-1+rot) % 3]

      局 0 (rot=0):  魏=C0  吴=C1  蜀=C2
      局 1 (rot=1):  魏=C1  吴=C2  蜀=C0
      局 2 (rot=2):  魏=C2  吴=C0  蜀=C1

【指标】
  win    成为最终 winner（存活到最后/分数最高）
  alive  终局仍存活
  slay   斩掉对方**主帅**的次数（`note["eliminated"]`，副帅不算 —— 见 game_dxf.apply）
  fed    自己被斩帅的次数
  mat    吃子收益（累计，按 rules_dxf.VALUE 计价）

【配对裁决】
  单看胜率噪声大。更有力的是**配对符号检验**：对每对 (X, Y)，
  统计"X 赢而 Y 没赢"与"Y 赢而 X 没赢"的局数，做二项检验
  ⇒ 即便绝对胜率都很低，只要 X 系统性压过 Y，也能判出来。

用法：
  python tools/ab_match.py --games 300 --workers 6 --tl 0.2 --depth 1 \\
      --cfg none=- --cfg offi=value_mlp.json --cfg bal=value_mlp_bal.json \\
      --out _对照实验/ab_r1.json

  `--cfg 标签=权重文件[:λ]`
    · 权重文件写 `-` 或留空 = **关闭**价值网络（纯搜索基线）
    · `:λ` 可选，**按配置覆盖**混合系数 —— 用来扫"到底是配方差还是 λ 太大"
      例：`--cfg offi=\\-` 太麻烦，直接 `--cfg offi=value_mlp.json:0.15`
  可给 2 或 3 个；给 2 个会自动补一个 `none` 基线。`--games` 取 3 的倍数。
"""
import argparse
import json
import math
import multiprocessing as mp
import os
import random
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)                     # 项目根
sys.path.insert(0, os.path.join(ROOT, "server"))

ARMY_CN = {1: "魏", 2: "吴", 3: "蜀"}

#: 子力价值 —— **必须与引擎同源**（rules_dxf.VALUE），否则 `mat` 指标不可比
VALUE = {"general": 1000.0, "rook": 9.0, "cannon": 4.5, "horse": 4.0,
         "elephant": 2.0, "advisor": 2.0, "pawn": 1.0}

#: 同进程内按 (权重文件, λ) 缓存顾问 —— 每局重建 bot 会重复解析 3.5MB JSON
_ADV_CACHE = {}


def _advisor(key, path, enabled, lam):
    """按 (文件, 开关, λ) 缓存 ValueAdvisor。"""
    if key in _ADV_CACHE:
        return _ADV_CACHE[key]
    from agents import value_advisor as VA
    if not enabled:
        adv = VA.ValueAdvisor(model=None, names=[], kind="", lam=lam,
                              enabled=False, path="")
    else:
        adv = VA.ValueAdvisor.load(kind="mlp", lam=lam, enabled=True, path=path)
    _ADV_CACHE[key] = adv
    return adv


def _play_one(task):
    """跑一局。返回该局每个配置的表现。

    task = (g, cfgs, tl, depth, maxply, seed0)
      cfgs = [{"tag","file","lam"}, ...]
    """
    g, cfgs, tl, depth, maxply, seed0 = task
    from engine import game_dxf as GA
    from agents.search_bot import SearchBot

    rot = g % 3
    grp = g // 3
    base = seed0 + grp                          # 同组三局共享基础 seed
    rng = random.Random(base * 7919)
    s = GA.new_game(first=1)                    # first 固定：轮转已让每个 cfg 都坐过先手位

    # 座位 → 配置
    seat = {a: cfgs[(a - 1 + rot) % 3] for a in (1, 2, 3)}
    bots = {}
    for a in (1, 2, 3):
        c = seat[a]
        bot = SearchBot(depth=depth, time_limit=tl, seed=base * 17 + a,
                        label=c["tag"], use_value=False)
        # 直接注入缓存好的顾问（绕过 SearchBot 的懒加载，避免每局重读权重）
        bot._adv = _advisor((c["file"] or "", c["file"] is not None, c["lam"]),
                            c["file"] or "", c["file"] is not None, c["lam"])
        bots[a] = bot

    # 每配置的本局表现
    #   ★ `mv`/`short`/`l0` 是 2026-10-02 新增的**健康度计数**，起因见文件头那段。
    stat = {c["tag"]: {"win": 0, "alive": 0, "slay": 0, "fed": 0, "mat": 0.0,
                       "plies": 0, "mv": 0, "short": 0, "l0": 0, "seats": []}
            for c in cfgs}
    for a in (1, 2, 3):
        stat[seat[a]["tag"]]["seats"].append(a)

    plies_target = int(depth) * 3
    n_skip = 0
    for _ in range(maxply):
        if s.get("winner") is not None:
            break
        cur = s["turn"]
        legal = GA.legal_moves(s, cur)
        if not legal:
            n_skip += 1
            GA._advance(s)
            if n_skip > 12:                     # 全员停走 ⇒ 卡死，认作平局
                break
            continue
        n_skip = 0
        r = bots[cur].choose(s, legal, "", ARMY_CN[cur])
        mv = (r or {}).get("move")
        legal0_hit = False
        if not mv or tuple(str(mv).split("-")) not in legal:
            frm, to = legal[rng.randrange(len(legal))]
        else:
            frm, to = str(mv).split("-")
        tag = seat[cur]["tag"]
        # ---- 健康度：这一步搜索是否被时间切断 / 是否退化成 legal[0] ----
        #   动机：`tl=0.02` 那次的教训（铁律 155）——"整层超时作废"会让着法
        #   定死成 `legal[0]`（与局面无关），而**外部只看胜负是看不出来的**。
        #   A/B 跑在 15 核配额被 throttle 82% 的机器上（`cpu.stat` 实测），
        #   时间切断完全可能按"谁的计算贵"差异化发生 ⇒ 必须显式计数。
        st = stat[tag]
        st["mv"] += 1
        li = getattr(bots[cur], "last_info", None) or {}
        if int(li.get("plies", -1)) < plies_target:
            st["short"] += 1
        if len(legal) > 1 and (frm, to) == tuple(legal[0]):
            legal0_hit = True
            st["l0"] += 1
        try:
            note = GA.apply(s, frm, to)
        except Exception:                       # noqa: BLE001
            frm, to = legal[rng.randrange(len(legal))]
            note = GA.apply(s, frm, to)
        if note.get("captured"):
            stat[tag]["mat"] += VALUE.get(note["captured"], 0.0)
        if note.get("eliminated"):              # 真·主帅被斩（副帅不算）
            stat[tag]["slay"] += 1
            victim = note["eliminated"]
            stat[seat[victim]["tag"]]["fed"] += 1

    win = s.get("winner")
    alive = GA.alive_armies(s)
    for a in alive:
        stat[seat[a]["tag"]]["alive"] += 1
    if win is not None:
        stat[seat[win]["tag"]]["win"] += 1
    for t in stat:
        stat[t]["plies"] = s["ply"]

    return {"g": g, "ply": s["ply"], "winner_tag": None if win is None else seat[win]["tag"],
            "winner_army": win, "alive_tags": [seat[a]["tag"] for a in alive],
            "draw": win is None, "tie_dead": bool(win is None and s["ply"] >= maxply),
            "stat": stat}


def _worker(task):
    return _play_one(task)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cfg", action="append", default=[],
                    help="标签=权重文件[:λ]（`-` = 关闭价值网络）。可重复 2~3 次")
    ap.add_argument("--games", type=int, default=300, help="总局数（取 3 的倍数）")
    ap.add_argument("--workers", type=int, default=8, help="并行进程数")
    ap.add_argument("--tl", type=float, default=5.0,
                    help="单步搜索时间上限（秒）。★默认 5.0 = **形同不限制**："
                         "depth=1 只需 3 plies，正常 0.05s 就跑完；"
                         "给到 5s 是为了让'容器被 throttle'不改变结果（见健康度一栏）")
    ap.add_argument("--depth", type=int, default=1, help="搜索层数（1 = 3 plies，对弈台入门档）")
    ap.add_argument("--maxply", type=int, default=300, help="单局最大手数")
    ap.add_argument("--lam", type=float, default=0.35, help="默认混合系数（可被 --cfg 的 :λ 覆盖）")
    ap.add_argument("--threads", type=int, default=1, help="每进程 torch 线程数")
    ap.add_argument("--seed0", type=int, default=2_000_000, help="基础 seed 起点（换一批局面用）")
    ap.add_argument("--out", default="ab_report.json", help="报告输出路径")
    a = ap.parse_args()

    # ---- 配置解析 ----
    if not a.cfg:
        a.cfg = ["none=-", "offi=value_mlp.json", "bal=value_mlp_bal.json"]
    cfgs = []
    for item in a.cfg:
        if "=" not in item:
            sys.exit(f"✗ --cfg 格式应为 标签=文件[:λ]，收到 {item!r}")
        tag, rest = item.split("=", 1)
        tag, rest = tag.strip(), rest.strip()
        lam_ov = None
        if rest not in ("", "-") and ":" in rest:
            rest, lam_s = rest.rsplit(":", 1)
            try:
                lam_ov = float(lam_s)
            except ValueError:
                sys.exit(f"✗ λ 解析失败：{lam_s!r}（应形如 value_mlp.json:0.2）")
        cfgs.append({"tag": tag, "file": None if rest in ("", "-") else rest,
                     "lam": a.lam if lam_ov is None else lam_ov})
    while len(cfgs) < 3:                        # 不足三个 ⇒ 补纯搜索基线
        cfgs.append({"tag": f"none{len(cfgs)}", "file": None, "lam": a.lam})
    if len(cfgs) > 3:
        sys.exit("✗ 最多 3 个配置（三人象棋三个座位）")
    if len({c["tag"] for c in cfgs}) != 3:
        sys.exit("✗ 标签必须互不相同")
    games = (a.games // 3) * 3
    if games < 3:
        sys.exit("✗ --games 至少 3")

    tasks = [(g, cfgs, a.tl, a.depth, a.maxply, a.seed0) for g in range(games)]

    print("=" * 78)
    print(f"配方 A/B/C 对局台   局数={games}（{games // 3} 组 × 3 轮转）")
    print(f"   搜索 depth={a.depth}（{a.depth * 3} plies）  tl={a.tl}s  "
          f"最大手数={a.maxply}  进程={a.workers}")
    for i, c in enumerate(cfgs):
        print(f"   座次{i}：{c['tag']:<8} 权重={c['file'] or '（纯搜索，无价值网络）'}"
              f"  λ={c['lam']:g}")
    print("=" * 78, flush=True)

    t0 = time.time()
    results = []
    if a.workers <= 1:
        for i, tk in enumerate(tasks):
            results.append(_worker(tk))
            if (i + 1) % max(1, games // 10) == 0:
                print(f"   … {i + 1}/{games} 局  {time.time() - t0:.0f}s", flush=True)
    else:
        with mp.Pool(a.workers, initializer=_init_threads,
                     initargs=(a.threads,)) as pool:
            for i, r in enumerate(pool.imap_unordered(_worker, tasks, chunksize=1)):
                results.append(r)
                if (i + 1) % max(1, games // 10) == 0:
                    print(f"   … {i + 1}/{games} 局  {time.time() - t0:.0f}s", flush=True)
    secs = time.time() - t0

    # ---------------- 汇总 ----------------
    tags = [c["tag"] for c in cfgs]

    def _sc(r, t):
        """★ 序数得分（2026-10-02 新增）：赢=2 / 存活但没赢=1 / 被斩出局=0。

        为什么需要它：本设计判和率高达 33~55%（三人棋互相牵制，常打不动）。
        只看 `win` 等于**扔掉一半以上的数据**。
        而判和局里三方仍有明确优劣（谁还活着、谁被斩了）⇒ 序数分把它们救回来。
        ⇒ 这是"用更多信息换更小噪声"，比单纯堆局数便宜得多。
        """
        if r["winner_tag"] == t:
            return 2
        return 1 if t in r["alive_tags"] else 0

    agg = {t: {"win": 0, "alive": 0, "slay": 0, "fed": 0, "mat": 0.0,
               "score": 0.0, "mv": 0, "short": 0, "l0": 0} for t in tags}
    draws = 0
    ply_sum = 0
    for r in results:
        ply_sum += r["ply"]
        if r["draw"]:
            draws += 1
        for t, v in r["stat"].items():
            for k in agg[t]:
                if k != "score":
                    agg[t][k] += v[k]
        for t in tags:
            agg[t]["score"] += _sc(r, t)

    def _se(p):
        return math.sqrt(max(p * (1 - p), 1e-9) / games)

    print("\n" + "=" * 78)
    print(f"  用时 {secs:.0f}s   平均 {ply_sum / max(len(results), 1):.0f} 手/局   "
          f"判和 {draws}/{len(results)}（{100.0 * draws / max(len(results), 1):.0f}%）")
    print("=" * 78)
    print(f"  {'配置':<10}{'胜':>5}{'胜率':>9}{'存活':>7}{'存活率':>9}"
          f"{'序数分':>8}{'均分':>7}{'斩帅':>6}{'被斩':>6}{'吃子收益':>11}")
    for t in tags:
        v = agg[t]
        wr = v["win"] / games
        ar = v["alive"] / games
        print(f"  {t:<10}{v['win']:>5}{wr:>8.1%}±{_se(wr):.1%}"
              f"{v['alive']:>7}{ar:>8.1%}{v['score']:>8.0f}{v['score'] / games:>7.3f}"
              f"{v['slay']:>6}{v['fed']:>6}{v['mat']:>11.1f}")

    # ---- ★ 健康度：搜索有没有被时间切断 / 退化 -----
    #   这是**方法论的守门人**：如果 `short` 或 `l0` 不可忽略，本次对局的胜负
    #   就掺了"机器繁忙度"这个混杂变量，结论不能用来裁决权重。
    tot_mv = sum(v["mv"] for v in agg.values())
    tot_short = sum(v["short"] for v in agg.values())
    tot_l0 = sum(v["l0"] for v in agg.values())
    print(f"\n  健康度（搜索是否被时间切断）：全场合计 {tot_mv} 手，"
          f"未跑满 {tot_short}（{100.0 * tot_short / max(tot_mv, 1):.2f}%），"
          f"退化成 legal[0] {tot_l0}（{100.0 * tot_l0 / max(tot_mv, 1):.2f}%）")
    print(f"  {'配置':<10}{'出手':>8}{'未跑满':>8}{'占比':>8}{'走legal0':>10}{'占比':>8}")
    for t in tags:
        v = agg[t]
        print(f"  {t:<10}{v['mv']:>8}{v['short']:>8}"
              f"{100.0 * v['short'] / max(v['mv'], 1):>7.2f}%"
              f"{v['l0']:>10}{100.0 * v['l0'] / max(v['mv'], 1):>7.2f}%")
    if tot_short / max(tot_mv, 1) > 0.01:
        print("  ⚠ 未跑满 >1% ⇒ 本次结果受机器负载污染，**不能**用来裁决权重"
              "（建议 --tl 加到 5.0 重跑）")

    # ---- 配对符号检验 ----
    print("\n  配对裁决（逐局配对，三家都没得分差的局不计）")
    print(f"  {'对比':<20}{'胜X':>5}{'胜Y':>5}{'p(胜)':>9}"
          f"{'分X':>6}{'分Y':>6}{'p(序数)':>10}   结论")
    pairs = []

    def _binom_p(nx, ny):
        n = nx + ny
        if n == 0:
            return 1.0
        k = min(nx, ny)
        return min(1.0, 2.0 * sum(math.comb(n, m) for m in range(k + 1)) / (2 ** n))

    for i in range(3):
        for j in range(i + 1, 3):
            X, Y = tags[i], tags[j]
            # (a) 只看"谁赢"（传统口径，判和局被丢掉）
            nx = sum(1 for r in results if r["winner_tag"] == X)
            ny = sum(1 for r in results if r["winner_tag"] == Y)
            p_win = _binom_p(nx, ny)
            # (b) ★ 序数得分逐局配对（判和局也参与，效力更高）
            bx = sum(1 for r in results if _sc(r, X) > _sc(r, Y))
            by = sum(1 for r in results if _sc(r, Y) > _sc(r, X))
            p_ord = _binom_p(bx, by)
            if min(bx, by) + max(bx, by) < 10:
                verdict = "—"
            elif p_ord < 0.05:
                verdict = f"{X if bx > by else Y} 强（序数）"
            elif p_win < 0.05:
                verdict = f"{X if nx > ny else Y} 强（仅胜率）"
            else:
                verdict = "无显著差异"
            print(f"  {X + ' vs ' + Y:<20}{nx:>5}{ny:>5}{p_win:>9.3f}"
                  f"{bx:>6}{by:>6}{p_ord:>10.3f}   {verdict}")
            pairs.append({"x": X, "y": Y, "n_x": nx, "n_y": ny, "p_win": round(p_win, 4),
                          "bx": bx, "by": by, "p_ord": round(p_ord, 4),
                          "verdict": verdict})

    report = {"games": games, "secs": round(secs, 1), "cfg": cfgs,
              "depth": a.depth, "plies": a.depth * 3, "tl": a.tl,
              "maxply": a.maxply, "seed0": a.seed0,
              "ply_mean": round(ply_sum / max(len(results), 1), 1),
              "draws": draws, "agg": agg, "pairs": pairs,
              "per_game": results}
    out = a.out if os.path.isabs(a.out) else os.path.join(ROOT, a.out)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)
    print(f"\n  报告已写 → {out}")
    return 0


def _init_threads(n):
    try:
        import torch
        torch.set_num_threads(max(1, int(n)))
    except Exception:                           # noqa: BLE001
        pass


if __name__ == "__main__":
    sys.exit(main())
