# -*- coding: utf-8 -*-
"""验证集泄漏诊断 —— AUC 到底是"泛化"还是"记住了这一局"？

【怀疑的来由】一局棋里保留的 40 个局面**共享同一个标签**（Y 只由最终胜负决定）。
若切分是按**样本**随机的，同一局的局面会同时落在训练侧和验证侧 ⇒
模型只要学会"识别这一局的指纹"，就能把验证侧同局局面蒙对 ⇒ **AUC 被抬高**。
守护现在就是这么切的：`rng.permutation(len(Y))` 取前 10%（见 gpu_daemon.py:605）。

【判据】同一个源、同样的网络、同样的训练量，只改**切分方式**：
    · row  ：按样本随机切（= 守护现状）  → 允许同局泄漏
    · shard：按分片切（整片进训练或整片进验证）→ 同局不跨侧
两个数字的差就是**泄漏量**。若 shard 口径跌到接近 0.5x，则
"0.65" 里绝大部分是记局，不是泛化 —— 那么用 AUC 选模型/选冠军就失去意义。

⚠️ 前提断言（`--n` 片内每片 ≥ 1 局）：本脚本会打印每片样本数，便于确认片=局批。

用法：
    python tools/_diag_leak.py --dir /root/autodl-tmp/data/sp2.parts --n 60
"""
import argparse
import glob
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRV = os.path.join(ROOT, "server")
for _p in (SRV, os.path.join(SRV, "engine"), os.path.join(SRV, "agents")):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def load_each(d, n):
    fs = sorted(glob.glob(os.path.join(d, "*.npz")))
    if not fs:
        return []
    if n and n < len(fs):
        fs = [fs[i] for i in np.linspace(0, len(fs) - 1, n).astype(int)]
    out = []
    for f in fs:
        try:
            z = np.load(f)
        except Exception:                          # noqa: BLE001
            continue
        if len(z["Y"]) >= 20:
            out.append((np.asarray(z["X"], dtype=np.float32),
                        np.asarray(z["Y"], dtype=np.float32)))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True)
    ap.add_argument("--n", type=int, default=60)
    ap.add_argument("--epochs", type=int, default=80)
    ap.add_argument("--hidden", default="64,32")
    ap.add_argument("--batch", type=int, default=4096)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--device", default="")
    a = ap.parse_args()

    import torch
    from agents import value_net as VN
    dev = a.device or ("cuda" if torch.cuda.is_available() else "cpu")
    hidden = tuple(int(x) for x in a.hidden.split(",") if x.strip())

    parts = load_each(a.dir, a.n)
    if len(parts) < 8:
        sys.exit(f"✗ 分片太少（{len(parts)}）")
    sizes = [len(y) for _x, y in parts]
    print(f"源 {os.path.basename(os.path.normpath(a.dir))}  抽 {len(parts)} 片  "
          f"每片样本 {min(sizes)}~{max(sizes)}（中位 {int(np.median(sizes))}）  "
          f"共 {sum(sizes):,} 样本")
    print(f"设备 {dev}  网络 mlp{hidden}  epochs={a.epochs}\n")

    def train_eval(Xtr, Ytr, evals, tag):
        m = VN.MLPNet(Xtr.shape[1], hidden=hidden, seed=a.seed, device=dev)
        m.fit(Xtr, Ytr, epochs=a.epochs, batch=a.batch)
        print(f"  训练于【{tag}】({len(Ytr):,} 样本)：")
        for nm, (Xe, Ye) in evals.items():
            auc = float(VN.metrics(m.predict(Xe), Ye)["auc"])
            print(f"      评估 {nm:<22} auc = {auc:.4f}")
        return m

    # ---- 口径 1：按分片切（同局不跨侧）----
    cut = len(parts) // 2
    tr_p, ev_p = parts[:cut], parts[cut:]
    Xtr1 = np.concatenate([x for x, _y in tr_p])
    Ytr1 = np.concatenate([y for _x, y in tr_p])
    Xev1 = np.concatenate([x for x, _y in ev_p])
    Yev1 = np.concatenate([y for _x, y in ev_p])
    print("【口径 A】按**分片**切：训练片 {}-{} / 评估片 {}-{}（同局不跨侧）".format(
        0, cut - 1, cut, len(parts) - 1))
    m1 = train_eval(Xtr1, Ytr1, {"异片（无泄漏）": (Xev1, Yev1)}, "分片-前半")
    auc_shard = float(VN.metrics(m1.predict(Xev1), Yev1)["auc"])
    # 反向折：只用后半片训练、前半片评估 —— 排除"早片/晚片本身有系统差异"的混杂
    Xtr1r = Xev1
    Ytr1r = Yev1
    m1r = train_eval(Xtr1r, Ytr1r, {"异片（无泄漏）": (Xtr1, Ytr1)}, "分片-后半")
    auc_shard_r = float(VN.metrics(m1r.predict(Xtr1), Ytr1)["auc"])
    auc_shard = (auc_shard + auc_shard_r) / 2.0
    print(f"  （两折平均 {auc_shard:.4f}）")

    # ---- 口径 2：按样本随机切（= 守护现状），训练量对齐 ----
    allX = np.concatenate([x for x, _y in parts])
    allY = np.concatenate([y for _x, y in parts])
    rng = np.random.default_rng(20261001)
    idx = rng.permutation(len(allY))
    ntr = len(Ytr1)
    ti, vi = idx[:ntr], idx[ntr:]
    print(f"\n【口径 B】按**样本**随机切（守护现状）：训练 {ntr:,} / 评估 {len(vi):,}"
          f"（训练量与口径 A 严格对齐）")
    # 只留"评估侧里与训练侧同局"的部分无法直接识别（未存局号），
    # 但两种口径的**训练集大小与网络完全相同** ⇒ 差异只来自切分方式。
    m2 = train_eval(allX[ti], allY[ti],
                    {"同源随机（可能泄漏）": (allX[vi], allY[vi])}, "样本随机")
    auc_row = float(VN.metrics(m2.predict(allX[vi]), allY[vi])["auc"])

    print("\n" + "=" * 70)
    print("判据")
    print("=" * 70)
    print(f"  按分片切（无泄漏） auc = {auc_shard:.4f}")
    print(f"  按样本切（有泄漏） auc = {auc_row:.4f}")
    print(f"  ⇒ 泄漏抬高量 = {auc_row - auc_shard:+.4f}")
    if auc_row - auc_shard > 0.03:
        print("  ⇒ **验证集存在同局泄漏**：AUC 里相当一部分是\"记住了这一局\"，")
        print("     而不是对陌生局面的泛化 ⇒ **不能用它选模型/选冠军**")
        print("     （更不能用它比较不同轮的模型 —— 泄漏量随数据构成还会变）")
    else:
        print("  ⇒ 泄漏不明显，AUC 的差异另有来源")


if __name__ == "__main__":
    main()
