# -*- coding: utf-8 -*-
"""AUC 天花板诊断：0.655 是「欠拟合」还是「标签本身就不可预测」？

    python tests/_diag_auc_ceiling.py --parts <分片目录> [--epochs 60]

【为什么必须做这个诊断】
  云端三个模型（512×256 / 1024×512 / 2048×1024）AUC 全是 0.655×，
  说明**加宽没用**。但"加宽没用"有两个完全不同的解释，对应两条相反的下一步：

    (A) 欠拟合 / 优化不够  ⇒ 应该加宽、加轮次、调 lr
    (B) 标签噪声封顶        ⇒ 加宽纯属浪费，**只能改数据生成方式（陪练更强）**

  判据：**训练集 AUC vs 验证集 AUC**
    · 两者都在 0.65 且贴得很近 ⇒ (B) 封顶（模型没记住训练集，说明信号就这么多）
    · 训练 AUC ≫ 验证 AUC     ⇒ (A) 过拟合/容量不够

【两个附加探针】
  ① **单特征基线**：只用 `mat_diff_top`（对最强对手的子力差）算 AUC。
     网络若打不过这个"常识"，说明它没学到东西。
  ② **分层 AUC**：按 |mat_diff_top| 分位切三档。子力悬殊的局面天然好猜、
     均势局面天然难猜 ⇒ 看均势档的 AUC 才知道网络的真实本事。

【切分铁律】**按分片切**，不随机切。
  同一局的一串局面高度相关，随机切会让验证集里混进"训练局的兄弟局面" ⇒ 虚高。
"""
import argparse
import glob
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (os.path.join(ROOT, "server"), os.path.join(ROOT, "server", "engine"),
           os.path.join(ROOT, "server", "agents")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from agents import features_dxf as F        # noqa: E402
from agents import value_net as VN          # noqa: E402


def load_parts(parts_dir):
    files = sorted(glob.glob(os.path.join(parts_dir, "part*.npz")))
    Xs, Ys = [], []
    for f in files:
        try:
            d = np.load(f)
            if len(d["Y"]):
                Xs.append(d["X"])
                Ys.append(d["Y"])
        except Exception:                    # noqa: BLE001
            pass
    return np.concatenate(Xs), np.concatenate(Ys), len(files)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--parts", required=True)
    ap.add_argument("--epochs", type=int, default=60)
    ap.add_argument("--hidden", default="512,256")
    ap.add_argument("--device", default="cpu")
    ap.add_argument("--val-parts", type=int, default=20,
                    help="最后多少个**分片**做验证集")
    a = ap.parse_args()

    X, Y, nf = load_parts(a.parts)
    print("=" * 78)
    print(f"分片 {nf} 个   样本 {len(Y):,}   正例率 {Y.mean():.4f}")
    print("=" * 78)

    # ---- ★ 按分片切（不随机切）：最后 val_parts 个分片整块做验证 ----
    cut = max(1, len(Y) * (nf - a.val_parts) // nf)
    Xtr, Ytr, Xva, Yva = X[:cut], Y[:cut], X[cut:], Y[cut:]
    print(f"训练 {len(Ytr):,}（前 {nf - a.val_parts} 片） / "
          f"验证 {len(Yva):,}（后 {a.val_parts} 片）")

    # ---- 探针 ①：单特征基线 ----
    print("\n【探针①】单特征基线（只用常识，不看网络）")
    mi = F.IDX["mat_diff_top"]
    for nm, arr in (("训练", (Xtr[:, mi], Ytr)), ("验证", (Xva[:, mi], Yva))):
        auc = VN.metrics(arr[0], arr[1])["auc"]
        print(f"  mat_diff_top 单独   {nm} AUC = {auc:.4f}")
    mi2 = F.IDX["mat_me"]
    print(f"  mat_me       单独   验证 AUC = "
          f"{VN.metrics(Xva[:, mi2], Yva)['auc']:.4f}")

    # ---- 训练 ----
    hidden = tuple(int(x) for x in a.hidden.split(","))
    print(f"\n训练 MLP{hidden}  {a.epochs} epochs  device={a.device}")
    m = VN.MLPNet(X.shape[1], hidden=hidden, seed=0, device=a.device)
    m.fit(Xtr, Ytr, epochs=a.epochs, lr=1.0e-3, batch=4096)
    mt_tr = VN.metrics(m.predict(Xtr), Ytr)
    mt_va = VN.metrics(m.predict(Xva), Yva)
    print(f"  训练 AUC = {mt_tr['auc']:.4f}   acc = {mt_tr['acc']:.4f}")
    print(f"  验证 AUC = {mt_va['auc']:.4f}   acc = {mt_va['acc']:.4f}")
    gap = mt_tr["auc"] - mt_va["auc"]
    print(f"  ⇒ 训练−验证 差距 = {gap:+.4f}  "
          f"（{'过拟合/容量不足' if gap > 0.03 else '基本无过拟合 ⇒ 信号封顶'}）")

    # ---- 探针 ②：按 |mat_diff_top| 分层的验证 AUC ----
    print("\n【探针②】分层验证 AUC（按 |mat_diff_top| 三分位）")
    v = np.abs(Xva[:, mi])
    q1, q2 = np.quantile(v, [1 / 3, 2 / 3])
    p = m.predict(Xva)
    for tag, mask in (("均势档 |Δ|最小", v <= q1),
                      ("中档", (v > q1) & (v <= q2)),
                      ("悬殊档 |Δ|最大", v > q2)):
        if mask.sum() < 50:
            continue
        auc = VN.metrics(p[mask], Yva[mask])["auc"]
        print(f"  {tag:<14} n={int(mask.sum()):>7,}  "
              f"实胜率={Yva[mask].mean():.3f}  AUC={auc:.4f}")

    print("\n【结论口径】")
    print("  训练≈验证 且都停在 0.65 ⇒ 换算法/加宽无用，**只能改陪练质量或特征**；")
    print("  训练≫验证               ⇒ 加大 model / 降 lr / 加数据 仍有效。")
    print("=" * 78)


if __name__ == "__main__":
    main()
