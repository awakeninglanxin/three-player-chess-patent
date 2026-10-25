# -*- coding: utf-8 -*-
"""数据源一致性诊断 —— 两批自对弈分片到底是不是同一个分布？

【为什么写它】2026-10-02 守护日志里分源 AUC 长期是
        {'sp2.parts': 0.56,  'selfplay_150k.parts': 0.654}
**同一个模型、同一套 32 维特征**，两个来源的可预测性差 0.09。
这只有两种可能，且后果完全不同：
    ① 两批数据的**特征分布不同**（生成时特征/规则版本不同、或抽样口径不同）
       ⇒ 混在一起训 = 把一个自相矛盾的训练集喂给网络，AUC 被平均掉，
         而且**守护拿 AUC 选冠军**会永久失效（新数据越多，AUC 越被拖低）。
    ② 某一批数据的**标签噪声大**（对局更乱、判和更多）
       ⇒ 只是"难"，不算错，加权即可。

本探针把两者分开：
    · 逐维均值/标准差 → 分布漂移（Cohen's d，用合并 std 标准化）—— 直接看①
    · **交叉泛化**：A 上训 → 分别到 A / B 上评；再 B 上训 → 到 B / A 上评 —— 把①②分开
        A→A 高、A→B 低，且 B→B 高、B→A 低  ⇒ ①（各回各家才能预测）
        A→A 低、B→B 低                     ⇒ ②（两边都难）
    · 分片按序号切成 4 段分别评 → 看**源内**有没有时间漂移

用法：
    python tools/_diag_sources.py --dirs data/sp2.parts data/selfplay_150k.parts --n 30
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


def load_shards(d, n):
    """按**均匀间隔**抽 n 片（不是前 n 片 —— 要覆盖整个时间轴）。"""
    fs = sorted(glob.glob(os.path.join(d, "*.npz")))
    if not fs:
        return None, []
    if n and n < len(fs):
        fs = [fs[i] for i in np.linspace(0, len(fs) - 1, n).astype(int)]
    Xs, Ys = [], []
    for f in fs:
        try:
            z = np.load(f)
        except Exception:                          # noqa: BLE001
            continue
        if len(z["Y"]):
            Xs.append(np.asarray(z["X"], dtype=np.float32))
            Ys.append(np.asarray(z["Y"], dtype=np.float32))
    if not Xs:
        return None, fs
    return (np.concatenate(Xs), np.concatenate(Ys)), fs


def split(X, Y, seed=0, frac=0.5):
    rng = np.random.default_rng(seed)
    idx = rng.permutation(len(Y))
    k = int(len(Y) * frac)
    return (X[idx[:k]], Y[idx[:k]]), (X[idx[k:]], Y[idx[k:]])


def blk_auc(model, X, Y, blocks=4):
    """把 (X,Y) 按行序切成 blocks 段分别算 AUC —— 行序 = 分片顺序 = 时间序。"""
    out = []
    n = len(Y)
    for b in range(blocks):
        i0, i1 = int(n * b / blocks), int(n * (b + 1) / blocks)
        if i1 - i0 < 50:
            out.append(None)
            continue
        try:
            out.append(round(float(_auc(model.predict(X[i0:i1]), Y[i0:i1])), 4))
        except Exception:                          # noqa: BLE001
            out.append(None)
    return out


def _auc(p, y):
    from agents import value_net as VN
    return VN.metrics(p, y)["auc"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dirs", nargs="+", required=True, help="要对比的 *.parts 目录")
    ap.add_argument("--n", type=int, default=30, help="每个目录抽多少片（均匀间隔）")
    ap.add_argument("--epochs", type=int, default=60)
    ap.add_argument("--hidden", default="64,32")
    ap.add_argument("--device", default="")
    ap.add_argument("--blocks", type=int, default=4)
    a = ap.parse_args()

    import torch
    from agents import value_net as VN
    from agents import features_dxf as F
    names = list(F.FEATURE_NAMES)
    dev = a.device or ("cuda" if torch.cuda.is_available() else "cpu")
    hidden = tuple(int(x) for x in a.hidden.split(",") if x.strip())
    print(f"设备 {dev}   网络 mlp{hidden}   epochs={a.epochs}\n")

    tags, data, shard_names = [], {}, {}
    for d in a.dirs:
        t = os.path.basename(os.path.normpath(d))
        r, fs = load_shards(d, a.n)
        if r is None:
            print(f"  ✗ {t}: 没有可用分片")
            continue
        X, Y = r
        tags.append(t)
        data[t] = (X, Y)
        shard_names[t] = fs
        print(f"  {t}: 抽 {len(fs)} 片（共 {len(glob.glob(os.path.join(d, '*.npz')))} 片）"
              f" ⇒ {len(Y):,} 样本, Y均值 {Y.mean():.4f}, 每片 {len(Y) // max(len(fs),1):,} 样本")
    if len(tags) < 2:
        sys.exit("✗ 至少要两个目录")

    # ---------------------------------------------------------------- ① 分布漂移
    print("\n" + "=" * 74)
    print("① 逐维分布漂移（Cohen's d = |Δ均值| / 合并 std；>0.2 就该警觉，>0.5 是换了分布）")
    print("=" * 74)
    for i in range(len(tags)):
        for j in range(i + 1, len(tags)):
            A, B = data[tags[i]][0], data[tags[j]][0]
            ma, mb = A.mean(axis=0), B.mean(axis=0)
            sa, sb = A.std(axis=0) + 1e-9, B.std(axis=0) + 1e-9
            pooled = np.sqrt((sa ** 2 + sb ** 2) / 2.0)
            d = np.abs(ma - mb) / pooled
            order = np.argsort(-d)[:6]
            print(f"\n  {tags[i]}  vs  {tags[j]}：d 中位 {np.median(d):.3f} / "
                  f"均值 {d.mean():.3f} / 最大 {d.max():.3f}；"
                  f"d>0.2 的维 {int((d > 0.2).sum())}/32，d>0.5 的维 {int((d > 0.5).sum())}/32")
            for k in order:
                nm = names[k] if k < len(names) else f"#{k}"
                print(f"      d={d[k]:>6.3f}  {nm:<26} "
                      f"{tags[i]} {ma[k]:>+9.4f}±{sa[k]:.4f}   {tags[j]} {mb[k]:>+9.4f}±{sb[k]:.4f}")

    # ---------------------------------------------------------------- ② 交叉泛化
    print("\n" + "=" * 74)
    print("② 交叉泛化（每源各切一半做本源的训练/评估；训练量完全相同，只有来源不同）")
    print("=" * 74)
    tr, ev = {}, {}
    for t in tags:
        tr[t], ev[t] = split(*data[t])

    def train_on(parts, label):
        X = np.concatenate([tr[t][0] for t in parts])
        Y = np.concatenate([tr[t][1] for t in parts])
        m = VN.MLPNet(X.shape[1], hidden=hidden, seed=0, device=dev)
        m.fit(X, Y, epochs=a.epochs, batch=4096)
        row = {}
        for t in tags:
            row[t] = round(float(_auc(m.predict(ev[t][0]), ev[t][1])), 4)
        print(f"\n  训练于 [{label}]（{len(Y):,} 样本）  → 评估：")
        for t in tags:
            mark = "◀ 本源" if (len(parts) == 1 and t == parts[0]) else ""
            print(f"      {t:<24} auc = {row[t]:.4f} {mark}")
        # 源内时间漂移（只对**训练源的评估集**切块，避免跨源混淆）
        if len(parts) == 1:
            t0 = parts[0]
            bl = blk_auc(m, ev[t0][0], ev[t0][1], a.blocks)
            print(f"      └ {t0} 评估集按分片序切 {a.blocks} 段（早→晚）：{bl}")
        return row

    cross = {}
    for t in tags:
        cross[t] = train_on([t], t)
    cross["ALL"] = train_on(list(tags), "+".join(tags))

    # ---------------------------------------------------------------- 判据
    print("\n" + "=" * 74)
    print("判据")
    print("=" * 74)
    own = {t: cross[t][t] for t in tags}
    worst_own = min(own.values())
    for t in tags:
        others = [cross[t][u] for u in tags if u != t]
        drop = cross[t][t] - (max(others) if others else 0.0)
        print(f"  {t:<24} 本源 auc {cross[t][t]:.4f}   → 跨源最高 {max(others) if others else float('nan'):.4f}"
              f"   落差 {drop:+.4f}")
        if drop > 0.02:
            print(f"      ⇒ **该源与别源分布不同**（各回各家才预测得准）")
        elif cross[t][t] < worst_own + 0.02:
            print(f"      ⇒ 该源**本身就难预测**（标签噪声 / 对局更乱），不是分布问题")
    print(f"\n  混训（= 守护现状，{'+'.join(tags)}）："
          + "  ".join(f"{t} {cross['ALL'][t]:.4f}" for t in tags))


if __name__ == "__main__":
    main()
