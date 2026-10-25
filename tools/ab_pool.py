# -*- coding: utf-8 -*-
"""把多组 A/B 报告的 `per_game` 合起来，裁决「锚点对」是否**跨组稳定**。

★ 为什么需要它（2026-10-02 血的教训）
  当天早先是两组 A/B（第三方分别是 `bal` / `osml`），对同一对 `none vs offi`
  给出**相反**结论：
      组1： none 18.3% vs offi 36.3%  p<0.0001  ⇒ offi 强
      组2： none 12.3% vs offi 13.3%  p=0.820   ⇒ 无差异
  而 `none` 是**同一个配置**，两组胜率却差 6 个百分点，唯一差别是"第三方是谁"。
  ⇒ 三人棋里「A 比 B 强」不是绝对命题，**强依赖第三方**；
    单组 200~300 局的噪声远大于两人棋（判和率高达 33~55%）。

  所以本工具要回答的**不是**"再算一遍 p 值"，而是：

      **这个优势在 K 个不同第三方下，方向一致吗？**

  一致 ⇒ 可以据此上线；方向摇摆 ⇒ 差距小于"对手构成"带来的扰动，不许上线。

用法
----
    python tools/ab_pool.py --pair offi none _对照实验/ab_G1.json _对照实验/ab_G2.json ...
    python tools/ab_pool.py _对照实验/ab_G*.json          # 默认 pair = offi none

指标口径（与 ab_match.py 一致）
--------------------------------
    score = 赢 2 / 存活但没赢 1 / 被斩出局 0
    配对检验 = 逐局比较两家的 score，符号检验（二项双侧）——
              判和局也参与 ⇒ 效力远高于"只看谁赢"
"""
import argparse
import json
import math
import os
import sys


def sc(r, t):
    if r["winner_tag"] == t:
        return 2
    return 1 if t in r["alive_tags"] else 0


def binom_p(nx, ny):
    n = nx + ny
    if n == 0:
        return 1.0
    k = min(nx, ny)
    return min(1.0, 2.0 * sum(math.comb(n, m) for m in range(k + 1)) / (2 ** n))


def tags_of(d):
    """取报告的配置标签集合。

    ⚠️ 兼容两种历史格式：早期 `cfg: [["none", null], …]`（数组），
       后来 `cfg: [{"tag":…, "file":…, "lam":…}, …]`（对象）。
       不兼容的话老报告会直接 KeyError，而"拿新工具跑老数据"恰恰是常见需求。
    """
    out = set()
    for c in d["cfg"]:
        out.add(c["tag"] if isinstance(c, dict) else c[0])
    return out


