# -*- coding: utf-8 -*-
"""探针：numba 内核所需的预计算表 —— 规模 + 语义假设

需要在动手重写热路径**之前**回答三个问题：
  ① 各表规模有多大（决定扁平数组尺寸、缓存友好度）
  ② 车/炮的 `seen` 去重到底是防什么 —— 射线之间有没有「前缀包含」关系？
     若有，预计算就能直接消除重复；若没有，JIT 里必须保留 stamp 去重。
  ③ `HORSE_LEG[pos][dest]` 的腿数分布（`_horse` 用的是 `all(...)` 不是 `any(...)`，
     腿数若恒为 1 则两者等价 —— 必须确认，否则照抄会抄错语义）
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "server"))

from engine import geometry_dxf as D            # noqa: E402
from engine import rules_dxf as R               # noqa: E402

B = D.BOARD
IDS = list(B.ids)
N = len(IDS)


def main():
    print(f"点数 N = {N}")
    print()
    print("=== ① 各表规模 ===")
    n_ray_seg = sum(len(v) for v in R.RAYS.values())
    n_ray_pts = sum(len(p) for v in R.RAYS.values() for p in v)
    print(f"  射线：{n_ray_seg} 条 / 共 {n_ray_pts} 个点（扁平数组长度）")
    print(f"    每条射线平均 {n_ray_pts / n_ray_seg:.2f} 点，最长 "
          f"{max(len(p) for v in R.RAYS.values() for p in v)}")
    print(f"  马表 HORSE_T：{sum(len(v) for v in R.HORSE_T.values())} 步")
    print(f"  象表 ELE_T  ：{sum(len(v) for v in R.ELE_T.values())} 步")
    print(f"  士表 ADV_T  ：{sum(len(v) for v in R.ADV_T.values())} 步 / "
          f"{len(R.ADV_T)} 个键")
    print(f"  帅表 GEN_T  ：{sum(len(v) for v in R.GEN_T.values())} 步 / "
          f"{len(R.GEN_T)} 个键")
    print(f"  兵表 PAWN_T ：{sum(len(v) for v in R.PAWN_T.values())} 步")
    print(f"  反向攻击 ATK_BY：{len(R.ATK_BY)} 个 target，共 "
          f"{sum(len(d) for d in R.ATK_BY.values())} 条 (pos→spec)")
    n_spec = sum(len(v) for d in R.ATK_BY.values() for v in d.values())
    print(f"    (pos→spec) 展开后 {n_spec} 条 spec")
    print(f"    spec 类型分布（应为 rook/cannon/horse/elephant/advisor/general/pawn）：")
    from collections import Counter
    c = Counter()
    for d in R.ATK_BY.values():
        for v in d.values():
            for kind, _extra in v:
                c[kind] += 1
    for k, v in sorted(c.items()):
        print(f"      {k:10s} {v}")
    print()

    print("=== ② 射线前缀重叠（车/炮 seen 去重到底防什么）===")
    # ⚠️ 这里曾经写成 `a[:k] == b[:k]`（k = 较短序列长度）—— **那是错的**：
    #    它只在「短序列整段等于长序列前缀」时才为真，会漏掉「部分共享前缀」。
    #    本盘的真实情况恰恰是后者：营点（各方 row5-5）的纵向射线**分成两条支线**
    #    （分别接另两方的 row5-5），两条射线都以**同一个第一落点**开头，例如
    #        RAYS[145] = [['155','255','245',...], ['155','355','345',...]]
    #    ⇒ 车/炮沿列5 推进时，155 会被两条射线各生成一次 → **必须去重**。
    def lcp(a, b):
        n = 0
        for x, y in zip(a, b):
            if x != y:
                break
            n += 1
        return n

    n_lcp = 0
    max_lcp = 0
    samples = []
    for p in IDS:
        paths = R.RAYS[p]
        for i in range(len(paths)):
            for j in range(i + 1, len(paths)):
                L = lcp(paths[i], paths[j])
                if L:
                    n_lcp += 1
                    max_lcp = max(max_lcp, L)
                    if len(samples) < 6:
                        samples.append((p, L, paths[i], paths[j]))
    print(f"  有共享前缀的射线对 = {n_lcp} 组，最长公共前缀 = {max_lcp} 个点")
    for p, L, a, b in samples:
        print(f"    {p}: 共享 {L} 点   A={' → '.join(a)}")
        print(f"    {' ' * (len(p) + 2)}              B={' → '.join(b)}")
    print("  ⇒ 共享前缀**真实存在**（营点分叉）⇒ JIT 内核**必须**保留 stamp 去重，"
          "否则同一落点会重复生成")
    print()

    print("=== ③ 马腿数分布（_horse 用 all() 还是 any() 的语义等价性）===")
    c2 = Counter()
    for pos, d in R.HORSE_LEG.items():
        for dest, legs in d.items():
            c2[len(legs)] += 1
    print(f"  腿数分布 = {dict(c2)}")
    print("  ⇒ 若全是 1，则 all/any 等价（照抄 all 即可，零风险）")
    print()

    print("=== ④ 全源距离矩阵 ===")
    dist = {}
    from collections import deque
    for src in B.xy:
        dd = {src: 0}
        q = deque([src])
        while q:
            cur = q.popleft()
            for nb in B.adj.get(cur, ()):
                if nb not in dd:
                    dd[nb] = dd[cur] + 1
                    q.append(nb)
        dist[src] = dd
    sys.path.insert(0, os.path.join(HERE, "..", "server", "agents"))
    from eval_dxf import MAX_DIST as _MAXD
    mx = max(max(d.values()) for d in dist.values())
    print(f"  最大图距离 = {mx}（eval_dxf.MAX_DIST = {_MAXD}）")
    miss = sum(1 for s in B.xy for t in B.xy if t not in dist[s])
    print(f"  不可达点对数 = {miss}（应为 0）")
    print()

    print("=== ⑤ 开局合法着法数（对拍基准）===")
    from engine import game_dxf as GA
    s = GA.new_game(first=1)
    for a in (1, 2, 3):
        print(f"  {D.ARMY_CN[a]}方伪合法 {len(R.side_moves(s, a))} 步 / "
              f"合法 {len(GA.legal_moves(s, a))} 步")


if __name__ == "__main__":
    main()
