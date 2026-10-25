# -*- coding: utf-8 -*-
"""GPU 常驻训练守护 —— 自对弈在跑的同时，把 GPU 喂饱

    python tools/gpu_daemon.py --parts /root/autodl-tmp/data/sp2.parts \
        /root/autodl-tmp/data/selfplay_150k.parts --rounds 0 --idle 5

★★ 2026-10-02 第二次修：「守护饿着肚子空转」（老师："GPU 基本上空置，你好好运用哦"）
  症状：`gpu_daemon_status.json` 里 `gpu.mean = 7.6 / p50 = 0.0`（第二轮实测 **4.6%**），
        `nvidia-smi` 采样 0/10/41/41/9 —— 而老代码**自己就知道**它闲着。
  根因（与算力无关，是"喂料不足"）：
    守护只读 `--parts` 给的**一个**目录。第二轮为了做干净 A/B 开了新目录 `sp2.parts`，
    于是守护手里只有 **2.7 万样本**，而 `mlp_512_256` 的 batch 就是 **16384** ⇒
    **一个 epoch 只有 2 步矩阵乘**，剩下时间全在等 kernel launch 和数据搬运。
    与此同时盘上躺着第一轮的 **1130 片 / 1011 万样本**（`selfplay_150k.parts`）没人读。
  修法（三处）：
    ① `--parts` 支持**多目录**（新数据 + 旧数据合并喂）；`seen` 键必须含**目录名**
       —— 两个目录的分片**同名**（都是 part00000.npz），只按文件名去重会把旧数据整批漏读。
    ② `data()` 加 **concat 缓存**（只在有新分片时重拼）—— 1011 万样本每轮重拼一次
       就是 1.29 GB 的无谓拷贝，且会跟自对弈抢 CPU。
    ③ 新增 `--threads`（默认 2）⇒ `torch.set_num_threads`。
       **故意不用满核**：15 核要留给 14 个自对弈 worker（那是产数据的源头），
       GPU 计算只靠 kernel launch，2 个 CPU 线程足够，抢多了反而拖慢自对弈。

【为什么需要它】（老师 2026-10-01 指出：GPU 使用率高峰不超过 18%，太浪费）
  自对弈产数据是 **100% CPU** 的活儿（numba 内核），GPU 全程闲着 ——
  实测 `nvidia-smi` utilization = **0%**。而训练那一版 MLP(64×32) 只跑 ~50s，
  跑完就再也不碰 GPU ⇒ 3.5 小时的窗口里 GPU 干活不到 1 分钟。

【它做什么】
  常驻循环，每一轮：
    ① 增量读入 `*.parts/` 里**新出现**的分片（自对弈还在写，只读已完成的）；
    ② 固定切分训练/验证；
    ③ 按 `BATTERY` 逐个训网络（**大 batch + 宽隐层**，故意把单步 matmul 做大，
       否则 kernel launch 开销会把利用率压在 10% 上下）；
    ④ 记 val AUC / acc / **稳健性矛盾对数** / 送马专项；
    ⑤ 把「验证 AUC 最高且稳健性达标」的那一版写到 `value_mlp.json`（best-so-far）；
    ⑥ 写 `status.json`（含 GPU 利用率采样均值）供外面监控。
  ⇒ 数据越攒越多，权重越好；GPU 占空比由 `--idle` 控制（idle=20s ⇒ 约 90%）。

【为什么要「稳健性矛盾对数」这一关】
  开局 44 手两两比：特征 L∞<0.10（肉眼一样）却给出 |ΔP|>0.05（判若两人）计一次矛盾。
  800 局那版 mlp 是 **148 对 ❌** ⇒ 它在噪声里排名，不能上线。
  **AUC 高但矛盾多 = 假繁荣**，两个都要看。

★★ 2026-10-02 第三次修：三处「观测/产物」层的病（都不是算法问题）
  ① **冒烟运行污染正式产物**：11:33 一次 ~80 秒的冒烟运行把 D1 轮 1 花 41 分钟
     训出的 `value_mlp.json` 原地覆盖成它自己 22.7 秒的产物。
     ⇒ 新增 `--tag`：调试只写 `value_mlp_<tag>.json`，正式文件绝不动。
     副作用（真正贵的那个）：它让我一小时后对着一份**来路不明**的权重做复现，
     得出"报告 0.6547 ≠ 实盘 0.5350"的假矛盾，白查了半天。
     ⇒ 另加「权重指纹」（`best.file/bytes/mtime`）进 status，**先核指纹再下结论**。
  ② **status 只在轮末写**：一轮 20+ 分钟 ⇒ 外面 2 分钟一跳的心跳一直读到
     上一轮的陈旧值（11:49→12:18 死循环打印 `17.0 p50=8.5 n=8`），
     把"GPU 好着呢"显示成"GPU 又闲了"。⇒ 每训完一个模型就原子写一次。
  ③ **`mean` 是全程累积均值**：早期读分片的 0% 会永久拉低它。
     ⇒ `mean/p50/max` 改滑动窗口（近 10 分钟），全程值另放 `mean_all`。
  ④ **容量不是瓶颈了**（实测）：512 / 1024 / 2048 三档 AUC 差 0.0003，
     而 2048 版墙钟是 512 版的 **10.3 倍** ⇒ 改成 `every=4`，省下的时间换轮次。
"""
import argparse
import copy
import hashlib
import json
import os
import subprocess
import sys
import threading
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRV = os.path.join(ROOT, "server")
for _p in (SRV, os.path.join(SRV, "engine"), os.path.join(SRV, "agents"), HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from agents import value_net as VN                            # noqa: E402
from agents import features_dxf as F                          # noqa: E402
from train_cloud import consistency_check, demo_hanging       # noqa: E402

OUTDIR = os.path.join(SRV, "agents", "values")
#: 工具目录（对局门禁要调 `ab_match.py`）
TOOLS_DIR = HERE

#: 每轮的模型清单。**大 batch + 宽隐层**是给 GPU 找活干的关键：
#:   batch 太小 ⇒ 每步 matmul 几十微秒，Python/kernel launch 开销占 90%，
#:   `nvidia-smi` 利用率就只有个位数。
BATTERY = [
    # `every=N` ⇒ 只在第 N、2N、3N… 轮跑（见训练循环里的注释）。
    # ★ 2026-10-01 22:00 实测改版依据（第 1 轮 299.4s，GPU 采样均値仅 65.0%、p50=93%=
    #   典型的"大部分时间饱和 + 一段真空转"）：logi 54.1s + mlp_128_64 49.4s = **103.5s**，
    #   与那约 100s 的 0% 采样几乎完全吻合。原因是这两个网络**太小**：
    #   单步 matmul 只有几十微秒，被 Python 的 zero_grad/forward/loss/backward/step
    #   开销彻底淹没 ⇒ nvidia-smi 真看到 GPU 闲着，而墙钟照样在走。
    #   代价却是 1/3 的轮次时间，买到的 AUC（0.6219 / 0.6552）还不如中等网络（0.6548）。
    #   ⇒ 小模型改成**错轮跑**（保住可解释基线 value_logi.json），
    #     省下的时间全部加到重模型上（加长 epochs），让 GPU 每一秒都是真计算。
    dict(name="logi",           hidden=None,           epochs=100, lr=0.05,  batch=4096, every=3),
    dict(name="mlp_128_64",     hidden=(128, 64),      epochs=200, lr=1.5e-3, batch=8192, every=3),
    dict(name="mlp_512_256",    hidden=(512, 256),     epochs=400, lr=1.0e-3, batch=16384),
    dict(name="mlp_1024_512",   hidden=(1024, 512),    epochs=400, lr=8e-4,  batch=32768),
    # ★★ 2026-10-02 第三次修：`mlp_2048_1024` 改为**错 4 轮跑一次**。
    #   实测依据（第一轮 D1 同一验证集，三个档位一字排开）：
    #       mlp_512_256    auc=0.6544  旧 0.6551  sp2 0.5403   186.9s
    #       mlp_1024_512   auc=0.6547  旧 0.6555  sp2 0.5404   335.2s
    #       mlp_2048_1024  auc=0.6547  旧 0.6555  sp2 0.5391  1928.9s
    #   ⇒ 2048 版比 512 版多花 **10.3 倍**墙钟，AUC 只多 **0.0003**（且和 1024 版打平）。
    #     网络容量**已经不是瓶颈** —— 三个档位的差异全在噪声里 ⇒
    #     继续堆容量是纯浪费 GPU；真正的短板是 sp2 那 0.54（数据/标签质量，见铁律 151/152）。
    #   ⇒ 省下的 ~13 分钟/轮 换成**更多轮次**：每轮都能吃到最新产出的 sp2 分片，
    #     AUC 曲线（同验证集口径）才能当"新标签到底有没有用"的进度条用。
    dict(name="mlp_2048_1024",  hidden=(2048, 1024),   epochs=350, lr=6e-4,  batch=65536, every=4),
]

#: 每轮训练的**子采样上限**（样本数）。0 = 不限制（用全部）。
#:
#: ★★ 2026-10-02 修正 —— 它推翻了我当天早些时候写的 `TARGET_STEPS` 写法。
#:   当时我用「固定**总步数**」（TARGET_STEPS=40000）控墙钟，在 1035 万样本下
#:   把 `mlp_1024_512` 的 epochs 从 400 砍到 **129**。后果是**欠拟合**：
#:     同一批 18 万旧样本上实测（预测值范围都正常 0.012~0.996，排除加载问题）
#:         129 epochs（云端新权重，1035 万混合训练） AUC **0.5340** ❌
#:         400 epochs（本地归档权重，第一轮 30 万局） AUC **0.6544** ✅
#:   ⇒ **关键量是「数据遍历次数」(epochs)，不是「总步数」。**
#:     固定总步数 = 用更大的数据集换取更少的遍历 ⇒ 等于没训够。
#:   正确做法：**满 epochs 保住收敛，改用"子采样"控墙钟** ——
#:     · 每轮从训练集随机抽 ≤MAX_TRAIN 个样本（每轮换子集，长期覆盖全量）；
#:     · **验证集划分仍用固定种子** ⇒ 各轮同口径，AUC 可比。
#:   代价：单轮墙钟仍约 10~20 分钟（满 400/350 epochs），这是**为棋力付的必要成本**。
MAX_TRAIN = 3_000_000


# ---------------------------------------------------------------- GPU 采样
class GpuSampler(threading.Thread):
    """后台每 10s 记一次 nvidia-smi 利用率，用来算**平均占空比**（老师的验收指标）。"""

    def __init__(self, period=10.0):
        super().__init__(daemon=True)
        self.period = period
        self.samples = []
        self._stop = threading.Event()

    def run(self):
        while not self._stop.is_set():
            try:
                out = subprocess.run(
                    ["nvidia-smi", "--query-gpu=utilization.gpu",
                     "--format=csv,noheader,nounits"],
                    capture_output=True, text=True, timeout=8).stdout.strip()
                if out:
                    self.samples.append(int(out.splitlines()[0]))
            except Exception:                          # noqa: BLE001
                pass
            self._stop.wait(self.period)

    def stop(self):
        self._stop.set()

    def summary(self, window=60):
        """→ {'n','mean','p50','max','mean_all'}。

        ★★ 2026-10-02 第三次修：`mean/p50/max` 改成**最近 `window` 个样本**
          （默认 60 ⇒ 约 10 分钟），不再是全程累积均值。
        起因（这是一次**监控把真话说反了**的事故）：
          autopilot 心跳读这个文件当"当前占空比"，而它只在**轮末**写盘。
          一轮 20+ 分钟 ⇒ 心跳从 11:49 到 12:18 一直打印同一个
          `守护均值 17.0 p50=8.5 n=8`，看着像"GPU 又闲着了"；
          真相是 11:33 那次 80 秒的冒烟运行留下的**陈旧读数**，此后
          D2/D3 再没落盘过，而瞬时读数**反复是 100%**。
        另外全程累积均值本身也不适合当"当前值"：早期读分片的 0% 会永久
        拉低它，跑得越久越失真。⇒ 当前值用滑动窗口，全程值另放 `mean_all`。
        """
        if not self.samples:
            return {"n": 0, "mean": None, "p50": None, "max": None, "mean_all": None}
        a = np.asarray(self.samples, dtype=float)
        w = a[-int(window):] if window and len(a) > int(window) else a
        return {"n": len(self.samples),
                "mean": round(float(w.mean()), 1),
                "p50": round(float(np.median(w)), 1),
                "max": round(float(w.max()), 1),
                "mean_all": round(float(a.mean()), 1)}


# ---------------------------------------------------------------- 分片增量加载
class PartCache:
    """只读**新出现**的分片 —— 自对弈还在写，每轮全量重读会白烧 I/O。

    2026-10-02：支持**多目录**（第二轮 `sp2.parts` + 第一轮 `selfplay_150k.parts`）。
    ⚠️ 两个目录的分片**同名**（都是 `part00000.npz`）⇒ `seen` 的键必须是
       `(目录, 文件名)`，只按文件名去重会把整个旧目录当"已读过"而**整批漏读**。
    """

    def __init__(self, parts_dirs):
        if isinstance(parts_dirs, str):
            parts_dirs = [parts_dirs]
        self.dirs = [d for d in parts_dirs if os.path.isdir(d)]
        self.names = [os.path.basename(d) for d in self.dirs]
        self.seen = set()                  # {(目录, 文件名)} —— 非要 dir 参与不可
        self.Xs, self.Ys = [], []
        self.Ss = []                       # 每片的**来源目录下标**，广播成逐行
        self.gkeys = []                    # ★ 每槽的**稳定键** "目录下标/文件名"
        self.gsize = []                    # ★ 每槽行数。两者合起来 = 「分组」索引，
        #   给"冻结验证集"用：整片进出 ⇒
        #   ① 各轮验证集**逐行相同**（AUC 才可比，见 `frozen_val_keys`）
        #   ② 同一局保存的 40 个局面**不会**一半在训练一半在验证（同局泄漏）
        #   键里含目录下标而不是全局序号：新分片只会**追加**，已存在的键永不变。
        self._counts = {d: 0 for d in self.dirs}
        self._cached = None                # concat 结果缓存（大样本集绝不能每轮重拼）

    def refresh(self):
        new = 0
        for di, d in enumerate(self.dirs):
            try:
                names = sorted(os.listdir(d))
            except OSError:
                continue
            for fn in names:
                if not fn.endswith(".npz"):
                    continue
                key = (d, fn)
                if key in self.seen:
                    continue
                try:
                    z = np.load(os.path.join(d, fn))
                    if len(z["Y"]):
                        self.Xs.append(z["X"])
                        self.Ys.append(z["Y"])
                        self.Ss.append(np.full(len(z["Y"]), di, dtype=np.int8))
                        self.gkeys.append(f"{di}/{fn}")
                        self.gsize.append(int(len(z["Y"])))
                        new += 1
                        self._counts[d] += 1
                    self.seen.add(key)
                except Exception:                      # noqa: BLE001
                    pass                               # 正在写：下一轮再读
        if new:
            self._cached = None                        # 有新料 ⇒ 让 concat 缓存失效
        return new

    def data(self):
        """→ (X, Y, S)，S 是逐行的来源目录下标。

        ★ 为什么要带 S（2026-10-02）：现在训练集是「旧 1011 万（标签有噪声）
        + 新 sp2（标签干净）」的混合体，**合起来的 AUC 会被旧数据稀释**，
        看不出标签修复有没有用。带上来源下标就能在验证集上**分开算 AUC**：
        旧数据 AUC 反映"基础信号"，新数据 AUC 反映"修复后标签到底值多少"。
        """
        if not self.Xs:
            return None, None, None
        if self._cached is None:
            self._cached = (np.asarray(np.concatenate(self.Xs), dtype=np.float32),
                            np.asarray(np.concatenate(self.Ys), dtype=np.float32),
                            np.asarray(np.concatenate(self.Ss), dtype=np.int8))
        return self._cached

    def stats(self):
        """{目录名: 已读片数} —— 打日志用，一眼看出"旧数据吃了多少、新数据涨了多少"。"""
        return {os.path.basename(d): c for d, c in self._counts.items()}

    # ------------------------------------------------------------ 分组（冻结验证集用）
    def group_mask(self, keys):
        """给定一组**稳定键** → 逐行 bool 掩码（顺序与 `data()` 的 X/Y 行序一致）。

        没读到的键直接跳过（不报错）：新文件还没出现时也能用。
        """
        ks = set(keys)
        m = np.zeros(int(sum(self.gsize)), dtype=bool)
        off = 0
        for k, n in zip(self.gkeys, self.gsize):
            if k in ks:
                m[off:off + n] = True
            off += n
        return m

    def rows_of(self, keys):
        return int(sum(n for k, n in zip(self.gkeys, self.gsize) if k in set(keys)))


def frozen_val_keys(cache, path, target, prefer_dir_idx, rebuild=False):
    """**冻结验证集**：把验证集固定成"某批分片"，之后每轮都用同一批。

    ★ 为什么必须冻结（2026-10-02 实测踩到，后果很重）：
      原实现是
          rng = np.random.default_rng(20261001); idx = rng.permutation(len(Y))
          nval = int(len(Y) * a.val_frac)
      注释写着"固定种子 ⇒ 各轮验证集同口径"——**这句话是错的**。
      `len(Y)` 每轮都在涨，同一个种子配上**不同的长度**，得到的是**完全不同的一套
      洗牌**，`nval` 也在涨。于是每轮的 AUC 其实是**换了一把尺子量出来的**：
        ① **跨轮不可比**：冠军存的 auc 是旧尺子上的数，候选是新尺子上的数，
           两者直接比 ⇒ 候选**永远追不上** ⇒ 一晚上白跑（日志里连 6 轮
           0.6445→0.6421 单调下滑，就是这个漂移，不是模型变差）；
        ② 验证集里**新数据占比逐轮上升**，而新源自身分源 AUC 只有 0.56
           ⇒ 整体 AUC 被单调拖低，冠军的数越来越"不可达"。
      ⇒ 冻结：键（目录下标/文件名）落盘一次，之后**只读**。新分片只进训练不进验证。

    ★ 顺带修掉同局泄漏：整片进出 ⇒ 同一局保存的 40 个局面不会一半在训练、
      一半在验证（实测泄漏量 0.005~0.012，不算大，但"整片进出"是零成本的正确做法）。

    返回 `(keys:set, vid:str)`；`vid` 是这把尺子的指纹，冠军记录里存它 ——
    指纹一变就说明"换了尺子"，必须重测冠军（否则比较无意义）。
    """
    if os.path.exists(path) and not rebuild:
        try:
            with open(path, encoding="utf-8") as f:
                d = json.load(f)
            if d.get("keys"):
                return set(d["keys"]), str(d.get("id", ""))
        except Exception:                              # noqa: BLE001
            pass
    sizes = dict(zip(cache.gkeys, cache.gsize))
    # 默认（prefer_dir_idx < 0）从**所有目录**按行数比例抽 ——
    #   这样冻结的尺子仍然覆盖各来源，`分源 AUC` 这条诊断线不会断；
    #   给非负下标则只从那个目录抽（想要"纯静态"的尺子时用）。
    if prefer_dir_idx is not None and prefer_dir_idx >= 0:
        pool = [k for k in cache.gkeys if k.startswith(f"{prefer_dir_idx}/")]
    else:
        pool = list(cache.gkeys)
    if len(pool) < 2:
        pool = list(cache.gkeys)
    if not pool:
        return set(), ""
    # ⚠️ 2026-10-02 冒烟抓到的 bug（写在这里防止回退）：
    #   第一版我写的是"逐行均匀抽"——`acc += step` 的 while 循环会把**同一个文件
    #   反复命中**，去重后**整个池子全进验证集**（实测：52,182 行全进验证，
    #   训练集 0 行，AUC 掉到 0.503 的纯噪声）。
    #   ⇒ 正确做法：先按"目标行数 / 池子平均每片行数"估出**要抽几片**，
    #     再在片序号轴上**等间距**取（保证覆盖早/中/晚），最后按行数收敛。
    tot_pool = int(sum(sizes[k] for k in pool))
    mean_rows = max(1.0, tot_pool / float(len(pool)))
    m = int(round(max(1, min(int(target), tot_pool)) / mean_rows))
    m = max(1, min(m, len(pool)))
    if m >= len(pool) and len(pool) > 1:
        m = len(pool) - 1                              # 必须给训练集留料
    picked = [pool[i] for i in np.linspace(0, len(pool) - 1, m).astype(int)]
    keys = list(dict.fromkeys(picked))                 # 去重且保序
    nrows = int(sum(sizes[k] for k in keys))
    h = hashlib.md5("|".join(sorted(keys)).encode("utf-8")).hexdigest()[:8]
    src_nm = (cache.names[prefer_dir_idx]
              if (prefer_dir_idx is not None and 0 <= prefer_dir_idx < len(cache.names))
              else "全部目录")
    vid = f"{len(keys)}片/{nrows:,}行/{src_nm}/{h}"
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"keys": sorted(keys), "id": vid, "rows": nrows,
                   "prefer": src_nm,
                   "target": int(target), "built_at": time.strftime("%Y-%m-%d %H:%M:%S")},
                  f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)
    print(f"   🔒 新建冻结验证集 → {path}\n      {vid}", flush=True)
    return set(keys), vid


