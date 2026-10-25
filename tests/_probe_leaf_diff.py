# -*- coding: utf-8 -*-
"""探针③：把 `leaf` 按权重**逐项隔离**，定位到底是哪一项差了

【原理】
    `SearchBot._leaf` 对权重是**线性**的（每个权重只以乘数出现），
    唯一例外是两个常数项：`+4000`（对手主帅已被斩）和 `-1e6`（我方主帅已失）。

    所以「只开一个权重、其余置 0」跑一次，就把那一项**单独拆了出来**：
        leaf(只开 pressure)  = ① 我的进攻压强
        leaf(只开 danger)    = ③ 敌对我的压强
        ...
        leaf(全 0)           = 常数项（4000 赏金 / -1e6）
    两边逐项对拍 ⇒ 直接指名哪一项抄错了，不用再猜。

【为什么要做这个】
    前面已经排除：排序平局口径（探针①）、宽度截断（探针②：关宽度也差）。
    且实测 plies=1 时差 22.35 —— **plies=1 的根分数就是纯 leaf 值**
    （根着法走完 → `_search(plies=0)` → `_leaf`）⇒ 分歧必在 leaf。
"""
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "server"))
sys.path.insert(0, os.path.join(HERE, "..", "server", "agents"))

import eval_dxf as E                          # noqa: E402
from engine import game_dxf as GA             # noqa: E402
from engine import geometry_dxf as D          # noqa: E402
from engine import nb_core as NB              # noqa: E402
from search_bot import SearchBot              # noqa: E402

KEYS = ["pressure", "danger", "check", "close1", "close2", "material", "deputy"]


def random_positions(n, seed=777, steps=(8, 34)):
    rng = random.Random(seed)
    out = []
    for i in range(n):
        s = GA.new_game(first=1 + (i % 3))
        target = rng.randint(*steps)
        for _ in range(target):
            lm = GA.legal_moves(s, s["turn"])
            if not lm:
                break
            frm, to = rng.choice(lm)
            try:
                GA.apply(s, frm, to)
            except Exception:
                break
            if GA.status(s).get("winner"):
                break
        out.append((f"局{i + 1}/{target}步", s))
    return out


def main():
    pos_list = random_positions(12)
    pos_list.insert(0, ("开局", GA.new_game(first=1)))

    bot = SearchBot(depth=1, noise=0.0)
    dist = E.distances()

    # key -> (最大偏差, 出现的第一个例子)
    worst = {k: (0.0, None) for k in KEYS + ["__const__"]}

    for tag, s in pos_list:
        board0 = s["board"]
        for me in (1, 2, 3):
            for key in KEYS + ["__const__"]:
                w = dict.fromkeys(NB.W_KEYS, 0.0)
                if key != "__const__":
                    w[key] = 1.0
                w["urgency"] = 0.0
                bot.w = w
                bot._ur = 1.0
                py = bot._leaf(dict(board0), me, dist)
                nb = NB.leaf_py(board0, me, w, ply=0)
                d = abs(py - nb)
                if d > worst[key][0]:
                    worst[key] = (d, f"{tag}·{D.ARMY_CN[me]}  Py={py:.6f} JIT={nb:.6f}")

    print("=" * 76)
    print("逐项隔离对照（每个权重单独开 1.0，其余全 0）")
    print("=" * 76)
    for key in KEYS + ["__const__"]:
        d, ex = worst[key]
        flag = "✗" if d > 1e-6 else "✓"
        name = {"__const__": "常数项(4000赏金 / -1e6)"}.get(key, key)
        print(f"  {flag} {name:<24} 最大偏差 {d:.3e}")
        if ex and d > 1e-6:
            print(f"       例：{ex}")

    # 权重全开（正常口径）—— 看总偏差是不是恰好等于某一项的偏差
    print()
    print("=" * 76)
    print("权重全开（正常口径）逐局面")
    print("=" * 76)
    bot.w = dict(SearchBot(depth=1, noise=0.0).w)
    bot._ur = 1.0
    n_bad = 0
    for tag, s in pos_list:
        for me in (1, 2, 3):
            py = bot._leaf(dict(s["board"]), me, dist)
            nb = NB.leaf_py(s["board"], me, bot.w, ply=0)
            d = abs(py - nb)
            if d > 1e-6:
                n_bad += 1
                if n_bad <= 12:
                    print(f"  ✗ {tag}·{D.ARMY_CN[me]}  Py={py:.6f} JIT={nb:.6f}  Δ={d:.3e}")
    print(f"  → 不一致 {n_bad} / {len(pos_list) * 3} 处")


if __name__ == "__main__":
    main()
