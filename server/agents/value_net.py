# -*- coding: utf-8 -*-
"""三人象棋 · 价值网络（AlphaZero 的 value head 裁剪版）

【定位】
    AlphaZero 的 value head 干一件事：**局面 → 胜率**。
    本文件就是它的最小可用实现 —— 不写任何棋理，只用自对弈的**胜负结果**去拟合。

    与 `eval_dxf.py`（手调权重）的根本区别：
      · `eval_dxf`  : 人定 10 个权重（pressure=0.25 / material=0.10 …），
                      特征是**人挑的**，权重是**人猜的**，目标是**人写的战斗分**。
      · `value_net` : 特征由 `features_dxf` 给出（32 维，含子力安危），
                      权重由**梯度下降**从胜负结果里学出来，**零人工棋理**。

【两个模型（刻意都保留）】
    · `LogiNet`  —— 线性 + sigmoid。**可解释**：学到的系数直接告诉你
                     "哪一维重要、正负如何"。用它来回答"网络学到了什么棋理"。
    · `MLPNet`   —— 2 隐层小网络。**更能打**：能表达特征交互。
                    上线用它，讲道理用 LogiNet。

【为什么不做 CNN（AlphaZero 原版）】
    原版输入是 9×10×N 的特征平面 + 19~39 层残差网络，需要 GPU 数周训练。
    本机 torch 是 **CPU 版**（无 CUDA），且本盘只有 135 点 vs 围棋 361 点，
    局面多样性低得多 ⇒ **在小特征向量上训 MLP 是这台机器上的正确取舍**。
    结构上仍是 AlphaZero 的形：特征 → 胜率，端到端学出来。
"""
import json
import os

import numpy as np
import torch
import torch.nn as nn


# ★ 标准化下限 —— 一个踩过的坑（2026-10-01）
#   我们的特征**已经手工归一化过**（量纲统一在 ±3 左右）。
#   若再除以 batch std，那些"几乎不变的维度"（std 接近 0）会被放大成
#   几十~上百倍增益 ⇒ 两个**肉眼一样**的局面被网络判成天差地别。
#   实测后果：开局 111→131 与 111→121 的特征只有 2 维差 0.06，
#             MLP 却给出 0.428 vs 0.220（ΔP = 0.21）——排名完全不可信。
#   ⇒ 给 sd 设下限，把最大增益锁在 10 倍以内。
SD_FLOOR = 0.10


def _sd(X):
    """带下限的标准差 —— 防止"几乎不变的维度"被放大成高增益噪声源"""
    sd = np.asarray(X, dtype=np.float64).std(axis=0)
    sd = np.maximum(sd, SD_FLOOR)
    return sd.astype(np.float32)


def default_device():
    """有 CUDA 就用，没有就 CPU。

    ⚠️ 对这个规模（32 维 → 64 → 32 的 MLP、batch 256）**GPU 其实没有优势** ——
       小矩阵上 kernel launch 开销会盖过计算收益，实测往往比 CPU 还慢。
       `device` 参数是给 **Phase 3（ResNet 双头 + MCTS 批量推理）** 预留的，
       那时 batch 上千、网络几十层，GPU 才真正吃得上力。
    """
    try:
        return "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:
        return "cpu"