# ---------------------------------------------------------------- 训练一轮
def train_one(cfg, Xtr, Ytr, Xva, Yva, feat_names, dev, verbose=False, epochs=None):
    t0 = time.time()
    ep = int(epochs) if epochs else int(cfg["epochs"])
    if cfg["hidden"] is None:
        m = VN.LogiNet(Xtr.shape[1], device=dev)
        m.fit(Xtr, Ytr, epochs=ep, lr=cfg["lr"], batch=cfg["batch"])
    else:
        m = VN.MLPNet(Xtr.shape[1], hidden=cfg["hidden"], seed=0, device=dev)
        m.fit(Xtr, Ytr, epochs=ep, lr=cfg["lr"], batch=cfg["batch"],
              val=(Xva, Yva) if verbose else None)
    p = m.predict(Xva)
    mt = VN.metrics(p, Yva)
    return m, mt, p, time.time() - t0


def subsample(X, Y, cap, seed):
    """每轮随机抽 ≤cap 个训练样本 —— 见 `MAX_TRAIN` 上方那段实测依据。

    ★ 为什么是"抽数据"而不是"砍 epochs"（2026-10-02，这是当天第二次纠正）：
      机制上，8ms/步 的开销由 kernel launch 决定，**跟 batch 无关** ⇒
      想缩短墙钟，要么少走几步（砍 epochs ⇒ 欠拟合，已实测 AUC 0.5340），
      要么每步少看些数据（子采样 ⇒ 遍历次数不变，收敛不受影响）。
      **墙钟 ∝ epochs × (样本数/batch)**，所以固定 epochs、压样本数才是对的方向。
      每轮换 seed ⇒ 长期看所有数据都会被用到，不是丢弃。
    """
    if not cap or len(Y) <= cap:
        return X, Y
    sel = np.random.default_rng(seed).choice(len(Y), int(cap), replace=False)
    return X[sel], Y[sel]


