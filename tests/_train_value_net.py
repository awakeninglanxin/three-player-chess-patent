# -*- coding: utf-8 -*-
"""AlphaZero 化 · 第一阶：用**自对弈的胜负结果**学出价值函数

   用法：
        python tests/_train_value_net.py 200                  # 跑 200 局自对弈
        python tests/_train_value_net.py 60 --quick           # 快速冒烟
        python tests/_train_value_net.py 800 --reuse          # 复用缓存、只重训
        python tests/_train_value_net.py 60 --no-save         # 只看结果、不写盘
        python tests/_train_value_net.py 800 --save-prod      # ★ 显式覆盖生产权重

   ⚠️⚠️ **写盘规则（2026-10-01 改，因一次真事故）**
        默认只写 `server/agents/values/value_*_<tag>.json`（tag 默认 `local`）。
        要覆盖生产文件 `value_mlp.json` / `value_logi.json`，**必须显式 `--save-prod`**。
        起因：以前无条件写生产文件，一次 8 局冒烟测试把 800 局权重静默覆盖了。

【这一步在做什么】
    完全不用人写的棋理、不用人调的权重：
      ① 让现在的 Bot 自对弈若干局（加 ε 随机走子保证局面多样）
      ② 每一手记下 `features_dxf` 的 32 维特征
      ③ 标签 = **这一方最后赢没赢**（终局唯一活着的将）
      ④ 梯度下降拟合  → 学出一个 `局面 → 胜率` 的函数

    这就是 AlphaZero 的 value head；区别只是我们用 MLP 而不是 ResNet
    （本机无 GPU，且本盘只有 135 点，MLP 是正确取舍 —— 见 value_net.py 注释）。

【输出】
    · `server/agents/values/value_mlp.json` —— 学到的价值网络（可加载上线）
    · `server/agents/values/value_logi.json` —— 线性版（**用来读"学到了什么棋理"**）
    · 控制台报告：AUC / 准确率 / 各特征学到的系数 / 送马局面的前后对比
"""
import copy
import os
import random
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRV = os.path.join(ROOT, "server")
for p in (SRV, os.path.join(SRV, "engine")):
    if p not in sys.path:
        sys.path.insert(0, p)

from engine import game_dxf as GA                      # noqa: E402
from agents import features_dxf as F                   # noqa: E402
from agents import eval_dxf as E                       # noqa: E402
from agents.search_bot import SearchBot                # noqa: E402
from agents import value_net as VN                     # noqa: E402

ARMY_CN = {1: "魏", 2: "吴", 3: "蜀"}
OUTDIR = os.path.join(SRV, "agents", "values")


def gen_games(n_games, tl=0.03, maxply=220, eps=0.12, seed0=1000, verbose=True):
    """自对弈产数据 → (X, Y, meta)

    eps：以该概率走一步**随机合法着法**（而非 Bot 的首选）。
        没有它，同一 seed 下局面会高度雷同，网络只学会"这一条线路"。
    """
    X, Y, meta = [], [], []
    decisive = 0
    t0 = time.time()
    for g in range(n_games):
        seed = seed0 + g
        rng = random.Random(seed * 7919)
        s = GA.new_game(first=1 + (seed % 3))
        bots = {k: SearchBot(depth=1, time_limit=tl, seed=seed * 17 + k)
                for k in (1, 2, 3)}
        rows = []
        for _ in range(maxply):
            if s.get("winner") is not None:
                break
            cur = s["turn"]
            legal = GA.legal_moves(s, cur)
            if not legal:
                GA._advance(s)
                continue
            rows.append((F.extract(s, cur), cur))
            mv = None
            if rng.random() >= eps:
                r = bots[cur].choose(s, legal, "", ARMY_CN[cur])
                mv = (r or {}).get("move")
            if not mv or tuple(str(mv).split("-")) not in legal:
                frm, to = legal[rng.randrange(len(legal))]
                mv = f"{frm}-{to}"
            f, t = str(mv).split("-")
            GA.apply(s, f, t)
        win = s.get("winner")
        if win:
            decisive += 1
        for feat, army in rows:
            if win is None:
                continue                      # 判和/触顶的局不提供胜负标签，丢弃
            X.append(feat)
            Y.append(1.0 if army == win else 0.0)
            meta.append({"game": g, "army": army, "ply": len(meta)})
        if verbose and (g + 1) % 25 == 0:
            print(f"    [{g + 1:>4}/{n_games}] 样本 {len(X):>7}  "
                  f"分出胜负 {decisive}/{g + 1}  已用 {time.time() - t0:.0f}s")
    return np.asarray(X, dtype=np.float32), np.asarray(Y, dtype=np.float32), meta