class LogiNet:
    """线性 + sigmoid —— 可解释版"""

    name = "logi"

    def __init__(self, nfeat, seed=0, l2=1e-3, device="cpu"):
        torch.manual_seed(seed)
        self.nfeat = nfeat
        self.l2 = l2
        self.device = device
        self.lin = nn.Linear(nfeat, 1).to(device)
        self.mu = None
        self.sd = None

    def _prep(self, X):
        X = np.asarray(X, dtype=np.float32)
        if self.mu is not None:
            X = (X - self.mu) / self.sd
        return torch.from_numpy(np.ascontiguousarray(X)).to(self.device)

    def fit(self, X, Y, epochs=200, lr=0.05, batch=512, verbose=False):
        self.mu = X.mean(axis=0)
        self.sd = _sd(X)
        Xt = self._prep(X)
        Yt = torch.from_numpy(
            np.ascontiguousarray(np.asarray(Y, dtype=np.float32).reshape(-1, 1))
        ).to(self.device)
        opt = torch.optim.Adam(self.lin.parameters(), lr=lr, weight_decay=self.l2)
        lossf = nn.BCEWithLogitsLoss()
        n = Xt.shape[0]
        for ep in range(epochs):
            perm = torch.randperm(n, device=self.device)
            tot = None
            for i in range(0, n, batch):
                idx = perm[i:i + batch]
                opt.zero_grad()
                out = self.lin(Xt[idx])
                loss = lossf(out, Yt[idx])
                loss.backward()
                opt.step()
                # ⚠️ 2026-10-02：原为 `float(loss)` —— 每个 batch 强制 **GPU 同步**，
                #    打断 CUDA 异步流水线。1011 万样本 / batch 4096 ⇒ 每轮 **24.7 万次**
                #    同步，实测是"GPU 利用率上不去"的隐藏元凶之一。改成累加 detached
                #    tensor，整轮只在最后同步一次（顺带消掉 PyTorch 的 requires_grad 警告）。
                b = loss.detach() * len(idx)
                tot = b if tot is None else tot + b
            tot = 0.0 if tot is None else float(tot) / n
            if verbose and (ep + 1) % 50 == 0:
                print(f"    logi ep{ep + 1:>4}  loss={tot:.4f}")
        return self

    def predict(self, X):
        with torch.no_grad():
            return torch.sigmoid(self.lin(self._prep(X))).detach().cpu().numpy().ravel()

    def coef_table(self, names):
        """返回按 |系数| 降序的 (特征名, 系数) —— 用来读"网络学到了什么"。
        系数已乘回原始量纲（除以 sd），故可直接比较量级。"""
        w = self.lin.weight.detach().cpu().numpy().ravel() / self.sd
        order = np.argsort(-np.abs(w))
        return [(names[i], float(w[i])) for i in order]

    def state(self):
        return {"kind": self.name, "nfeat": self.nfeat,
                "w": self.lin.weight.detach().cpu().numpy().ravel().tolist(),
                "b": float(self.lin.bias.detach().cpu().numpy().ravel()[0]),
                "mu": self.mu.tolist(), "sd": self.sd.tolist(), "l2": self.l2}


class MLPNet:
    """2 隐层小网络 —— 更能打"""

    name = "mlp"

    def __init__(self, nfeat, hidden=(64, 32), seed=0, device="cpu"):
        torch.manual_seed(seed)
        self.nfeat = nfeat
        self.hidden = tuple(hidden)
        self.device = device
        layers = []
        prev = nfeat
        for h in self.hidden:
            layers += [nn.Linear(prev, h), nn.Tanh()]
            prev = h
        layers += [nn.Linear(prev, 1)]
        self.net = nn.Sequential(*layers).to(device)
        self.mu = None
        self.sd = None

    def _prep(self, X):
        X = np.asarray(X, dtype=np.float32)
        if self.mu is not None:
            X = (X - self.mu) / self.sd
        return torch.from_numpy(np.ascontiguousarray(X)).to(self.device)

    def fit(self, X, Y, epochs=120, lr=2e-3, batch=256, val=None, verbose=False):
        self.mu = X.mean(axis=0)
        self.sd = _sd(X)
        Xt = self._prep(X)
        Yt = torch.from_numpy(
            np.ascontiguousarray(np.asarray(Y, dtype=np.float32).reshape(-1, 1))
        ).to(self.device)
        opt = torch.optim.Adam(self.net.parameters(), lr=lr, weight_decay=1e-4)
        sch = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=max(1, epochs))
        lossf = nn.BCEWithLogitsLoss()
        n = Xt.shape[0]
        for ep in range(epochs):
            self.net.train()
            perm = torch.randperm(n, device=self.device)
            tot = None
            for i in range(0, n, batch):
                idx = perm[i:i + batch]
                opt.zero_grad()
                loss = lossf(self.net(Xt[idx]), Yt[idx])
                loss.backward()
                opt.step()
                # ⚠️ 2026-10-02：同 LogiNet.fit —— 去掉逐步 `float(loss)` 的 GPU 同步，
                #    改累加 detached tensor。batch 越小伤害越大，这里 batch 上万，
                #    但 1011 万样本 / 16384 ⇒ 每轮仍有 617 次同步。
                b = loss.detach() * len(idx)
                tot = b if tot is None else tot + b
            sch.step()
            tot = 0.0 if tot is None else float(tot) / n
            if verbose and (ep + 1) % 20 == 0:
                msg = f"    mlp ep{ep + 1:>4}  loss={tot:.4f}"
                if val is not None:
                    p = self.predict(val[0])
                    msg += f"  val_loss={_bce(p, val[1]):.4f}  val_acc={_acc(p, val[1]):.3f}"
                print(msg)
        return self

    def predict(self, X):
        self.net.eval()
        with torch.no_grad():
            return torch.sigmoid(self.net(self._prep(X))).detach().cpu().numpy().ravel()

    def state(self):
        return {"kind": self.name, "nfeat": self.nfeat, "hidden": list(self.hidden),
                "sd": None if self.sd is None else self.sd.tolist(),
                "mu": None if self.mu is None else self.mu.tolist(),
                "sd_dict": {k: v.detach().cpu().tolist()
                            for k, v in self.net.state_dict().items()}}

    def restore(self, st):
        self.mu = np.asarray(st["mu"], dtype=np.float32)
        self.sd = np.asarray(st["sd"], dtype=np.float32)
        self.net.load_state_dict({k: torch.tensor(v, device=self.device)
                                 for k, v in st["sd_dict"].items()})
        return self


