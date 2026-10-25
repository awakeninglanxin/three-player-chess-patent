# -*- coding: utf-8 -*-
"""探针 2：只回答一个问题 —— 引擎为什么看不见「白送的马」

老师 2026-10-01：
  「你一开始推荐让右车往前走了一步……这样，马里面就容易被蜀的炮干掉，相当于马白送」

已知（由 _probe_rook_horse.py 实测）：
  · 蜀炮 H2 吃 魏马 E8 的线路 = 蜀H2 →G2 →F2 →(贯通纵线)→ 魏A8 →B8 →C8(魏炮=炮架)
    →D8 →E8，中间**恰好一个炮架** ⇒ 合法；
  · 车在 E9 时：蜀炮吃马，魏车 E9 吃得回 ⇒ 只是**兑子**；
  · 车走 E9→D9 后：魏**吃不回来** ⇒ 马**净丢**。

本探针只查：**蜀方自己的搜索，为什么不趁机白吃这个马？**
  逐层输出蜀方的候选着法 + 分数，并单独标出「炮 H2 吃 E8 马」那一手的排名与分差。

运行：python tests/_probe_rook_horse2.py
"""
import os
import sys
import copy

HERE = os.path.dirname(os.path.abspath(__file__))
SRV = os.path.join(HERE, "..", "server")
sys.path.insert(0, os.path.abspath(SRV))
sys.path.insert(0, os.path.abspath(os.path.join(SRV, "engine")))

from engine import game_dxf as GA          # noqa: E402
from agents.search_bot import SearchBot    # noqa: E402

LETTER = {1: "ABCDE", 2: "KLMNO", 3: "FGHIJ"}
CN = {"general": "帅", "advisor": "士", "elephant": "象",
      "horse": "马", "rook": "车", "cannon": "炮", "pawn": "兵"}
ARMY = {1: "魏", 2: "吴", 3: "蜀"}


def lab(p):
    p = str(p)
    a, r, c = int(p[0]), int(p[1]), int(p[2])
    return LETTER[a][5 - r] + str(10 - c)


def show(ranked, mv, n=8):
    try:
        items = list(ranked)
    except TypeError:
        print("      （ranked 不可枚举）")
        return
    print(f"      ranked 结构样本：{repr(items[0]) if items else '空'}")
    for i, it in enumerate(items[:n]):
        star = "  ★选招" if str(it[0]) == str(mv[0]) and str(it[1]) == str(mv[1]) else ""
        print(f"      #{i+1} {tuple(it)}{star}")


def main():
    s = GA.new_game(first=1)

    print("=" * 74)
    print("① 魏走 111→121（引擎推荐的那手）之后的局面")
    print("=" * 74)
    s2 = copy.deepcopy(s)
    GA.apply(s2, "111", "121")
    # 三方回合：魏 → 吴 → 蜀；这里把回合推到「蜀」（相当于吴随便走一步）
    s2["turn"] = 3
    legal3 = GA.legal_moves(s2, 3)
    print(f"  轮到 {ARMY[s2['turn']]}，合法着法 {len(legal3)} 条")
    tgt = [(f, t) for f, t in legal3 if f == "338" and t == "112"]
    print(f"  其中「蜀炮 H2 吃 魏马 E8」= {tgt}   （{'在' if tgt else '不在'}合法着法里）")

    print("\n" + "=" * 74)
    print("② 蜀方自己逐层搜索：它想干什么？「白吃马」排第几？")
    print("=" * 74)
    for plies in (3, 6, 9, 12):
        bot = SearchBot(depth=plies // 3, time_limit=90.0, seed=20261001,
                        label=f"蜀探针 {plies}")
        res = bot._jit_search(copy.deepcopy(s2["board"]), 3, plies,
                              list(legal3), 90.0, True)
        mv = tuple(res[0])
        print(f"\n  ── 蜀 {plies} plies ──  选招 {mv} "
              f"({lab(mv[0])}→{lab(mv[1])})  根分 {res[1]:+.2f}  "
              f"节点 {res[3]}")
        show(res[2], mv, 8)
        # 「白吃马」那一手在榜上第几？
        try:
            names = [tuple(x)[:2] for x in list(res[2])]
            idx = names.index(("338", "112")) + 1
            print(f"      ⇒ 「炮 H2 吃 E8 马」在榜上第 {idx} 名")
        except Exception as e:
            print(f"      ⇒ 榜上没找到「炮吃马」（{type(e).__name__}）")

    print("\n" + "=" * 74)
    print("③ 换个问法：直接问引擎「吃这个马值不值」——同局面下 338-112 的分数")
    print("=" * 74)
    for plies in (6, 12):
        bot = SearchBot(depth=plies // 3, time_limit=90.0, seed=20261001,
                        label=f"对比 {plies}")
        # 只留一手 vs 全量：看根分怎么变
        res_all = bot._jit_search(copy.deepcopy(s2["board"]), 3, plies,
                                  list(legal3), 90.0, True)
        only = [("338", "112")]
        res_one = bot._jit_search(copy.deepcopy(s2["board"]), 3, plies,
                                  only, 90.0, True)
        print(f"  {plies} plies：全量根分 {res_all[1]:+.2f}（选 {res_all[0]}） "
              f"｜只给「炮吃马」一手时根分 {res_one[1]:+.2f}")
        print(f"     ⇒ 差值 {res_one[1] - res_all[1]:+.2f}"
              f"{'（吃马更差 ⇒ 引擎认为不值）' if res_one[1] < res_all[1] else '（吃马更好 ⇒ 引擎该吃却没吃，说明排序/剪枝有问题）'}")


if __name__ == "__main__":
    main()