def consistency_check(models, n_moves=0):
    """★ 稳健性自检 —— 防止"在噪声里排名"

    做法：取开局 44 手合法着法，两两比较特征向量。
      · 若两手的特征 L∞ 距离 < 0.10（肉眼几乎一样）
      · 却给出 |ΔP| > 0.05 的预测差
      ⇒ 记为一次「矛盾」。矛盾越多，说明网络增益失控、它的排名不可信。

    这是 2026-10-01 踩坑后加的：修 sd 下限之前，111→131 与 111→121
    只差 2 维 0.06，MLP 却给 0.428 vs 0.220。
    """
    s = GA.new_game(first=1)
    feats, names = [], []
    for frm, to in GA.legal_moves(s, 1):
        s2 = copy.deepcopy(s)
        GA.apply(s2, frm, to)
        feats.append(F.extract(s2, 1))
        names.append(f"{frm}->{to}")
    Fm = np.asarray(feats, dtype=np.float32)
    print(f"\n  用开局 {len(names)} 手合法着法做两两稳健性检查（阈值 L∞<0.10 且 |ΔP|>0.05）：")
    for nm, m in models.items():
        P = m.predict(Fm)
        bad = []
        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                linf = float(np.max(np.abs(Fm[i] - Fm[j])))
                dp = abs(float(P[i]) - float(P[j]))
                if linf < 0.10 and dp > 0.05:
                    bad.append((names[i], names[j], linf, dp))
        tag = "✅" if not bad else "❌"
        print(f"    {tag} {nm:<5} 矛盾 {len(bad)} 对"
              + ("" if not bad else f"  最严重：{bad[0][0]} vs {bad[0][1]}"
                 f"（特征差 {bad[0][2]:.4f} → P 差 {bad[0][3]:.3f}）"))
    return Fm, names


def show_coef(model, top=16):
    tab = model.coef_table(F.FEATURE_NAMES)
    print("  学到的一维系数（+ = 该特征越大，本方胜率越高）：")
    for name, w in tab[:top]:
        star = "★" if name in ("my_hanging_val", "my_attacked_val", "my_bad_trade",
                               "enemy_hanging_val", "my_cheap_attacked") else " "
        print(f"    {star} {name:<22} {w:+8.3f}")


def demo_rook_horse(models):
    """★ 关键演示：在老师指出的「送马」局面上，各模型怎么判"""
    names = " ".join(models)
    print(f"\n{'=' * 74}\n★ 送马局面：各模型对 魏方胜率 的判断（{names}）\n{'=' * 74}")
    s0 = GA.new_game(first=1)
    s1 = copy.deepcopy(s0)
    GA.apply(s1, "111", "121")
    rows = []
    for tag, st in (("① 开局（车 E9 保着马 E8）", s0),
                    ("② 走 111→121（车让开、马无人保）", s1)):
        f = F.extract(st, 1)
        hang = f[F.IDX["my_hanging_val"]] * 50
        line = f"  {tag:<34} 悬子值={hang:4.1f}  旧eval={E.evaluate(st, 1):+7.2f}"
        for nm, m in models.items():
            line += f"   {nm}={float(m.predict([f])[0]):.3f}"
        rows.append((tag, line))
    for _t, ln in rows:
        print(ln)
    p0 = rows[0][1]
    print("  ⇒ 旧 eval 认为这手更好（分数上升）；学出来的价值网络应当给它**更低**的胜率。")
    return rows