def _bce(p, y):
    p = np.clip(np.asarray(p, dtype=np.float64), 1e-7, 1 - 1e-7)
    y = np.asarray(y, dtype=np.float64)
    return float(-(y * np.log(p) + (1 - y) * np.log(1 - p)).mean())


def _acc(p, y):
    return float(((np.asarray(p) >= 0.5).astype(float) == np.asarray(y)).mean())


def metrics(p, y):
    """常用的几个指标（不引 sklearn，保持零额外依赖）"""
    p = np.asarray(p, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)
    base = max(y.mean(), 1 - y.mean())
    # AUC：用秩和公式，O(n log n)
    order = np.argsort(p)
    ranks = np.empty(len(p), dtype=np.float64)
    ranks[order] = np.arange(1, len(p) + 1)
    n1, n0 = y.sum(), (1 - y).sum()
    auc = 0.5
    if n1 > 0 and n0 > 0:
        auc = float((ranks[y == 1].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))
    return {"bce": _bce(p, y), "acc": _acc(p, y), "base": float(base), "auc": auc}


def save(model, path, names=None):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    blob = {"model": model.state(), "names": list(names or [])}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(blob, f, ensure_ascii=False)
    return path


def load(path, device="cpu"):
    with open(path, encoding="utf-8") as f:
        blob = json.load(f)
    st = blob["model"]
    if st["kind"] == "logi":
        m = LogiNet(st["nfeat"], l2=st.get("l2", 1e-3), device=device)
        m.lin.weight.data = torch.tensor(
            np.asarray(st["w"], dtype=np.float32), device=device).reshape(1, -1)
        m.lin.bias.data = torch.tensor([st["b"]], dtype=torch.float32, device=device)
        m.mu = np.asarray(st["mu"], dtype=np.float32)
        m.sd = np.asarray(st["sd"], dtype=np.float32)
    else:
        m = MLPNet(st["nfeat"], hidden=tuple(st["hidden"]), device=device)
        m.restore(st)
    return m, blob.get("names") or []


if __name__ == "__main__":
    # 自检：造一批有明显规律的假数据，看两种模型能否学出来
    rng = np.random.default_rng(0)
    n, d = 4000, 8
    X = rng.normal(size=(n, d)).astype(np.float32)
    true_w = np.array([2.0, -1.5, 0.0, 0.0, 1.0, 0.0, -0.5, 0.0], dtype=np.float32)
    logit = X @ true_w + rng.normal(scale=0.5, size=n)
    Y = (logit > 0).astype(np.float32)
    for m in (LogiNet(d), MLPNet(d)):
        m.fit(X, Y, verbose=False)
        mm = metrics(m.predict(X), Y)
        print(f"  {m.name:<5} acc={mm['acc']:.3f}  auc={mm['auc']:.3f}  bce={mm['bce']:.4f}"
              f"   （真权重 {true_w.tolist()}）")
        if isinstance(m, LogiNet):
            print("      学到：", [(i, round(w, 2)) for i, w in enumerate(m.lin.weight.detach().numpy().ravel())])
