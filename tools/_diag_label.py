# -*- coding: utf-8 -*-
"""标签映射一致性诊断 —— 两批数据的"特征→标签"是同一个函数吗？

【接 `_diag_sources.py` 的结论】2026-10-02 实测：
    · 逐维分布漂移极小（Cohen's d 中位 0.046，0/32 维 >0.2）⇒ 特征分布**相同**
    · 但交叉泛化崩：训 sp2 → sp2 0.6284 / 老 0.5500；训老 → 老 0.6505 / sp2 0.5401
    ⇒ 分布相同、各自自洽、互相预测不了。**"难"解释不了**（难则两边都低），
      只剩一种可能：**同一组特征在两个源里被贴了不同的标签映射**。

【本探针的判据：单特征 AUC 向量（不需要训练）】
对每个源、每一维，把该维本身当分数算一次 AUC ⇒ 得到一条 32 维的"极性指纹"。
  · 两源指纹**正相关**  ⇒ 映射一致（那问题在别处）
  · 两源指纹**符号打架** ⇒ 同一特征在一源里"越大越赢"、在另一源里"越大越输"
    ⇒ 典型的**标签口径/规则版本不同**（或某一源的 X-Y 配对错位）

用法：
    python tools/_diag_label.py --dirs data/sp2.parts data/selfplay_150k.parts --n 25
"""
import argparse
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from _diag_sources import load_shards                     # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dirs", nargs="+", required=True)
    ap.add_argument("--n", type=int, default=25)
    ap.add_argument("--top", type=int, default=8)
    a = ap.parse_args()

    from agents import features_dxf as F
    from agents import value_net as VN
    names = list(F.FEATURE_NAMES)

    fps, ys, tags = {}, {}, []
    for d in a.dirs:
        t = os.path.basename(os.path.normpath(d))
        r, fs = load_shards(d, a.n)
        if r is None:
            print(f"  ✗ {t}: 没分片")
            continue
        X, Y = r
        tags.append(t)
        ys[t] = Y
        fp = []
        for k in range(X.shape[1]):
            fp.append(float(VN.metrics(X[:, k], Y)["auc"]))
        fps[t] = np.asarray(fp)
        print(f"  {t}: {len(Y):,} 样本, Y均值 {Y.mean():.4f}, 单特征 AUC 中位 "
              f"{np.median(fp):.4f}（越偏 0.5 越有信息）")

    print("\n" + "=" * 76)
    print("① 单特征极性指纹（AUC>0.5 = 该维越大越可能赢；<0.5 = 越大越可能输）")
    print("=" * 76)
    for t in tags:
        fp = fps[t]
        order = np.argsort(-np.abs(fp - 0.5))[:a.top]
        print(f"\n  【{t}】信息量最大的 {a.top} 维：")
        for k in order:
            nm = names[k] if k < len(names) else f"#{k}"
            arrow = "↑赢" if fp[k] > 0.5 else "↓输"
            print(f"      auc={fp[k]:.4f}  {arrow}   {nm}")

    if len(tags) < 2:
        sys.exit("\n✗ 只有一个源，没法比")
    A, B = tags[0], tags[1]
    da, db = fps[A] - 0.5, fps[B] - 0.5
    sign_agree = int((np.sign(da) == np.sign(db)).sum())
    pear = float(np.corrcoef(da, db)[0, 1])
    print("\n" + "=" * 76)
    print("② 两源指纹的一致性")
    print("=" * 76)
    print(f"  符号一致 {sign_agree}/{len(da)} 维（随机应 ≈ {len(da)//2}）")
    print(f"  去均值后 Pearson r = {pear:+.4f}   （r≈1 同映射；r≈0 无关；r<0 反向）")
    flip = [k for k in range(len(da)) if np.sign(da[k]) != np.sign(db[k])
            and abs(da[k]) > 0.02 and abs(db[k]) > 0.02]
    print(f"  两边信息量都不小（|Δauc|>0.02）但**极性打架**的维：{len(flip)} 个")
    for k in flip[:a.top]:
        nm = names[k] if k < len(names) else f"#{k}"
        print(f"      {nm:<26} {A} {fps[A][k]:.4f}   {B} {fps[B][k]:.4f}")

    # ---- ③ 跨源用"对方的极性表"打分 ----
    # 做法：用 A 的指纹方向（+1/-1）当线性权重，直接在 B 上算 AUC。
    #       再与"B 自己的极性表"在同一批 B 样本上的成绩对比。
    print("\n" + "=" * 76)
    print("③ 把 A 的极性表**搬到 B 上**用（同一批 B 样本，只换权重来源）")
    print("=" * 76)
    for src, dst in ((A, B), (B, A)):
        w_src = np.sign(fps[src] - 0.5) * np.minimum(np.abs(fps[src] - 0.5), 0.2)
        w_dst = np.sign(fps[dst] - 0.5) * np.minimum(np.abs(fps[dst] - 0.5), 0.2)
        r, _ = load_shards([d for d in a.dirs
                            if os.path.basename(os.path.normpath(d)) == dst][0], a.n)
        Xd, Yd = r
        # 特征先按 dst 自身的均值/std 标准化，公平比较
        Xs = (Xd - Xd.mean(axis=0)) / (Xd.std(axis=0) + 1e-9)
        auc_src = float(VN.metrics(Xs @ w_src, Yd)["auc"])
        auc_dst = float(VN.metrics(Xs @ w_dst, Yd)["auc"])
        auc_avg = float(VN.metrics(Xs @ ((w_src + w_dst) / 2), Yd)["auc"])
        print(f"  在 [{dst}] 上评估：用 {src} 的权重 {auc_src:.4f} | "
              f"用 {dst} 自己的权重 {auc_dst:.4f} | 两者平均 {auc_avg:.4f}"
              f"   ⇒ 搬过去损失 {auc_dst - auc_src:+.4f}")


if __name__ == "__main__":
    main()
