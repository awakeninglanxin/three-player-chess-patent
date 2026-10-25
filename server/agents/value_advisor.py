# -*- coding: utf-8 -*-
"""价值网络 → 搜索（方案 c：推荐 + 对弈都接，留开关）

【它解决什么】
旧的 `eval_dxf` 十项权重里**没有一项**管"我的子正被白吃"：
  `material = 0.10` ⇒ 一个马只值 **0.40 分**（`close1 400` 是它 1000 倍），
  且 `material = 我 − 最强对手` ⇒ **吃弱者的子贡献 0**。
⇒ 实测开局"车往前走一步、白送一匹马"，搜索分数还从 +36.96 **涨到** +37.87。
换 AlphaZero 也治不好这个 —— value head 只是「特征 → 胜率」的映射，
**特征里没有"我的子正被白吃"，网络就学不出来**。
所以先补了 `features_dxf`（32 维，含 12 维子力安危），再训网络；本模块负责**接上**。

【接在哪一层：根节点重排，不是叶节点】
叶节点融合（把网络塞进 `_leaf`）理论上更彻底，但：
  · JIT 路径（默认）的叶评估在 `nb_core.leaf`（numba 里），塞 torch 不现实；
  · 根节点重排对 **Python / JIT 两条路径完全一致**，一处生效；
  · 成本可控：根着法 ~40 条 × (深拷贝 + 走子 + 提特征 + 前向) ≈ 数十毫秒，
    而单步预算是 12~150 秒（`HINT_BUDGET`）。
⇒ 取「根节点重排」，并且**用第一层（plies=3）的全量榜单**做候选
（`ROOT_KEEP[3]=99` ⇒ 覆盖**所有**合法着法，不会因渐进加宽把正确手筛掉）。

【为什么要「第一层全量榜单」而不是最终候选】
渐进加宽到 plies=12 时 `ROOT_KEEP[12]=5`，只剩 5 个候选。
"送马"那手正在其中（它搜索分高），而"把马救回来"那手早就被砍掉了。
⇒ 拿最终 5 个候选重排，网络**没有机会**把救马的手排上来。

【归一化口径：z-score + SD_FLOOR】
搜索分（量级 ±40）与网络概率（0~1）不同量纲，必须各自标准化后再线性混合。
⚠️ 概率的 std 在候选集里常常极小（对手棋来说"都很接近"），直接除以会
**把噪声放大几十倍**（训练时踩过：mlp 的 ΔP 被放大到 0.208）⇒ 加 `SD_FLOOR` 兜底。

【开关】
`SearchBot(use_value=True/False/None)`：
  None = 跟随配置（`agents.json` 的 `value_net.enabled`）；True/False = 强制。
任何异常都**静默退回纯搜索**，绝不让网络问题阻断对局。
"""
import copy
import json
import os
import sys

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
_SRV = os.path.dirname(_HERE)
for _p in (_SRV, os.path.join(_SRV, "engine"), _HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

VALUES_DIR = os.path.join(_HERE, "values")
CONF_FILE = os.path.join(_HERE, "agents.json")

#: 候选集里概率的 std 下限 —— 低于它就按这个算，防止"几乎一样"被放大成排名
SD_FLOOR = 0.10
#: 搜索分标准化时的 std 下限（同理）
SCORE_SD_FLOOR = 1e-3
#: 默认混合系数：最终分 = (1-λ)·搜索分z + λ·网络概率z
DEFAULT_LAMBDA = 0.35
#: 默认用哪个网络（mlp 容量大、AUC 高；logi 只是线性基准）
DEFAULT_KIND = "mlp"

_KIND_FILE = {"logi": "value_logi.json", "mlp": "value_mlp.json"}


def load_conf():
    """读 `agents.json` 里的 `value_net` 段；读不到就给默认（**默认关闭**）。

    默认关闭是有意的：没训过网络时不该悄悄改变 Bot 行为。
    """
    default = {"enabled": False, "kind": DEFAULT_KIND,
               "lambda": DEFAULT_LAMBDA, "file": ""}
    try:
        with open(CONF_FILE, encoding="utf-8") as f:
            conf = (json.load(f) or {}).get("value_net") or {}
        out = dict(default)
        for k in ("enabled", "kind", "lambda", "file"):
            if k in conf:
                out[k] = conf[k]
        return out
    except Exception:                              # noqa: BLE001
        return default


def weights_path(kind="mlp", file=""):
    if file:
        return file if os.path.isabs(file) else os.path.join(VALUES_DIR, file)
    return os.path.join(VALUES_DIR, _KIND_FILE.get(kind, "value_mlp.json"))


class ValueAdvisor:
    """价值网络顾问：给根着法重排。

        adv = ValueAdvisor.load()          # 读配置，可能 enabled=False
        adv = ValueAdvisor.load(enabled=True, kind="mlp")
        ranked2 = adv.rerank(state, me, ranked)
    """

    def __init__(self, model=None, names=None, kind="", lam=DEFAULT_LAMBDA,
                 enabled=False, path=""):
        self.model = model
        self.names = names or []
        self.kind = kind
        self.lam = float(lam)
        self.enabled = bool(enabled) and model is not None
        self.path = path
        self.stats = {"calls": 0, "evals": 0, "fails": 0, "changed": 0}

    # ---------------------------------------------------------------- 构造
    @classmethod
    def load(cls, kind=None, lam=None, enabled=None, path="", device="cpu"):
        conf = load_conf()
        kind = kind or conf["kind"]
        lam = conf["lambda"] if lam is None else lam
        if enabled is None:
            enabled = bool(conf["enabled"])
        p = weights_path(kind, path or conf.get("file", ""))
        # ★★【2026-10-02 修】**没开就绝不 import torch**（性能根因，别再退回去）。
        #
        #   旧写法只在「权重文件不存在」时短路 ⇒ 文件一旦存在（现在**永远**存在），
        #   即使 `enabled=False` 也会走到下面 `from agents import value_net`
        #   ⇒ 拖进 `import torch`，本机实测 **≈2.4 s**（cProfile：时间几乎全在
        #   `torch/nn/__init__.py` 与 `torch/_jit_internal._overload`）。
        #
        #   后果有两条，都是实测的：
        #     ① **每次进程启动后的第一次搜索白等 2.4 s** —— 即使那一方是关的
        #        （魏/蜀两席就是关的，照样付这笔钱）。老师重启对弈台后第一手棋/第一次点
        #        推荐会莫名慢一拍，且极难归因。
        #     ② `tests/_verify_difficulty.py` §⑫ 的「1.0 s 预算 ⇒ 实测不超 2.5 s」
        #        被顶穿（实测 **2.60 s**），长期红着 —— 它会一直红，因为把
        #        "一次性 import 开销"算进了"超时截断"这名下。
        #
        #   取证探针：`tests/_probe_timeout_grain.py`（首发 2.43 s / 之后 0.01 s，
        #   且 `search_root.nopython_signatures` 数量**前后不变** ⇒ 排除 JIT 编译）。
        #   守门测试：`tests/_probe_value_lazy.py`（断言 disabled 时 `torch not in sys.modules`）。
        #
        #   ⚠️ `enabled` 只有为真时才需要模型 ⇒ 先判 enabled、再判文件存在，最后才 import。
        if not enabled:
            return cls(None, [], kind, lam, False, p)
        if not os.path.exists(p):
            return cls(None, [], kind, lam, False, p)
        try:
            from agents import value_net as VN
            model, names = VN.load(p, device=device)
        except Exception:                          # noqa: BLE001
            return cls(None, [], kind, lam, False, p)
        return cls(model, names, kind, lam, enabled, p)

    # ---------------------------------------------------------------- 打分
    def prob(self, s, me):
        """局面 s 在 me 视角下的胜率（0~1）。异常返回 None。"""
        if self.model is None:
            return None
        try:
            from agents import features_dxf as F
            x = np.asarray(F.extract(s, me), dtype=np.float32).reshape(1, -1)
            p = self.model.predict(x)
            self.stats["evals"] += 1
            return float(np.asarray(p).reshape(-1)[0])
        except Exception:                          # noqa: BLE001
            self.stats["fails"] += 1
            return None

    def prob_after(self, state, me, frm, to):
        """走完 (frm,to) 之后、仍从 me 视角看的胜率。

        ⚠️ `GA.apply` **原地改 s 并自动 `_advance()`**（走子方取自 `s["turn"]`）
        ⇒ 必须先深拷贝；且**不能**依赖 `s["turn"]`，走子方是显式传进来的 `me`。
        """
        try:
            from engine import game_dxf as GA
            # 引擎自带 `clone`（就是 deepcopy，但集中在一处，方便以后换更快的实现）
            snap = GA.clone(state)
            GA.apply(snap, frm, to)
            # 终局直接给确定标签，不必过网络
            if snap.get("winner") is not None:
                return 1.0 if snap["winner"] == me else 0.0
            if me not in (snap.get("vitality") or {}):
                return 0.0
            return self.prob(snap, me)
        except Exception:                          # noqa: BLE001
            self.stats["fails"] += 1
            return None

    # ---------------------------------------------------------------- 重排
    def rerank(self, state, me, ranked, k=0):
        """把 `[(move, search_score)]`（降序）用网络胜率重排。

        `k > 0` 时只在**前 k 名**里重排（省算力）；`k=0` 表示全量。
        任何一步取不到概率 ⇒ **整次重排放弃**，原样返回（宁可不改，不可改错）。
        """
        if not self.enabled or not ranked:
            return ranked
        self.stats["calls"] += 1
        cand = ranked if not k else ranked[:k]
        ps, ok = [], True
        for mv, _sc in cand:
            try:
                frm, to = str(mv).split("-")
            except Exception:                      # noqa: BLE001
                ok = False
                break
            p = self.prob_after(state, me, frm, to)
            if p is None:
                ok = False
                break
            ps.append(p)
        if not ok:
            return ranked

        sc = np.asarray([float(s) for _m, s in cand], dtype=np.float64)
        pr = np.asarray(ps, dtype=np.float64)
        sc_z = (sc - sc.mean()) / max(sc.std(), SCORE_SD_FLOOR)
        pr_z = (pr - pr.mean()) / max(pr.std(), SD_FLOOR)
        final = (1.0 - self.lam) * sc_z + self.lam * pr_z

        order = np.argsort(-final, kind="stable")
        out = [(cand[i][0], float(final[i])) for i in order]
        # 保留没参与重排的尾巴（k>0 时），按原顺序附在后面
        if k and len(ranked) > k:
            out = out + list(ranked[k:])
        if out and out[0][0] != ranked[0][0]:
            self.stats["changed"] += 1
        return out

    def describe(self):
        return (f"价值网络[{self.kind}] enabled={self.enabled} λ={self.lam:g} "
                f"{os.path.basename(self.path)} "
                f"调用{self.stats['calls']}/评估{self.stats['evals']}/失败{self.stats['fails']}")


def enabled_by_default():
    return bool(load_conf()["enabled"])


if __name__ == "__main__":
    # 自检：加载 + 对开局局面跑一次全量重排
    adv = ValueAdvisor.load(enabled=True)
    print("加载：", adv.describe())
    if adv.model is None:
        sys.exit("✗ 没有可用权重")
    from engine import game_dxf as GA
    s = GA.new_game(first=1)
    me = s["turn"]
    legal = GA.legal_moves(s, me)
    ranked = [(f"{f}-{t}", 0.0) for f, t in legal]
    out = adv.rerank(s, me, ranked)
    print(f"候选 {len(ranked)} 手，重排后前 6：")
    for mv, sc in out[:6]:
        frm, to = mv.split("-")
        print(f"  {mv}  混合分 {sc:+.3f}  胜率 {adv.prob_after(s, me, frm, to):.3f}")
    print(adv.describe())