def subsample_by_src(X, Y, S, cap, seed, mode="all"):
    """→ (X, Y, S)。按 `mode` 决定训练样本的**来源配比**。

    ★★ 2026-10-02 新增，起因是一个把自己骗了很久的盲点：
      守护一直把 `sp2`（新、干净标签）和 `selfplay_150k`（旧、**已知有噪声**标签）
      **放在一起按总量抽**，而旧数据是 1027 万、sp2 只有 51 万 ⇒ 旧数据天然占 95%。
      表面上 AUC 0.65 很好看、分源也打印了，但我从没问过
      "**混合模型的决策面到底是谁的**"。

      云端实测（`_对照实验/_x_cloud_src_diag.py`，2×2 跨源矩阵，mlp_128_64，同验证集）：
                    验证 sp2   验证 old
          训练 sp2     0.6369     0.5476
          训练 old     0.5425     0.6520
          (标签打乱)    0.4874     0.4895
      · sp2→sp2 0.6369  **高于**  old→sp2 0.5425（Δ=+0.094）
        ⇒ **sp2 的干净标签确实带了旧模型学不到的信息**，这批数据没白产
        （"sp2 标签弱"的假设被推翻；打乱对照 ≈0.49 证明管线健康、0.64 是真信号）。
      · 而**混合模型**在 sp2 上只有 0.539~0.553 —— 和 `old→sp2`（0.5425）**几乎相等**
        ⇒ 铁证：混合模型的决策面**基本就是"旧数据模型"**，干净标签被淹了。
        ⇒ 等于**一直在拿有噪声的旧标签上线**，这正是棋力上不去的原因之一。

    mode：
      · ``all``      —— 老行为（按总量抽，旧数据 ~95%）。**默认不动，随时可回退。**
      · ``balanced`` —— **每个来源等量**贡献（各 ≤ cap/来源数）。
      · ``only0``    —— 只用第一个 `--parts` 目录（约定 = 新数据）。
    """
    if mode == "all" or not cap:
        if not cap or len(Y) <= cap:
            return X, Y, S
        sel = np.random.default_rng(seed).choice(len(Y), int(cap), replace=False)
        return X[sel], Y[sel], S[sel]

    srcs = np.unique(S)
    if mode == "only0":
        keep = np.nonzero(S == srcs[0])[0]
        if len(keep) > cap:
            keep = keep[np.random.default_rng(seed).choice(len(keep), int(cap),
                                                           replace=False)]
        return X[keep], Y[keep], S[keep]

    # balanced：每源配额相同；小源（样本不够）就全用，不补差
    per = max(1, int(cap) // len(srcs))
    parts = []
    for i, s in enumerate(srcs):
        idx = np.nonzero(S == s)[0]
        if len(idx) > per:
            idx = idx[np.random.default_rng(seed + 31 * (i + 1)).choice(
                len(idx), per, replace=False)]
        parts.append(idx)
    sel = np.concatenate(parts)
    sel = sel[np.random.default_rng(seed + 7).permutation(len(sel))]   # 打散，别成块
    return X[sel], Y[sel], S[sel]


# ---------------------------------------------------------------- 冠军持久化
def _md5_file(path, cap=1 << 22):
    """算文件 md5（只读前 4MiB 就够做身份指纹，值 3.5MB 的权重本来就小于它）。"""
    h = hashlib.md5()
    try:
        with open(path, "rb") as f:
            while True:
                b = f.read(cap)
                if not b:
                    break
                h.update(b)
    except OSError:
        return ""
    return h.hexdigest()


def load_champion(champ_p, mlp_p):
    """从 `champion.json` 复原"当前冠军"，让 `best` **跨进程重启不丢**。

    ★ 为什么必须做（2026-10-02 实测事故）：
      `best` 原来只是**进程内变量**。我为了做对照实验停了守护，autopilot 又把它
      拉起来 —— 新进程 `best=None` ⇒ **本轮不管 AUC 多少都会写 value_mlp.json**。
      于是 12:33 写入的 `auc=0.6496` 被 13:33 一轮 `auc=0.6467` 原地覆盖。
      而当天 A/B 恰好横跨这两个时间点，导致我一度以为"两份权重棋力差一倍"。
      （真正的原因见对局台诊断：`tl`，不是这两份权重的差别。）
    ⇒ 规则：**冠军是跨进程的状态，必须落盘**；进程重启后只允许更强的候选替换它。
    """
    try:
        with open(champ_p, encoding="utf-8") as f:
            c = json.load(f)
    except Exception:                                   # noqa: BLE001
        return None
    if not c or not os.path.exists(mlp_p):
        return None
    cur = _md5_file(mlp_p)
    if c.get("md5") and cur and c["md5"] != cur:
        print(f"   ⚠ champion.json 记的 md5 {c['md5'][:8]} ≠ 现场文件 {cur[:8]}"
              f" ⇒ 不认这个冠军（现场文件是外人写的）", flush=True)
        return None
    print(f"   ⤺ 接手上一轮的冠军：{c.get('name')} auc={c.get('auc')} "
          f"（{c.get('saved_at', '?')} 写的，md5 {cur[:8]}）", flush=True)
    return c


def save_champion(champ_p, best, mlp_p):
    """把冠军身份写盘（含 md5 指纹 —— 下次接手时要核）。"""
    c = dict(best)
    c["md5"] = _md5_file(mlp_p)
    c["saved_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    tmp = champ_p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(c, f, ensure_ascii=False, indent=1)
    os.replace(tmp, champ_p)
    return c


# ---------------------------------------------------------------- 对局门禁
#: 门禁用的**固定标尺**：把被测权重放到"两台**完全相同**的纯搜索"对面。
#:   种子固定 ⇒ 历次候选的成绩可直接比。
#:   为什么不用 `{none, 冠军, 候选}`：实测（C/D/L 六组）**两台价值网络同场时
#:   三方全平**（判和率 31%→54%）⇒ 那个场次**根本分辨不出孰强孰弱**，
#:   门禁会永远不放行。而 `{n1, n2, X}` 在 V1/V2 两批里 X 都稳定领先
#:   6~8 个胜率点（18.7~21.7% → 26.0~26.7%）⇒ 这个标尺有分辨力。
YARD_SEED = 2200000
#: 上位门槛：候选的序数分至少要比冠军的标尺成绩高这么多
#:   （300 局的空对照地板约 ±15~24 分，取 25 表示"必须超出地板"）
YARD_MARGIN = 25
#: AUC 的**筛查容差**：候选只要不比冠军低过这么多，就允许它**去跑门禁**。
#:   ★ 为什么不再要求"auc 必须超过冠军"：AUC 是在一把**冻结的尺子**上量的
#:     （`frozen_val_keys`），而冻结之前它是**每轮换一把尺子** —— 于是
#:     "cand.auc > best.auc" 实际是拿两把尺子的数硬比，冠军一封就锁死一切候选。
#:     现在的分工：**AUC 只筛垃圾**（同一把尺子上"没落后"），
#:     **升不升级由对局门禁说了算**（SOUL 162：AUC 不能选冠军）。
VAL_TOL = 0.005


def yard_score(tools_dir, wfile, games, workers, tl, tag, seed0=YARD_SEED):
    """把一份权重放到 `{n1, n2, 它自己}` 里跑一局，量出它的**标尺成绩**。

    返回 {"ordi": 序数胜场之和, "wins": 胜局之和, "games": 局数} 或 None（跑失败）。
    """
    import subprocess as sp
    out = os.path.join(os.path.dirname(os.path.abspath(wfile)),
                       f"_yard_{tag}.json")
    cmd = [sys.executable, "-u", os.path.join(tools_dir, "ab_match.py"),
           "--games", str(games), "--workers", str(workers), "--tl", str(tl),
           "--depth", "1", "--maxply", "300", "--threads", "1",
           "--seed0", str(seed0),
           "--cfg", "n1=-", "--cfg", "n2=-",
           "--cfg", f"x={os.path.basename(wfile)}",
           "--out", out]
    try:
        sp.run(cmd, cwd=os.path.dirname(tools_dir), capture_output=True,
               text=True, timeout=7200)
    except Exception as e:                              # noqa: BLE001
        print(f"   ⚠ 标尺跑不起来（{type(e).__name__}: {e}）", flush=True)
        return None
    try:
        with open(out, encoding="utf-8") as f:
            rep = json.load(f)
    except Exception as e:                              # noqa: BLE001
        print(f"   ⚠ 标尺报告读不出（{type(e).__name__}: {e}）", flush=True)
        return None
    ordi = wins = 0
    for p in rep.get("pairs", []):
        if "x" not in (p["x"], p["y"]):
            continue
        bx = p["bx"] if p["x"] == "x" else p["by"]
        nx = p["n_x"] if p["x"] == "x" else p["n_y"]
        ordi += bx
        wins += nx
    return {"ordi": int(ordi), "wins": int(wins),
            "games": int(rep.get("games", 0)), "seed0": int(seed0)}


GATE_LOCK = os.path.join(OUTDIR, "gate.lock")


def _gate_lock(on, note=""):
    """标记"守护正在跑门禁标尺"。

    【为什么必须有这个锁】2026-10-02 实测活锁：
      门禁是**纯 CPU 对局**（300 局，跑三台搜索 Bot），全程 GPU 占用 0%。
      而 cloud_autopilot.sh 的自保判据是「守护活着但 GPU 连续 6 分钟 <5%
      ⇒ 判定卡死并重启」。它**不知道**门禁期间空转是合法的，于是：
        16:45:43 写候选 → 开门禁 → 16:47/16:49/16:51 三次心跳都是 0%
        → 16:51:35 autopilot **kill 守护**（EXIT=143）→ 16:51:40 重新拉起
        → 又从"[轮 1] 训 mlp_512_256"开始 → 循环
      ⇒ `round` 永远停在 1，门禁永远跑不完，候选永远无法上位。
      （我在 autopilot 注释里估"门禁一次约 3 分钟"，实测 **>6 分钟**，
        正好越过自保阈值 —— 估算错一点，系统就变成活锁。）

    锁文件内容 = 开始时间戳 + pid + 说明，供 autopilot 读；
    同时给 autopilot 一个"陈旧锁"兜底（守护崩了不会留下永不判零的死锁）。
    """
    try:
        if on:
            tmp = GATE_LOCK + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(f"{int(time.time())}\n{os.getpid()}\n{note}\n")
            os.replace(tmp, GATE_LOCK)
        elif os.path.exists(GATE_LOCK):
            os.remove(GATE_LOCK)
    except Exception:                            # noqa: BLE001
        pass


def arena_gate(tools_dir, cand_p, mlp_p, champ, games, workers, tl=5.0):
    """新候选必须先**在实战标尺上超过现冠军**才准上位（AlphaZero 的 gating）。

    【为什么不能只看 AUC】2026-10-02 实测：
      · 分源 AUC 从 0.55 提到 0.60（`--src-mix balanced`）⇒ 实战反而最差
      · 守护自己报的 AUC 长期稳定（0.6496/0.6494/0.6493/0.6492），
        但同期权重的实战表现差异远超"哪个冠军都行"的程度
      · 同一份权重在两组 A/B 里分别拿 36.3% / 17.0%
    ⇒ **AUC 只能筛掉垃圾，不能选冠军。** 上位必须过对局。

    返回 (promote: bool, 说明字符串, 候选标尺成绩 or None)。
    """
    if not os.path.exists(mlp_p):
        return True, "无现冠军，空场上位", None
    print(f"   ⚖ 开标尺：{os.path.basename(cand_p)} 对两台纯搜索"
          f"（{games} 局，seed0={YARD_SEED}）…", flush=True)
    # ★ 开门禁锁（见 `_gate_lock` 的说明）：标尺是纯 CPU 对局，这段 GPU 必然 0%。
    #   不打招呼，autopilot 就会按"守护卡死"在第 6 分钟把它腰斩（实测活锁）。
    t0 = time.time()
    _gate_lock(True, f"cand={os.path.basename(cand_p)} games={games} workers={workers}")
    try:
        s_cand = yard_score(tools_dir, cand_p, games, workers, tl, "cand")
        if s_cand is None:
            return False, "标尺跑不出来 ⇒ 保守不换", None
        yard = (champ or {}).get("yard")
        if not yard:
            print(f"   ⚖ 冠军还没有标尺成绩，先量一次…", flush=True)
            yard = yard_score(tools_dir, mlp_p, games, workers, tl, "champ")
            if yard is None:
                return False, "冠军标尺量不出来 ⇒ 保守不换", s_cand
        d_ordi = s_cand["ordi"] - yard["ordi"]
        ok = d_ordi >= YARD_MARGIN
        return ok, (f"候选 序数{s_cand['ordi']}/胜{s_cand['wins']} "
                    f"vs 冠军 序数{yard['ordi']}/胜{yard['wins']} "
                    f"⇒ Δ序数 {d_ordi:+d}（门槛 +{YARD_MARGIN}）"), s_cand
    finally:
        _gate_lock(False)
        # ★ 把**真实耗时**打出来：上一版我在 autopilot 注释里估"约 3 分钟"，
        #   实测 >6 分钟 ⇒ 恰好越过自保阈值 ⇒ 活锁。这个数字必须由在环数据说话。
        print(f"   ⚖ 门禁结束，本次耗时 {time.time() - t0:.0f}s"
              f"（autopilot 自保阈值 360s；超了就靠 gate.lock 豁免）", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--parts", required=True, nargs="+",
                    help="分片目录，可给多个（新数据在前、旧数据在后）")
    ap.add_argument("--rounds", type=int, default=0, help="0 = 无限循环")
    ap.add_argument("--idle", type=float, default=20.0, help="每轮结束后的空转秒数")
    ap.add_argument("--val-frac", type=float, default=0.1)
    ap.add_argument("--val-frozen", default="",
                    help="冻结验证集的定义文件（默认 <parts 的父目录>/val_frozen.json）。"
                         "★ 建一次、之后只读：验证集逐行固定，AUC 才跨轮可比。"
                         "见 `frozen_val_keys` 的实测依据（不冻结 = 每轮换尺子）")
    ap.add_argument("--val-rebuild", action="store_true",
                    help="重建冻结验证集（换了语料/口径时才用；会改变 AUC 的刻度）")
    ap.add_argument("--no-gpu", action="store_true")
    ap.add_argument("--threads", type=int, default=2,
                    help="torch 训练线程数。**故意小**：15 核留给自对弈产数据，"
                         "GPU 计算只靠 kernel launch，2 线程足够（抢多了拖慢自对弈）")
    ap.add_argument("--max-train", type=int, default=MAX_TRAIN,
                    help="每轮训练的子采样上限（样本数），0=用全部。见 MAX_TRAIN 注释")
    ap.add_argument("--src-mix", choices=("all", "balanced", "only0"), default="all",
                    help="训练样本的来源配比：all=按总量抽（旧数据占 ~95%，老行为）；"
                         "balanced=每个来源等量；only0=只用第一个 --parts 目录。"
                         "配比变了要配 --tag 另存，别覆盖正式权重（见 subsample_by_src）")
    ap.add_argument("--once", action="store_true", help="只跑一轮（调试用）")
    ap.add_argument("--gate-games", type=int, default=0,
                    help="★ 对局门禁局数：候选 AUC 超过冠军后，先跟冠军打这么多局，"
                         "**赢了才准覆盖正式权重**（0 = 关闭）。"
                         "AUC 只能筛垃圾不能选冠军，见 arena_gate 注释")
    ap.add_argument("--gate-workers", type=int, default=6,
                    help="门禁对局的并行进程数（别把自对弈的核抢光）")
    ap.add_argument("--only", default="",
                    help="只跑指定的档位（逗号分隔，如 mlp_512_256）。空=全部。"
                         "★ 做**受控对照**时必用：要比较两个配方，就必须保证"
                         "**除了配方以外的一切都相同**（同一个架构跑两遍），"
                         "否则差异里混着'网络容量'。默认关（跑全 BATTERY）。")
    ap.add_argument("--tag", default="",
                    help="调试/冒烟运行的后缀：非空时只写 value_mlp_<tag>.json，"
                         "**绝不覆盖正式的 value_mlp.json**")
    a = ap.parse_args()
    only = {s.strip() for s in a.only.split(",") if s.strip()}
    if only:
        bad = only - {c["name"] for c in BATTERY}
        if bad:
            sys.exit(f"✗ --only 里有 BATTERY 之外的档位：{sorted(bad)}")

    dev = "cpu" if a.no_gpu else VN.default_device()
    VN.torch.set_num_threads(max(1, a.threads))      # 别跟 14 个自对弈 worker 抢核
    cache = PartCache(list(a.parts))
    os.makedirs(OUTDIR, exist_ok=True)
    # ★★ 2026-10-02 第三次修：冒烟/调试运行必须写**另一个**文件名。
    #   事故经过：11:33 一次 ~80 秒的冒烟运行（`best.secs == 22.7`、GPU 采样 n=8）
    #   把 D1 轮 1 花 41 分钟训出的 `value_mlp.json`（mlp_1024_512, auc 0.6547）
    #   **原地覆盖**成了它自己 22.7 秒的产物（auc 0.6426）。
    #   后果不只是"权重变差" —— 它让我在一小时后对着一份**来路不明的文件**
    #   做复现，得出"报告与实盘不一致"的错误结论，白查了半天。
    #   教训：**正式产物与实验产物必须物理可分**（不能靠"我记得这次是冒烟"）。
    tag = (a.tag or "").strip()
    # 运行标识：`--tag`（调试）+ 来源配比，两者合成**一个**后缀。
    #   `--src-mix all` 且无 tag ⇒ 后缀为空 ⇒ 一切照旧（维护正式文件）。
    #   任何一项非默认 ⇒ 后缀非空 ⇒ **权重 / status / leaderboard 全部另存**，
    #   既不会污染正式产物，也不会让两个并发守护互相覆盖状态文件。
    #   ⇒ 想再开一个"均衡配比"守护，只需 `--src-mix balanced`（不必再加 --tag）。
    mix_sfx = {"all": "", "balanced": "bal", "only0": "only0"}[a.src_mix]
    run_sfx = "_".join(x for x in (tag, mix_sfx) if x)
    _sfx = f"_{run_sfx}" if run_sfx else ""
    f_mlp = f"value_mlp{_sfx}.json"
    f_logi = f"value_logi{_sfx}.json"
    status_p = os.path.join(OUTDIR, f"gpu_daemon_status{_sfx}.json")
    board_p = os.path.join(OUTDIR, f"gpu_leaderboard{_sfx}.json")
    champ_p = os.path.join(OUTDIR, f"champion{_sfx}.json")
    mlp_p = os.path.join(OUTDIR, f_mlp)
    # ★ 冻结验证集的定义文件。冒烟/调试运行**用另一个文件**（同 `--tag` 的道理：
    #   实验不该动正式的那把尺子）。
    val_path = a.val_frozen or os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(a.parts[0]))),
        f"val_frozen{('_smoke_' + run_sfx) if run_sfx else ''}.json")
    val_keys, val_id = None, ""

    sampler = GpuSampler()
    sampler.start()

    print("=" * 78)
    print(f"GPU 训练守护   设备={dev}   空闲={a.idle}s   训练线程={a.threads}"
          f"   训练集上限={a.max_train:,}   来源配比={a.src_mix}")
    for d in cache.dirs:
        print(f"   分片目录：{d}")
    if run_sfx:
        print(f"   ⚠ 非默认配方（后缀 {run_sfx}）⇒ 只写 {f_mlp} / {f_logi} / "
              f"gpu_daemon_status{_sfx}.json，**正式 value_mlp.json 与对外状态文件都不动**")
    print("=" * 78, flush=True)

    board, best = [], None
    rnd = 0
    Y = None
    #: 是否已经给"现场遗留的 value_mlp.json"封过冠军（只在第 1 轮做一次）
    sealed = False
    # ★★ 跨进程接手冠军（2026-10-02 第五次修）：**`load_champion` 之前定义了却没被
    #   调用**（死代码）⇒ `best` 每次重启仍是 None，只靠下面"现场封冠军"兜底。
    #   兜底能防"随手覆盖"，但**读不回 champion.json 里的 yard 成绩** ⇒ 每遇候选
    #   挑战都要重跑一次冠军标尺（3 分钟），而且 yard 会随进程一次次丢失。
    #   这里补上调用：接手成功 ⇒ `sealed = True`（不必再重复封一次）。
    #   ⚠️ md5 不符时 `load_champion` 返回 None ⇒ sealed 仍为 False ⇒ 兜底路径照常接管。
    if not run_sfx:
        _inherited = load_champion(champ_p, mlp_p)
        if _inherited is not None:
            best = _inherited
            sealed = True

    def _status(**kw):
        """把 status **原子**写盘（临时文件 + rename ⇒ 心跳进程绝不会读到半截 JSON）。

        ★ 2026-10-02 第三次修：轮末写一次（老行为）**外，每训完一个模型也写一次**。
          理由见 `GpuSampler.summary`：一轮 20+ 分钟才落一次盘，外面 2 分钟一跳的
          心跳就只能一直读到**上一轮的陈旧值**，把"GPU 好着呢"显示成"GPU 17%"。
        """
        d = {"round": rnd,
             "samples": int(len(Y)) if Y is not None else 0,
             "best": best,
             "gpu": sampler.summary(),
             "updated": time.strftime("%Y-%m-%d %H:%M:%S")}
        d.update(kw)
        tmp = status_p + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
        os.replace(tmp, status_p)

    while True:
        rnd += 1
        t_round = time.time()
        new = cache.refresh()
        X, Y, S = cache.data()
        if X is None:
            print(f"[轮 {rnd}] 还没有可用分片，等 20s…", flush=True)
            time.sleep(20)
            continue

        # ★★ 冻结验证集（2026-10-02 第六次修，也是最要紧的一次）——
        #   原实现（下面注释里那两行）**每轮换一把尺子**，见 `frozen_val_keys`：
        #     `rng.permutation(len(Y))` 里长度在涨 ⇒ 同种子得到的是另一次洗牌。
        #   后果：冠军存的 auc 与候选的 auc **不在同一把尺子上**，
        #   `cand.auc > best.auc` 永远不成立 ⇒ 一晚上一个候选都上不去。
        if val_keys is None:
            val_keys, val_id = frozen_val_keys(
                cache, val_path, max(2000, int(len(Y) * a.val_frac)),
                -1, rebuild=a.val_rebuild)
        vmask = cache.group_mask(val_keys)
        if vmask.any():
            Xva, Yva, Sva = X[vmask], Y[vmask], S[vmask]
            Xtr, Ytr, Str = X[~vmask], Y[~vmask], S[~vmask]
        else:
            # 兜底：冻结键一个都没命中（分片被改名/挪走）⇒ 退回旧口径并**告警**
            print("   ⚠ 冻结验证集一行都没命中（分片被改名/挪走？）⇒ 本轮退回随机切，"
                  "**本轮 AUC 与往轮不可比**", flush=True)
            rng = np.random.default_rng(20261001)
            idx = rng.permutation(len(Y))
            nval = max(1, int(len(Y) * a.val_frac))
            Xva, Yva, Sva = X[idx[:nval]], Y[idx[:nval]], S[idx[:nval]]
            Xtr, Ytr, Str = X[idx[nval:]], Y[idx[nval:]], S[idx[nval:]]
        n_full = len(Ytr)
        # ★ 满 epochs + 子采样控墙钟（**不是**砍 epochs —— 砍了会欠拟合，
        #   实测 129 epochs AUC 0.5340 vs 400 epochs 0.6544）。每轮换 seed ⇒ 长期覆盖全量。
        #   `--src-mix` 决定**各来源的配比**（默认 all = 老行为，不动）。
        Xtr, Ytr, Str = subsample_by_src(Xtr, Ytr, Str, a.max_train,
                                         20261002 + rnd, a.src_mix)
        print(f"\n[轮 {rnd}] 新分片 {new} 个   样本 {len(Y):,} "
              f"（验证 {len(Yva):,} / 训练 {n_full:,}→{len(Ytr):,}）"
              f"   来源 {cache.stats()}", flush=True)
        # 验证集的来源构成 —— 决定"新数据 AUC"能不能单独摘出来看
        print(f"   验证集🔒 {val_id}   来源 "
              + str({cache.names[i]: int((Sva == i).sum())
                     for i in range(len(cache.names))}), flush=True)
        # ★ 训练集的来源构成 —— **这一行是新的，也是关键**：
        #   以前只看"总样本数"，看不见"我的训练集其实 95% 是旧的有噪标签"。
        print("   训练集来源 " + str({cache.names[i]: int((Str == i).sum())
                                     for i in range(len(cache.names))})
              + f"   （--src-mix {a.src_mix}）", flush=True)

        # ★★ 尺子换了 ⇒ 冠军的 auc 必须**重测**（2026-10-02 第六次修）
        #   冠军记录里存着它当年被测时那把尺子的指纹 `val`。尺子一换（或老记录
        #   里压根没有指纹），它那个 auc 与候选的 auc 就**不可比** ——
        #   直接拿来当门槛，等于拿两把尺子的刻度比大小。重测一次，把冠军
        #   放到**当前这把冻结尺子**上，之后一切比较才有意义。
        if best is not None and val_id and best.get("val") != val_id and not run_sfx:
            try:
                m0, _ = VN.load(
                    os.path.join(OUTDIR, best.get("file") or f_mlp), device=dev)
                a0 = round(float(VN.metrics(m0.predict(Xva), Yva)["auc"]), 4)
                print(f"   ⟳ 尺子换了 ⇒ 冠军 auc 重测：{best.get('auc')} → {a0}"
                      f"（同一把尺子：{val_id}）", flush=True)
                best["auc"], best["val"] = a0, val_id
                best = save_champion(champ_p, best, mlp_p)
            except Exception as e:                         # noqa: BLE001
                print(f"   ⚠ 冠军 auc 重测失败（{type(e).__name__}: {e}）"
                      f"⇒ 本轮不做 AUC 比较，只跑门禁", flush=True)
                best["val"] = val_id

        # ★★ 冠军接手（2026-10-02 第四次修，只做一次）
        #   三种情况：
        #     · champion.json 在 ⇒ 已由 `load_champion` 接手（跨重启不丢）
        #     · champion.json 不在、但 value_mlp.json 在（老部署）⇒ 现在**实测它**
        #       并封为冠军。不这么做的话 `best is None` ⇒ 本轮无条件写盘 ⇒
        #       一份好不容易调好的权重会被随手覆盖（12:33 那次就是这样没的）。
        #     · 两个都不在 ⇒ 空场，第一轮正常写盘。
        if not sealed:
            sealed = True
            if best is None and not run_sfx and os.path.exists(mlp_p):
                try:
                    m0, _ = VN.load(mlp_p, device=dev)
                    a0 = round(float(VN.metrics(m0.predict(Xva), Yva)["auc"]), 4)
                    st0 = os.stat(mlp_p)
                    best = {"name": "（现场 value_mlp.json）", "auc": a0,
                            "bad_pairs": 0, "cmp_pairs": 0,
                            "hidden": list(getattr(m0, "hidden", []) or []),
                            "file": os.path.basename(mlp_p), "bytes": st0.st_size,
                            "mtime": time.strftime("%Y-%m-%d %H:%M:%S",
                                                   time.localtime(st0.st_mtime)),
                            "round": -1, "tag": "", "samples": int(len(Y)),
                            "val": val_id}
                    best = save_champion(champ_p, best, mlp_p)
                    print(f"   ⤺ 现场无 champion.json，已把 value_mlp.json 封为冠军"
                          f"（实测 auc={a0}）⇒ 本轮只有更强（且过门禁）的候选才写盘",
                          flush=True)
                except Exception as e:                 # noqa: BLE001
                    print(f"   ⚠ 给现场权重封冠军失败（{type(e).__name__}: {e}）"
                          f"⇒ 本轮可能覆盖它，请留意", flush=True)

        models, rows = {}, []
        # 本轮真会跑的模型（`every=N` 的错轮项先剔掉）—— 用来算进度/N，
        # 也让"实时 status"能报出"第几个/共几个"，一眼看出守护卡在哪。
        runnable = [c for c in BATTERY
                    if not (c.get("every") and (rnd % c["every"]))
                    and (not only or c["name"] in only)]
        if len(runnable) != len(BATTERY):
            print(f"   本轮跑 {len(runnable)}/{len(BATTERY)} 个档位："
                  f"{[c['name'] for c in runnable]}", flush=True)
        for cfg in runnable:
            if cfg.get("every") and (rnd % cfg["every"]):
                continue
            print(f"   → 正在训 {cfg['name']}（epochs={cfg['epochs']} "
                  f"batch={cfg['batch']}）…", flush=True)
            _status(cur=cfg["name"], done=len(rows), total=len(runnable))
            try:
                m, mt, p, dt = train_one(cfg, Xtr, Ytr, Xva, Yva,
                                         F.FEATURE_NAMES, dev)   # 满 epochs，不再收缩
            except Exception as e:                     # noqa: BLE001
                print(f"   ✗ {cfg['name']}: {type(e).__name__} {e}", flush=True)
                continue
            models[cfg["name"]] = m
            # ★ 分来源 AUC（2026-10-02）：训练集是「旧 1011 万（噪声标签）+ 新 sp2
            #   （干净标签）」的混合体，合起来的 AUC 会被旧数据稀释 ⇒ 分开算才看得出
            #   标签修复到底值多少。样本 <200 的来源不报（统计噪声太大）。
            by_src = {}
            for i, nm in enumerate(cache.names):
                mask = (Sva == i)
                if int(mask.sum()) >= 200:
                    by_src[nm] = round(float(VN.metrics(p[mask], Yva[mask])["auc"]), 4)
            rows.append(dict(name=cfg["name"], hidden=cfg["hidden"],
                             epochs=cfg["epochs"], batch=cfg["batch"],
                             auc=round(float(mt["auc"]), 4),
                             acc=round(float(mt["acc"]), 4),
                             auc_by_src=by_src,
                             secs=round(dt, 1)))
            print(f"   {cfg['name']:<16} auc={mt['auc']:.4f} acc={mt['acc']:.4f}"
                  f"  分源 {by_src}  {dt:6.1f}s", flush=True)
            _status(cur=cfg["name"], done=len(rows), total=len(runnable))

        if not models:
            time.sleep(a.idle)
            continue

        # ⚠️ 报告环节**整体**包在 try 里：它只是"观测"，不该有权限搞死训练循环。
        #    2026-10-01 实测踩到：`demo_hanging` 返回的是**嵌套 dict**
        #    （{局面描述: {eval_hand:…, hanging_val:…, P_xxx:…}}），
        #    我按标量 `round(v, 3)` 处理 ⇒ TypeError ⇒ 整个守护进程退出、GPU 又闲着。
        try:
            cons = consistency_check(models)
            hang = demo_hanging(models)
            for r in rows:
                c = cons.get(r["name"], {})
                r["bad_pairs"] = c.get("bad", -1)
                r["cmp_pairs"] = c.get("pairs", -1)
            hang_flat = {}
            # ⚠️ 这里原来用 `tag` 当循环变量 —— 会**覆盖**上面 `--tag` 的后缀变量
            #    （Python 的 for 变量是函数级作用域），等于后半个 main 里
            #    `tag` 变成了局面描述字符串。改名为 `hkey` 钉死这个坑。
            for hkey, rowv in (hang or {}).items():
                hang_flat[hkey] = {k: (round(float(v), 3)
                                       if isinstance(v, (int, float)) else v)
                                   for k, v in rowv.items()}
            report_extra = hang_flat
        except Exception as e:                         # noqa: BLE001
            print(f"   ⚠ 报告环节出错（不影响训练）：{type(e).__name__} {e}", flush=True)
            for r in rows:
                r.setdefault("bad_pairs", -1)
                r.setdefault("cmp_pairs", -1)
            report_extra = {}

        # ---- 选 best：**稳健性达标优先**，再看 AUC ----
        #   理由：AUC 高但矛盾多 = 在噪声里排名，上不了线（800 局那版就是）。
        #   ⚠️ AUC **只能筛垃圾、不能选冠军**（2026-10-02 三条实测见 `arena_gate`）
        #      ⇒ 开了 `--gate-games` 时，还要过对局才准上位。
        #   ★★ 第六次修（2026-10-02）：原来的条件是 `cand.auc > best.auc` ——
        #      那是拿"漂移尺子"上的两个数硬比（见 `frozen_val_keys`），
        #      冠军一旦封盘就**锁死一切候选**。现在改成**只筛不选**：
        #      同一个"没落后"（容差 `VAL_TOL`）就放它去跑门禁，
        #      **升不升级由对局（真棋力）说了算**。
        ok = [r for r in rows if r["bad_pairs"] == 0]
        pool = ok or rows
        cand = max(pool, key=lambda r: r["auc"])
        auc_same_rule = (best is not None and best.get("val") == val_id)
        beats = (best is None
                 or (cand["bad_pairs"] == 0 and best.get("bad_pairs", 0) != 0)
                 or (cand["bad_pairs"] == best.get("bad_pairs", 0)
                     and (not auc_same_rule
                          or cand["auc"] >= float(best.get("auc", 0)) - VAL_TOL)))
        if not beats:
            print(f"   · 本轮最好 {cand['name']} auc={cand['auc']:.4f} 比冠军 "
                  f"{best['name']} auc={best['auc']:.4f} 低过容差 {VAL_TOL}"
                  f" ⇒ 不写盘", flush=True)
        else:
            m = models[cand["name"]]
            # ★★ 对局门禁：候选先跟现冠军对打，赢了才准覆盖正式权重。
            #   只在**正式运行**（无 run_sfx）且开了 `--gate-games` 时生效。
            gate_on = bool(a.gate_games) and best is not None and not run_sfx
            promoted, why, s_cand = True, "未开门禁", None
            if gate_on:
                cand_p = os.path.join(OUTDIR, "value_mlp_cand.json")
                VN.save(m, cand_p, F.FEATURE_NAMES)
                print(f"   ⚖ 候选 {cand['name']} auc={cand['auc']:.4f} 挑战冠军 "
                      f"{best['name']} auc={best['auc']:.4f}", flush=True)
                had_yard = bool(best.get("yard"))
                promoted, why, s_cand = arena_gate(TOOLS_DIR, cand_p, mlp_p, best,
                                                   a.gate_games, a.gate_workers, 5.0)
                print(f"   ⚖ 门禁判决：{'✅ 换冠军' if promoted else '❌ 不换'} —— {why}",
                      flush=True)
                if not had_yard and best.get("yard"):
                    # 冠军的标尺成绩现算出来了 ⇒ 存下来，别每轮重跑一次（一次 3 分钟）
                    save_champion(champ_p, best, mlp_p)
            if promoted:
                best = dict(cand, samples=int(len(Y)), round=rnd, val=val_id)
                if s_cand:
                    best["yard"] = s_cand
                path = VN.save(m, mlp_p, F.FEATURE_NAMES)
                # ★ 权重**身份指纹**写进 status：`name / hidden / 字节数 / mtime`。
                #   2026-10-02 我在这上面栽过 —— 拿着一份"来路不明"的 value_mlp.json
                #   做了半天复现，最后发现它是另一次冒烟运行留下的。
                #   以后"报告 vs 实盘"对不上时，**第一步先核指纹**，不要靠记忆和文件名。
                st = os.stat(path)
                best["file"] = os.path.basename(path)
                best["bytes"] = st.st_size
                best["mtime"] = time.strftime("%Y-%m-%d %H:%M:%S",
                                              time.localtime(st.st_mtime))
                best["tag"] = tag
                print(f"   ★ 新最优 → {cand['name']}  auc={cand['auc']:.4f} "
                      f"矛盾={cand['bad_pairs']}/{cand['cmp_pairs']}   "
                      f"已写 {os.path.basename(path)}（{st.st_size / 1e6:.1f} MB）",
                      flush=True)
                # ★★ 存盘回读自检（**保留**）：
                #   来历：我一度报告 mlp_1024_512 内存 AUC 0.6547，却在 `value_mlp.json`
                #   上测出 0.5350，判定"报告与实盘不一致 ⇒ 上线即错"。
                #   **后来查明是我的误判**：那份 JSON 在 11:33 已被一次 80 秒的冒烟运行
                #   覆盖成了 mlp_2048_1024（`best.secs == 22.7`、采样 n=8），
                #   而 0.5350 那笔来自我另外上传的 129ep 欠拟合权重。
                #   但**这个自检该留**：它是"存盘保真"的唯一在环证据。
                try:
                    m_chk, _ = VN.load(path, device=dev)
                    auc_chk = round(float(VN.metrics(m_chk.predict(Xva), Yva)["auc"]), 4)
                    best["auc_reload"] = auc_chk
                    if abs(auc_chk - cand["auc"]) > 0.005:
                        print(f"   ⚠⚠ [存盘自检] 不一致！内存 {cand['auc']:.4f} "
                              f"→ 回读 {auc_chk:.4f}（差 {auc_chk - cand['auc']:+.4f}）",
                              flush=True)
                    else:
                        print(f"   [存盘自检] ✅ 内存 {cand['auc']:.4f} = 回读 {auc_chk:.4f}",
                              flush=True)
                except Exception as e:                 # noqa: BLE001
                    print(f"   ⚠ [存盘自检] 出错：{type(e).__name__} {e}", flush=True)
                # ★★ 冠军身份**落盘**（2026-10-02 第四次修）：
                #   不改这一条，进程一重启 `best` 就归零 ⇒ 下一轮**不管 AUC 多少都会
                #   覆盖正式权重**。这不是理论 —— 12:33 写的 auc=0.6496 就是这样被
                #   13:33 的 auc=0.6467 覆盖的，而当天 A/B 恰好横跨这两个时刻，
                #   害我一度以为"两份权重棋力差一倍"。详见 `load_champion`。
                save_champion(champ_p, best, path)


        # 线性基准也存一份（只读棋理用）
        if "logi" in models:
            VN.save(models["logi"], os.path.join(OUTDIR, f_logi),
                    F.FEATURE_NAMES)

        board.append(dict(round=rnd, samples=int(len(Y)), new_parts=new,
                          secs=round(time.time() - t_round, 1), rows=rows,
                          hanging=report_extra))
        with open(board_p, "w", encoding="utf-8") as f:
            json.dump(board, f, ensure_ascii=False, indent=1)
        _status(cur=None, done=len(rows), total=len(runnable))

        if a.once or (a.rounds and rnd >= a.rounds):
            break
        time.sleep(a.idle)

    sampler.stop()
    print("\n" + "=" * 78)
    print(f"结束。轮数 {rnd}   最优 {best['name'] if best else '-'}   "
          f"GPU 采样 {sampler.summary()}")
    print("=" * 78)


if __name__ == "__main__":
    main()