def main():
    argv = sys.argv[1:]
    quick = "--quick" in argv
    no_save = "--no-save" in argv
    save_prod = "--save-prod" in argv
    tag = "local"
    for i, a in enumerate(argv):
        if a == "--tag" and i + 1 < len(argv):
            tag = argv[i + 1]
    n = 0
    for a in argv:
        if a.isdigit():
            n = int(a)
    if n == 0:
        n = 60 if quick else 200
    tl = 0.02 if quick else 0.03

    print("=" * 74)
    print(f"AlphaZero 化 · 第一阶：自对弈学价值函数（{n} 局，tl={tl}）")
    print("=" * 74)
    cache = os.path.join(HERE, "_value_dataset.npz")
    reuse = "--reuse" in argv and os.path.exists(cache)
    if reuse:
        z = np.load(cache)
        X, Y = z["X"], z["Y"]
        cached_n = int(z["n"]) if "n" in z.files else -1
        print(f"\n① 复用已有数据集 {cache}")
        print(f"  数据：{X.shape[0]} 样本 × {X.shape[1]} 特征   正例率 {Y.mean():.3f}"
              f"   （缓存来自 {cached_n if cached_n >= 0 else '?'} 局）")
        if cached_n >= 0 and cached_n != n:
            print(f"  ⚠ 缓存局数({cached_n}) ≠ 请求局数({n})。要用新局数请去掉 --reuse。")
    else:
        print("\n① 自对弈产数据（含 ε 随机走子保证多样）")
        t0 = time.time()
        X, Y, _meta = gen_games(n, tl=tl, eps=0.12, verbose=True)
        np.savez_compressed(cache, X=X, Y=Y, n=n)     # 缓存，便于快速迭代模型
        print(f"  数据：{X.shape[0]} 样本 × {X.shape[1]} 特征   正例率 {Y.mean():.3f}"
              f"   用时 {time.time() - t0:.0f}s")
        print(f"  已缓存到 {cache}（下次加 --reuse 可跳过产数据）")

    if X.shape[0] < 500:
        print("  ⚠ 样本太少，加大局数再试")
        return

    # ---- 划分训练 / 验证 ----
    rng = np.random.default_rng(0)
    idx = rng.permutation(X.shape[0])
    cut = int(X.shape[0] * 0.85)
    tr, va = idx[:cut], idx[cut:]
    Xtr, Ytr, Xva, Yva = X[tr], Y[tr], X[va], Y[va]
    print(f"  训练 {len(tr)} / 验证 {len(va)}")

    # ---- 基线：旧的手调权重（拿 eval 当分数，用秩相关看它排不排得动）----
    print("\n② 训练")
    logi = VN.LogiNet(X.shape[1], seed=1).fit(Xtr, Ytr, epochs=300, lr=0.05)
    mlp = VN.MLPNet(X.shape[1], hidden=(64, 32), seed=1).fit(
        Xtr, Ytr, epochs=150, lr=2e-3, val=(Xva, Yva), verbose=True)
    models = {"logi": logi, "mlp": mlp}

    print("\n③ 验证集表现（base = 全猜多数类的准确率，AUC 0.5 = 瞎猜）")
    for nm, m in models.items():
        mm = VN.metrics(m.predict(Xva), Yva)
        print(f"  {nm:<5} AUC={mm['auc']:.4f}  acc={mm['acc']:.4f}"
              f"  （base {mm['base']:.4f}）  bce={mm['bce']:.4f}")

    print()
    consistency_check(models)

    print()
    show_coef(logi)

    demo_rook_horse(models)

    # ---- 存盘 ----
    # ⚠️⚠️ 2026-10-01 踩坑（真事故）：本脚本以前**无条件**写 `value_mlp.json` /
    #    `value_logi.json`，结果一次 8 局的冒烟测试（`_train_value_net.py 8 --quick`）
    #    把 800 局训出的权重**当场静默覆盖**，连数据集缓存一起冲掉了。
    #    ⇒ 现在默认只写 `value_*_<tag>.json`（tag 默认 `local`）。
    #      想覆盖生产文件（`value_mlp.json` / `value_logi.json`）必须显式加 `--save-prod`。
    os.makedirs(OUTDIR, exist_ok=True)
    if no_save:
        print("\n④ --no-save：未写盘（生产权重文件保持不变）")
    else:
        if save_prod:
            print("\n④ ⚠ --save-prod：即将**覆盖生产权重** value_mlp.json / value_logi.json")
            sfx = ""
        else:
            sfx = f"_{tag}"
        p1 = VN.save(mlp, os.path.join(OUTDIR, f"value_mlp{sfx}.json"), F.FEATURE_NAMES)
        p2 = VN.save(logi, os.path.join(OUTDIR, f"value_logi{sfx}.json"), F.FEATURE_NAMES)
        print(f"\n④ 已保存（tag={tag}）：\n  {p1}\n  {p2}")
        if not save_prod:
            print("   （生产文件 value_mlp.json / value_logi.json **未改动**）")


if __name__ == "__main__":
    main()
