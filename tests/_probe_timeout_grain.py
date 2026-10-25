# -*- coding: utf-8 -*-
"""超时截断粒度探针：1s 预算到底花在哪一层？

背景（2026-10-02）：
  `_verify_difficulty.py` §⑫ 断言「给 1.0s 预算 ⇒ 实测不超 2.5s」，实测 **2.60s ⇒ 失败**。
  而 JIT 内核的时钟检查是 `if (CTX[1] & 4095) == 0 and _now_ns() > CTX[2]`（每 4096 节点一次），
  按 ~43 万节点/秒算，溢出**本该只有 ~10ms** —— 1.6s 的溢出说明另有来源。

本探针**只测量、不改源码**，输出：
  · 每一层的 (plies, 节点增量, 耗时秒)
  · 总耗时 / 是否 aborted / last_info
  · JIT 路径 vs 纯 Python 路径对照（看是哪条路溢出）

用法：python tests/_probe_timeout_grain.py
"""
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "server"))
sys.path.insert(0, os.path.join(ROOT, "server", "agents"))

from engine import game_dxf as GA                    # noqa: E402
from search_bot import SearchBot, _jit_warmup        # noqa: E402


def midgame(steps=9, first=1):
    s = GA.new_game(first=first)
    for _ in range(steps):
        lm = GA.legal_moves(s, s["turn"])
        if not lm:
            break
        GA.apply(s, lm[0][0], lm[0][1])
    return s


def one(depth_layers, tl, use_jit, steps=9, tag=""):
    s = midgame(steps)
    b = SearchBot(depth=depth_layers, time_limit=tl, seed=11)
    b.use_jit = use_jit
    legal = GA.legal_moves(s, s["turn"])

    # 记录每层（借 times 的长度变化）
    seen = []
    orig = b._jit_search if use_jit else None

    t0 = time.time()
    res = b.choose(s, legal, "", "魏")
    dt = time.time() - t0

    info = dict(b.last_info or {})
    print(f"  [{tag}] depth_layers={depth_layers} tl={tl}s jit={use_jit} "
          f"⇒ **{dt:.2f}s**  aborted={info.get('aborted')} "
          f"plies={info.get('plies')} nodes={info.get('nodes')} move={res.get('move')}")
    return dt, info


def main():
    print("=" * 84)
    print("JIT 预热中（一次性）…")
    t = time.time()
    _jit_warmup()
    print(f"预热 {time.time() - t:.1f}s")
    print("=" * 84)

    s = midgame(9)
    print(f"局面：中局 9 步后，轮到 army={s['turn']}，合法着法 {len(GA.legal_moves(s, s['turn']))} 条\n")

    print("【A】预算 1.0s，看各深度的实际总耗时（JIT）")
    for dl in (1, 2, 3, 4):
        one(dl, 1.0, True, tag=f"jit dl={dl}")
    print()

    print("【B】同深度换不同预算，看溢出是否随预算变化（JIT / dl=4）")
    for tl in (0.5, 1.0, 2.0, 3.0):
        one(4, tl, True, tag=f"jit tl={tl}")
    print()

    print("【C】对照：纯 Python 路径（use_jit=False），同样 1.0s / dl=4")
    one(4, 1.0, False, tag="py  dl=4")
    print()

    print("【D】重复 3 次 1.0s / dl=4（看稳定性）")
    for i in range(3):
        one(4, 1.0, True, tag=f"rep{i + 1}")
    print()

    print("=" * 84)
    print("判读：若 A 中 dl=1/2 很快、dl=3/4 突然 2s+ ⇒ 溢出发生在**某一层的内部**；")
    print("      若 B 中溢出量≈常数（不随预算变化）⇒ 是「整层跑完才检查」；")
    print("      若 B 中溢出量≈预算比例 ⇒ 是外推在骗人（est 低估）。")
    print("=" * 84)


if __name__ == "__main__":
    main()
