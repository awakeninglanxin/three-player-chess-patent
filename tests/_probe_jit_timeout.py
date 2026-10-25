# -*- coding: utf-8 -*-
"""探针：`tl=0.02` 下 JIT 搜索是否大量退化成 `legal[0]`（超时作废）

【为什么怀疑它】（2026-10-02）
  自对弈陪练 = `SearchBot(depth=1, time_limit=0.02)` ⇒ `depth_layers=1`
  ⇒ `range(3, 1*3+1, 3)` = `[3]`，**整个搜索只有 plies=3 这一层**。

  而 `_choose_jit` 的初值是：
      best_move, best_score = root[0], -INF        # root[0] == legal[0]
      for plies in ...:
          mv, sc, ranked, nodes, aborted = self._jit_search(...)
          if aborted or mv is None:
              break                                # ⇒ best_move 仍是 legal[0]
  再叠一个放大器：`nb_core.py` 每 **4096 节点**才查一次时钟，而 3 plies 开局
  只有 ~4543 节点 ⇒ **整层只有 1 次检查机会**，超时即"整层作废"。

  若这条路径被大量触发，则：① AI 实际在走 `legal[0]`（固定退化着法）；
  ② `first_ranked=None` ⇒ 价值网络重排也一起失效。

【判据】
  `last_info["plies"] == 0` ⇒ 第一层没完成 ⇒ 走的是 `legal[0]`。
  统计这个比例，并对比不同 `tl`，看 0.02 是不是正好卡在临界点上。
"""
import os
import sys
import time
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # tests/ 的上一级
for p in (os.path.join(ROOT, "server"), os.path.join(ROOT, "server", "engine"),
          os.path.join(ROOT, "server", "agents")):
    if p not in sys.path:
        sys.path.insert(0, p)

from engine import game_dxf as GA                                  # noqa: E402
from agents.search_bot import SearchBot                            # noqa: E402

ARMY_CN = getattr(GA, "ARMY_CN", {1: "魏", 2: "吴", 3: "蜀"})


def probe(tl, n_games=30, max_ply=8):
    hist = Counter()
    legal0 = 0
    total = 0
    t0 = time.time()
    for g in range(n_games):
        s = GA.new_game(first=1 + (g % 3))
        bot = SearchBot(depth=1, time_limit=tl, seed=g * 17 + 1)
        for _ in range(max_ply):
            if s.get("winner") is not None:
                break
            cur = s["turn"]
            legal = GA.legal_moves(s, cur)
            if not legal:
                GA._advance(s)
                continue
            r = bot.choose(s, legal, "", ARMY_CN[cur])
            p = int((bot.last_info or {}).get("plies", -1))
            hist[p] += 1
            total += 1
            first = f"{legal[0][0]}-{legal[0][1]}"
            if r.get("move") == first:
                legal0 += 1
            f, t = str(r["move"]).split("-")
            GA.apply(s, f, t)
    dt = time.time() - t0
    return dict(tl=tl, total=total, plies0=hist.get(0, 0),
                plies3=hist.get(3, 0), legal0=legal0, secs=round(dt, 1),
                hist=dict(sorted(hist.items())))


def main():
    print("=" * 78)
    print("探针：depth=1 / tl=0.02 是否退化成 legal[0]")
    print("=" * 78)
    print(f"{'tl(s)':>7} {'搜索次数':>9} {'plies=0':>9} {'占比':>8} "
          f"{'走legal[0]':>11} {'占比':>8} {'plies 分布':>22}")
    rows = []
    for tl in (0.02, 0.05, 0.2, 1.0):
        r_ = probe(tl)
        rows.append(r_)
        z = r_["plies0"] / max(r_["total"], 1)
        z2 = r_["legal0"] / max(r_["total"], 1)
        print(f"{r_['tl']:>7} {r_['total']:>9} {r_['plies0']:>9} {z:>7.1%} "
              f"{r_['legal0']:>11} {z2:>7.1%} {str(r_['hist']):>22}")
    print()
    r02 = rows[0]
    if r02["plies0"] / max(r02["total"], 1) > 0.3:
        print("⇒ ❌ 严重：tl=0.02 下超过三成搜索**第一层就没跑完**，陪练实际在走 legal[0]")
        print("   ⇒ 自对弈标签的'生成器'是退化的，这可以解释 sp2 的 AUC 0.54")
    elif r02["plies0"] > 0:
        print("⇒ ⚠ 存在退化但比例不高，需结合 legal[0] 占比一起看")
    else:
        print("⇒ ✅ tl=0.02 下没有第一层作废，退化假设不成立，得另找原因")


if __name__ == "__main__":
    main()