def fisher(ps):
    """Fisher 合并（卡方近似）：chi2 = -2Σln p，df = 2k。

    没有 scipy ⇒ 用 Wilson–Hilferty 近似卡方上尾，足够判"是不是整体有信号"。
    """
    ps = [p for p in ps if p > 0]
    if not ps:
        return 1.0
    chi2 = -2.0 * sum(math.log(p) for p in ps)
    df = 2 * len(ps)
    # Wilson–Hilferty：把卡方近似成正态
    z = ((chi2 / df) ** (1.0 / 3.0) - (1.0 - 2.0 / (9.0 * df))) / math.sqrt(2.0 / (9.0 * df))
    # 单侧上尾
    return 0.5 * math.erfc(z / math.sqrt(2.0))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+", help="ab_match.py 产出的报告 JSON（可多个）")
    ap.add_argument("--pair", nargs=2, default=["offi", "none"],
                    metavar=("A", "B"), help="要裁决的锚点对（默认 offi none）")
    ap.add_argument("--pair2", nargs=2, default=None,
                    metavar=("A", "B"), help="可选：再裁决一对")
    a = ap.parse_args()
    A, B = a.pair

    groups = []
    for f in a.files:
        if not os.path.exists(f):
            print(f"  ⚠ 跳过（不存在）：{f}")
            continue
        with open(f, encoding="utf-8") as fh:
            groups.append((os.path.basename(f), json.load(fh)))
    if not groups:
        sys.exit("✗ 没有可用的报告")

    def judge(pair, quiet=False):
        X, Y = pair
        tot = {"gx": 0, "gy": 0, "wx": 0, "wy": 0, "n": 0}
        rows = []
        for name, d in groups:
            pg = d["per_game"]
            tags = tags_of(d)
            if X not in tags or Y not in tags:
                rows.append((name, None))
                continue
            gx = sum(1 for r in pg if sc(r, X) > sc(r, Y))
            gy = sum(1 for r in pg if sc(r, Y) > sc(r, X))
            wx = sum(1 for r in pg if r["winner_tag"] == X)
            wy = sum(1 for r in pg if r["winner_tag"] == Y)
            third = sorted(tags - {X, Y})
            rows.append((name, dict(n=len(pg), gx=gx, gy=gy, wx=wx, wy=wy,
                                    p_ord=binom_p(gx, gy), p_win=binom_p(wx, wy),
                                    third=third[0] if third else "-",
                                    draw=d.get("draws", 0))))
            tot["gx"] += gx; tot["gy"] += gy; tot["wx"] += wx; tot["wy"] += wy
            tot["n"] += len(pg)
        if quiet:
            return rows, tot
        print("=" * 84)
        print(f"  锚点对：{X}  vs  {Y}      （逐局序数配对；score 赢2/存活1/出局0）")
        print("=" * 84)
        print(f"  {'报告':<16}{'第三方':<10}{'局数':>6}{'序数X':>7}{'序数Y':>7}{'p(序数)':>10}"
              f"{'胜X':>6}{'胜Y':>6}{'p(胜)':>9}   方向")
        signs = []
        for name, r in rows:
            if r is None:
                print(f"  {name:<16}{'(缺该配置)':<10}")
                continue
            if r["gx"] == r["gy"]:
                arrow = "="
            else:
                arrow = f"{X} 优" if r["gx"] > r["gy"] else f"{Y} 优"
                signs.append(1 if r["gx"] > r["gy"] else -1)
            print(f"  {name:<16}{r['third']:<10}{r['n']:>6}{r['gx']:>7}{r['gy']:>7}"
                  f"{r['p_ord']:>10.3f}{r['wx']:>6}{r['wy']:>6}{r['p_win']:>9.3f}   {arrow}")
        print("  " + "-" * 82)
        p_pool = binom_p(tot["gx"], tot["gy"])
        p_win_pool = binom_p(tot["wx"], tot["wy"])
        print(f"  {'合并':<16}{'':<10}{tot['n']:>6}{tot['gx']:>7}{tot['gy']:>7}"
              f"{p_pool:>10.3f}{tot['wx']:>6}{tot['wy']:>6}{p_win_pool:>9.3f}")
        ps = [r["p_ord"] for _n, r in rows if r is not None]
        pf = fisher(ps)
        print(f"\n  Fisher 合并各组 p（{len(ps)} 组）→ p = {pf:.4f}")
        # ---- 一致性裁决 ----
        n_dir = len(signs)
        pos = sum(1 for s in signs if s > 0)
        neg = n_dir - pos
        print(f"  跨组方向一致性：{n_dir} 组有效，{X} 占优 {pos} 组 / {Y} 占优 {neg} 组")
        if n_dir == 0:
            verdict = "数据不足"
        elif pos == n_dir:
            verdict = f"★ {X} 在**所有**第三方下都占优"
        elif neg == n_dir:
            verdict = f"★ {Y} 在**所有**第三方下都占优"
        else:
            verdict = "⚠ 方向摇摆 ⇒ 差距小于「对手构成」扰动，**不可据此上线**"
        print(f"  裁决：{verdict}")
        if p_pool < 0.05 and n_dir and (pos == n_dir or neg == n_dir):
            print(f"  ⇒ 合并 p={p_pool:.4f} < 0.05 且方向全一致 ⇒ **可信**")
        return rows, tot

    judge((A, B))
    if a.pair2:
        print()
        judge(tuple(a.pair2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
