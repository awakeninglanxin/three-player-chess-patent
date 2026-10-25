# -*- coding: utf-8 -*-
"""五档难度 · JIT(+静态搜索) 实测耗时 / 实到层数 / 选出的着法

用途：给 `docs/专利版_预判改进方案.md`、`web/index.html` 的难度说明、
     `agents/difficulty.py` 的档位 desc 提供**实测数据**（不再凭推算写"约 X 秒"）。

★ 2026-10-02：第 6 档「传奇 · 15 plies」已由老师撤除 ⇒ 现测 5 档。
   本脚本直接遍历 `DIFF.LEVELS`，撤档后自动跟随，无需改循环。

同时给出 Python（qs=0 / JIT 关闭）的对照，验证加速倍数。
"""
import os
import random
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "server"))
sys.path.insert(0, os.path.join(HERE, "..", "server", "agents"))

from engine import game_dxf as GA            # noqa: E402
from engine import geometry_dxf as D         # noqa: E402
from agents import difficulty as DIFF        # noqa: E402
from search_bot import SearchBot, _jit_warmup  # noqa: E402


def midgame(steps=14, seed=3):
    rng = random.Random(seed)
    s = GA.new_game(first=1)
    for _ in range(steps):
        lm = GA.legal_moves(s, s["turn"])
        if not lm:
            break
        frm, to = rng.choice(lm)
        GA.apply(s, frm, to)
        if GA.status(s).get("winner"):
            break
    return s


def run(bot, s):
    me = s["turn"]
    legal = list(GA.legal_moves(s, me))
    t0 = time.time()
    res = bot.choose(s, legal)
    dt = time.time() - t0
    info = bot.last_info
    return res["move"], dt, info


def main():
    print("=" * 88)
    print(f"五档难度实测 · JIT 已接入（qs_depth={DIFF.QS_DEFAULT} 静态搜索开）")
    print("=" * 88)
    t0 = time.time()
    _jit_warmup()
    print(f"JIT 预热 {time.time() - t0:.2f}s\n")

    opening = GA.new_game(first=1)
    mg = midgame()

    hdr = f"{'档位':<16}{'设 depth':>9}{'时间上限':>9}   {'局面':<6}" \
          f"{'耗时':>9}{'实到 plies':>11}{'节点':>10}   着法"
    print(hdr)
    print("-" * 88)
    for lv in DIFF.LEVELS:
        if lv["model_id"] != "__search__":
            print(f"[{lv['level']}] {lv['name']:<12} 贪心档（不建树），跳过")
            continue
        bot = SearchBot(depth=lv["depth"], time_limit=lv["time_limit"],
                        seed=11, qs_depth=DIFF.QS_DEFAULT, use_jit=True,
                        label=lv["name"])
        for tag, s in (("开局", opening), ("中局14步", mg)):
            mv, dt, info = run(bot, s)
            print(f"[{lv['level']}] {lv['name']:<11}{lv['depth']:>8}层"
                  f"{lv['time_limit']:>8.0f}s   {tag:<6}"
                  f"{dt:>8.2f}s{info.get('plies'):>10}plies"
                  f"{info.get('nodes', 0):>10}   {mv}")
    print()

    # ---- 对照：JIT 关闭（纯 Python）+ 静态搜索开 ----
    print("=" * 88)
    print("对照 · 纯 Python 内核（use_jit=False，qs=6）—— 仅测档2/3，档4 以上太慢")
    print("=" * 88)
    for lv in DIFF.LEVELS[:3]:
        if lv["model_id"] != "__search__":
            continue
        bot = SearchBot(depth=lv["depth"], time_limit=lv["time_limit"],
                        seed=11, qs_depth=DIFF.QS_DEFAULT, use_jit=False,
                        label=lv["name"])
        mv, dt, info = run(bot, opening)
        print(f"[{lv['level']}] {lv['name']:<11}{lv['depth']:>8}层"
              f"{lv['time_limit']:>8.0f}s   {'开局':<6}"
              f"{dt:>8.2f}s{info.get('plies'):>10}plies"
              f"{info.get('nodes', 0):>10}   {mv}")
    print("=" * 88)
    return 0


if __name__ == "__main__":
    sys.exit(main())
