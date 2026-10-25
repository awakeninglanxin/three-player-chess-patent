# -*- coding: utf-8 -*-
"""AlphaZero 化 · 云端训练（读大 npz，支持 GPU）

    python tools/train_cloud.py --data data/selfplay_100k.npz
    python tools/train_cloud.py --data data/selfplay_100k.npz --hidden 256,128 --epochs 200
    python tools/train_cloud.py --data data/selfplay_100k.npz --no-gpu   # 强制 CPU

【它跟本机的 tests/_train_value_net.py 有什么不同】
  · 本机版：**连产数据带训练**，单进程，适合几百局的小样本调试。
  · 云端版：**只训练**，读云端多进程产好的大 npz；支持 GPU / 自定义网络宽度 / 早停。

【必须看的一个指标：稳健性自检（一致性检查）】
  取开局 44 手合法着法两两比较：
    · 两手特征 L∞ < 0.10（肉眼几乎一样）
    · 网络却给 |ΔP| > 0.05（判若两人）
  ⇒ 记一次「矛盾」。矛盾多 = 网络在**噪声里排名**，**绝不能上线**。
  2026-10-01 本机 800 局的结果：`logi` **0/946** ✅、`mlp` **148/946** ❌。
  ⇒ 这就是要上云扩数据的直接原因。上云后这个数必须掉到接近 0。

【产出】
  server/agents/values/value_logi.json / value_mlp.json（直接拷回本机即上线）
  <data>.report.json —— 指标 + 系数表 + 稳健性，便于多轮对比
"""
import argparse
import copy
import json
import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRV = os.path.join(ROOT, "server")
for _p in (SRV, os.path.join(SRV, "engine"), os.path.join(SRV, "agents")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from agents import value_net as VN                        # noqa: E402
from agents import features_dxf as F                      # noqa: E402

OUTDIR = os.path.join(SRV, "agents", "values")


def consistency_check(models):
    """★ 上线门槛：开局 44 手两两比，特征几乎相同却给出大 ΔP 的次数"""
    from engine import game_dxf as GA
    s = GA.new_game(first=1)
    feats, names = [], []
    for frm, to in GA.legal_moves(s, 1):
        s2 = copy.deepcopy(s)
        GA.apply(s2, frm, to)
        feats.append(F.extract(s2, 1))
        names.append(f"{frm}->{to}")
    Fm = np.asarray(feats, dtype=np.float32)
    out = {}
    for nm, m in models.items():
        P = m.predict(Fm)
        bad = pairs = 0
        worst = (0.0, "")
        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                lin = float(np.max(np.abs(Fm[i] - Fm[j])))
                if lin >= 0.10:
                    continue
                pairs += 1
                dp = abs(float(P[i]) - float(P[j]))
                if dp > 0.05:
                    bad += 1
                    if dp > worst[0]:
                        worst = (dp, f"{names[i]} vs {names[j]} (L∞={lin:.3f})")
        out[nm] = dict(bad=bad, pairs=pairs, worst=worst)
    return out


def demo_hanging(models):
    """专项复现：老师说的「送马」局面，新旧口径对比"""
    from engine import game_dxf as GA
    from agents import eval_dxf as E
    s = GA.new_game(first=1)
    s2 = copy.deepcopy(s)
    GA.apply(s2, "111", "121")
    out = {}
    for tag, st in (("车还在 E9（马有保护）", s), ("车走 111→121（马无人保）", s2)):
        f = F.extract(st, 1)
        row = {"eval_hand": float(E.evaluate(st, 1)),
               # 特征里是 ÷50 归一化过的，乘回来才是"实际分值"（一个马 = 4.0）
               "hanging_val": round(float(f[F.IDX["my_hanging_val"]]) * 50, 2),
               "bad_trade": round(float(f[F.IDX["my_bad_trade"]]) * 50, 2)}
        for nm, m in models.items():
            row["P_" + nm] = float(m.predict([f])[0])
        out[tag] = row
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="", help="cloud_selfplay.py 产出的 npz")
    ap.add_argument("--parts", default="",
                    help="**分片目录**（cloud_selfplay 的 *.parts/）。"
                         "自对弈还在跑时用它做「中途训练」，不必等跑完。"
                         "与 --data 二选一，--parts 优先。")
    ap.add_argument("--hidden", default="64,32", help="MLP 隐层，逗号分隔")
    ap.add_argument("--epochs", type=int, default=160)
    ap.add_argument("--mlp-epochs", type=int, default=0, help="0=与 --epochs 同")
    ap.add_argument("--lr", type=float, default=0.05)
    ap.add_argument("--batch", type=int, default=1024)
    ap.add_argument("--val-frac", type=float, default=0.1)
    ap.add_argument("--no-gpu", action="store_true")
    ap.add_argument("--tag", default="", help="输出文件名后缀，便于多轮对比")
    a = ap.parse_args()

    dev = "cpu" if a.no_gpu else VN.default_device()
    t0 = time.time()

    print("=" * 78)
    print(f"云端训练   设备={dev}   数据={a.parts or a.data}")
    print("=" * 78, flush=True)

    if a.parts:
        # ---- 中途训练：直接把 *.parts/ 里的分片拼起来 ----
        #   ⚠️ 自对弈可能仍在写分片，所以**先列目录再逐个读**：
        #      刚写一半的 npz 会读失败，跳过即可（下次再训就带上了）。
        import glob
        files = sorted(glob.glob(os.path.join(a.parts, "part*.npz")))
        Xs, Ys, bad = [], [], 0
        for f in files:
            try:
                dd = np.load(f)
                if len(dd["Y"]):
                    Xs.append(dd["X"])
                    Ys.append(dd["Y"])
            except Exception:                      # noqa: BLE001
                bad += 1
        if not Xs:
            sys.exit(f"✗ {a.parts} 下没有可用的分片")
        X = np.asarray(np.concatenate(Xs), dtype=np.float32)
        Y = np.asarray(np.concatenate(Ys), dtype=np.float32)
        print(f"分片 {len(files)} 个（跳过未写完 {bad} 个）")
    else:
        if not a.data:
            sys.exit("✗ 必须给 --data 或 --parts")
        d = np.load(a.data)
        X = np.asarray(d["X"], dtype=np.float32)
        Y = np.asarray(d["Y"], dtype=np.float32)
    print(f"样本 {X.shape[0]:,} × {X.shape[1]} 维   正例率 {Y.mean():.4f}   载入 {time.time() - t0:.1f}s")

    # 切分（固定种子，可复现）
    rng = np.random.default_rng(20261001)
    idx = rng.permutation(len(Y))
    nval = int(len(Y) * a.val_frac)
    vi, ti = idx[:nval], idx[nval:]
    Xtr, Ytr, Xva, Yva = X[ti], Y[ti], X[vi], Y[vi]
    print(f"训练 {len(Ytr):,}   验证 {len(Yva):,}\n", flush=True)

    hidden = tuple(int(x) for x in a.hidden.split(",") if x.strip())
    models = {}
    report = {"data": a.parts or a.data, "samples": int(len(Y)), "device": dev,
              "hidden": list(hidden), "epochs": a.epochs}

    # ---- LogiNet（可解释）----
    print("① LogiNet（线性 · 用来读棋理）")
    t1 = time.time()
    logi = VN.LogiNet(X.shape[1], device=dev)
    logi.fit(Xtr, Ytr, epochs=max(200, a.epochs), lr=a.lr, batch=min(a.batch, 2048))
    mt = VN.metrics(logi.predict(Xtr), Ytr)
    mv = VN.metrics(logi.predict(Xva), Yva)
    models["logi"] = logi
    report["logi"] = {"train": mt, "val": mv, "secs": time.time() - t1}
    print(f"   train auc={mt['auc']:.4f} acc={mt['acc']:.4f}   "
          f"val auc={mv['auc']:.4f} acc={mv['acc']:.4f}（base {mv['base']:.4f}）"
          f"   {time.time() - t1:.0f}s", flush=True)

    # ---- MLPNet（能打）----
    print(f"\n② MLPNet（隐层 {hidden} · 上线用）")
    t2 = time.time()
    mlp = VN.MLPNet(X.shape[1], hidden=hidden, device=dev)
    mlp.fit(Xtr, Ytr, epochs=(a.mlp_epochs or a.epochs), lr=2e-3, batch=a.batch,
            val=(Xva, Yva), verbose=True)
    nt = VN.metrics(mlp.predict(Xtr), Ytr)
    nv = VN.metrics(mlp.predict(Xva), Yva)
    models["mlp"] = mlp
    report["mlp"] = {"train": nt, "val": nv, "secs": time.time() - t2}
    print(f"   train auc={nt['auc']:.4f} acc={nt['acc']:.4f}   "
          f"val auc={nv['auc']:.4f} acc={nv['acc']:.4f}   {time.time() - t2:.0f}s", flush=True)

    # ---- 特征系数（读"学到了什么"）----
    print("\n③ LogiNet 学到的系数（按 |系数| 降序，已还原到原始量纲）")
    coef = logi.coef_table(F.FEATURE_NAMES)
    report["coef"] = coef
    for nm, w in coef[:14]:
        bar = "█" * min(30, int(abs(w) * 4))
        print(f"   {nm:<20} {w:>+8.3f}  {bar}")
    risk = {n: w for n, w in coef if n in
            ("my_hanging_val", "my_bad_trade", "my_attacked_val", "risk_balance",
             "enemy_hanging_val", "enemy_bad_trade")}
    print(f"\n   ★ 子力安危那几维：{risk if risk else '（没进前 14，见 report.json）'}")

    # ---- 稳健性自检（上线门槛）----
    print("\n④ ★ 稳健性自检（上线门槛：矛盾越少越好）")
    cons = consistency_check(models)
    report["consistency"] = {k: {kk: vv for kk, vv in v.items()} for k, v in cons.items()}
    for nm, r in cons.items():
        flag = "✅" if r["bad"] == 0 else ("⚠" if r["bad"] / max(1, r["pairs"]) < 0.02 else "❌")
        print(f"   {nm:<5} {flag} 矛盾 {r['bad']}/{r['pairs']}"
              + (f"   最差 {r['worst'][1]} ΔP={r['worst'][0]:.3f}" if r["bad"] else ""))

    # ---- 送马专项 ----
    print("\n⑤ 送马专项复现（老师 2026-10-01 报的那手）")
    demo = demo_hanging(models)
    report["hanging_demo"] = demo
    for tag, row in demo.items():
        extra = "  ".join(f"{k}={v:+.3f}" for k, v in row.items() if k.startswith("P_"))
        print(f"   {tag:<26} 旧eval={row['eval_hand']:+8.2f}  悬子值={row['hanging_val']:.1f}  {extra}")

    # ---- 存盘 ----
    os.makedirs(OUTDIR, exist_ok=True)
    sfx = f"_{a.tag}" if a.tag else ""
    p1 = VN.save(logi, os.path.join(OUTDIR, f"value_logi{sfx}.json"), F.FEATURE_NAMES)
    p2 = VN.save(mlp, os.path.join(OUTDIR, f"value_mlp{sfx}.json"), F.FEATURE_NAMES)
    rp = a.data[:-4] + f"{sfx}.report.json"
    report["wall_secs"] = time.time() - t0
    with open(rp, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print("\n" + "=" * 78)
    print(f"完成，总用时 {report['wall_secs']:.0f}s")
    print(f"  → {p1}\n  → {p2}\n  → {rp}")
    print("\n把这三个文件下载回本机（放到 server/agents/values/ 与 data/），即可上线。")
    print("=" * 78)


if __name__ == "__main__":
    main()
