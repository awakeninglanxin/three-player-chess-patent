# -*- coding: utf-8 -*-
"""把 `_bench_ply_gold.json` 汇总成「金发姑娘区」结论表。

    python tests/_analyze_gold.py

【它回答什么】
  老师 2026-10-01：「搜索树层级能否再优化，不一定要到 15 plies，
  找到一个金发姑娘区、智力饱和点，去推荐给人类下一步建议。」

【判据（不是拍脑袋，是拿"该层自己的判据裕度"当标尺）】
  在**低层**看：榜首与次席的分差 `gap_at_lo`；
  同一层里"肉眼同级"的两手分差中位数 = **噪声地板** `margin_lo`
  （引擎给的 `margin_lo` 就是这个）。于是

      ratio = gap_at_lo / margin_lo
      ratio ≤ 1  ⇒  榜首并不比次席突出 ⇒ 加深后变招 = **噪声变招**（加深无收益）
      ratio ≫ 1  ⇒  榜首是真突出      ⇒ 加深后变招 = **真变招**（加深值钱）

  再配一个独立信号 `halluc`（幻视）：同一手在两层的绝对分差。
  分制在不同层不可比（地平线效应），所以只看"变没变、变得有没有道理"。

【输出】
  ① 相邻层对（3→6 / 6→9 / 9→12）的变招率、真/噪声拆分、耗时与节点中位数；
  ② 每个局面的逐层榜单首位变化；
  ③ 一句落点建议（HINT_PLIES / HINT_BUDGET 该给哪几档）。
"""
import json
import os
import statistics as st
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "_bench_ply_gold.json")


def med(xs):
    xs = [x for x in xs if x is not None]
    return round(st.median(xs), 3) if xs else None


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else SRC
    d = json.load(open(src, encoding="utf-8"))
    recs = d["records"]
    print("=" * 78)
    print(f"金发姑娘区汇总   源={os.path.basename(src)}   局面 {len(recs)} 个   "
          f"参数 {d['args']}")
    print("=" * 78)

    # ---------------- ① 每个局面的逐层概况 ----------------
    print("\n【一】逐局面：各层耗时 / 节点 / 榜首")
    print(f"{'#':>3} {'子力':>4} {'合法':>4} | "
          + " | ".join(f"{p:>2}plies" for p in (3, 6, 9, 12)))
    for r in recs:
        cells = []
        for row in r["rows"]:
            # ⚠️ 被预算掐断的那层 `mv=None`（aborted=True）——不能直接格式化
            mv = row["mv"] or ("—超时—" if row.get("aborted") else "—")
            sec = row.get("sec")
            cells.append(f"{mv:>8} {'n/a' if sec is None else f'{sec:.2f}s':>7}")
        print(f"{r['idx']:>3} {r['pieces']:>4} {r['legal']:>4} | " + " | ".join(cells))

    # ---------------- ② 相邻层对聚合 ----------------
    print("\n【二】相邻层对：变招 / 真变招 / 噪声变招 / 耗时 / 节点")
    print(f"{'层对':>8} {'变招':>6} {'真':>4} {'噪声':>5} "
          f"{'中位ratio':>10} {'幻视':>5} {'耗时中位(s)':>12} {'节点中位':>12}")
    detail = {}
    for lo, hi in ((3, 6), (6, 9), (9, 12)):
        n = same = real = noise = hall = 0
        ratios, secs, nodes = [], [], []
        for r in recs:
            pr = next((p for p in r.get("pairs", [])
                       if p["lo"] == lo and p["hi"] == hi), None)
            # ⚠️ 高层被预算掐断时 `ratio=None`（低层没分可比）⇒ 不能参与比值判断
            if not pr or not pr.get("comparable") or pr.get("ratio") is None:
                continue
            n += 1
            if pr["same"]:
                same += 1
            else:
                if pr["ratio"] > 1.0:
                    real += 1
                else:
                    noise += 1
            ratios.append(pr["ratio"])
            if abs(pr.get("halluc") or 0) > 20:
                hall += 1
        for r in recs:
            for row in r["rows"]:
                if row["plies"] == hi:
                    secs.append(row["sec"])
                    nodes.append(row["nodes"])
        detail[(lo, hi)] = dict(n=n, changed=n - same, real=real, noise=noise,
                                hall=hall, ratio_med=med(ratios),
                                sec_med=med(secs), nodes_med=med(nodes))
        print(f"{lo:>4}→{hi:<3} {n - same:>6} {real:>4} {noise:>5} "
              f"{med(ratios):>10} {hall:>5} {med(secs):>12} {med(nodes):>12}")

    # ---------------- ③ 落点建议 ----------------
    print("\n【三】落点建议")
    rows = []
    for r in recs:
        for row in r["rows"]:
            rows.append((row["plies"], row["sec"], row["nodes"]))
    for p in (3, 6, 9, 12):
        ss = [s for q, s, _ in rows if q == p]
        nn = [x for q, _, x in rows if q == p]
        if ss:
            print(f"  {p:>2} plies：耗时中位 {med(ss):>7.2f}s   "
                  f"节点中位 {med(nn):>10,.0f}")

    print("\n  解读：")
    for (lo, hi), v in detail.items():
        if not v["n"]:
            continue
        rate = (v["n"] - v["changed"]) / v["n"]
        noise_share = v["noise"] / max(1, v["changed"])
        verdict = ("加深**无收益**（变招多半是噪声）" if noise_share >= 0.4
                   else "加深**值钱**（变招多半是真变招）")
        print(f"   {lo}→{hi}：变招 {v['changed']}/{v['n']}，"
              f"其中噪声占 {noise_share:.0%} ⇒ {verdict}")
    print("=" * 78)


if __name__ == "__main__":
    main()
