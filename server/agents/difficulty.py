# -*- coding: utf-8 -*-
"""三人象棋 · Bot 难度档位（**5 档**）—— 老师 2026-09-25 定案，2026-10-02 撤除第 6 档

老师原话：
    「网页设置难度4个档，最低档不需要树状预判，属于新手，然后第二档，
      就是博弈树逐层 3 plies，第3档6 plies，第4档9 plies可以吗？」
    「bot挑战难度档位可以在网页里面选择，默认选第二档」
    「可以考虑让bot加更多挑战难度档，提高bot的智商，但不要烧钱，也不要卡死」
    （2026-10-02）「网页里面去掉 15 piles 这第 6 档难度，因为时间太久，
      性价比不高，下棋太慢」

--------------------------------------------------------------------------
【ply 与档位的换算】
    1 ply = 一层 = 某一方走一步。
    三人棋**一轮 = 三方各走一步 = 3 plies**，
    所以「对手各想 N 步」= 3N plies。档位表就按这个换算：

        档1 新手  →  0 ply    ：一步贪心，不建树
        档2 入门  →  3 plies  ：我 1 步 + 两个对手各 1 步
        档3 进阶  →  6 plies  ：两个对手各想 2 步
        档4 大师  →  9 plies  ：两个对手各想 3 步
        档5 宗师  → 12 plies  ：两个对手各想 4 步   ← **本表上限**

    实现上 `depth` 是「迭代加深的**上限层数**」，plies = 3 × depth：
        depth=1 → 3 plies    depth=2 → 6 plies    depth=3 → 9 plies
        depth=4 → 12 plies
    搜索器会在 time_limit 内逐层加深（1→2→3…），**跑不完的层自动不开**。

--------------------------------------------------------------------------
【★ 2026-10-02 撤除第 6 档「传奇 · 15 plies」】
    老师裁决：「去掉 15 plies 这第 6 档难度，因为时间太久，性价比不高，下棋太慢」。

    依据（不是拍脑袋，全部是在环实测）：
      · 档6 名义 15 plies / 120 s 预算，**实到只有 12 plies**（= 与档5 完全同果）——
        「名不副实」在诚实标注下已经是负资产。
      · 12 → 15 的节点放大实测 **8~27 倍**（15 plies 约需 **10 分钟**）；
        而 16 局面标定（`tests/_analyze_gold.py`）显示 **9→12 已是 noise 级**
        （ratio 1.00、真变招里 5/14 是噪声、耗时 ×24）⇒ 15 plies 纯属烧时间。
      · 交互场景下"陪练想 10 分钟"直接把对弈节奏打死。

    ⚠️ **撤的是"档位"，不是"深搜能力"**：`depth=4`（12 plies）仍是搜索器支持的上限，
    将来机器更快 / 或离线批量跑棋谱时，把本表加一档回来即可（`MAX_LEVEL` 自动跟随 `len(LEVELS)`）。
    下面 `_selftest()` ⑥ 专门加了「上限 plies == 12」的守卫，
    防止这一档在没重新做标定的情况下被无意识加回。

--------------------------------------------------------------------------
【为什么档4 的 time_limit 给到 45 秒】
    实测本机吞吐 ≈ 3~4 万节点/秒（纯 Python；见 docs/专利版_预判改进方案.md）：
        9 plies：中局 24 手 18.6 s ｜ 开局 40.6 s（迭代加深是 3→6→9 **累加**）
    若给窄了（例如 8 s），迭代加深的「时间外推」会判定这层开不出来 ⇒
    **静默停在 6 plies**，那样「档4 = 9 plies」就名不副实。
    ⇒ 宁可长考，也不虚标深度。嫌慢就把本表档4 的 time_limit 调小，
      代价是开局会退回 6 plies（中局仍能吃到 9 plies）。

--------------------------------------------------------------------------
【换档只换「几方 Bot 的脑子」】
    不动棋盘 / 轮次 / 战绩 / 悔棋次数 / 规则约定；
    人类接管的那几方本来就不走 Bot ⇒ 天然不受影响。
"""
import json
import os

# ------------------------------------------------------------------ 方案 ②
# 静态搜索（quiescence）层数 —— 所有"搜索档"统一开启。
#   plies 用尽后继续只搜**吃子**，直到盘面安静或吃满 N 层，
#   消除"固定深度边界上刚吃了个大子被高估"的水平线效应。
#   0 = 关闭（退回纯固定深度）。
#   为什么取 2：见 `search_bot.QS_DEFAULT` 上方的实测说明 ——
#   节点数 qs=0/2/4 → 1.0× / 4.6× / 19.9×，而估值改变面局数 17/20 → 17/20（几乎不涨），
#   深档还要抢深度，故取性价比拐点 2。
#   ⚠️ 与 `search_bot.QS_DEFAULT` 保持一致（此处复制而非法 import，
#      避免 difficulty → search_bot 的依赖把档位模块拖上 numpy/numba）。
QS_DEFAULT = 2

# ------------------------------------------------------------------ 档位表
#   改档位只改这里 —— 网页按钮、后端 API、默认档全部由本表驱动。
LEVELS = [
    {
        "level": 1, "name": "新手", "plies": 0, "brief": "不预判",
        "model_id": "__local__",
        # ⚠️ 2026-10-01 订正：旧文案写「只算当前这手能吃什么」——**与实现不符**。
        #   `LocalBot._score()` 实为 6 项加权求和（吃子只是权重最大的一项）：
        #     ① 吃子 +VALUE[被吃子]（吃别家 +1，吃帅 +900）
        #     ② 反吃风险 −VALUE[自己的子]×0.6（**仅当本步是吃子时才计算**）
        #     ③ 将军 +8.0（每将到一方帅各 +8）  ④ 帅受威胁 −6.0
        #     ⑤ 出子展开：车/炮/马向前 +0.8、兵向前 +0.35 / 横走 −0.15 / 过界 +0.2
        #     ⑥ 同分随机抖动 +random()×0.05
        #   另有：残局(≤22 子)朝敌帅 BFS 每近一步 +0.35；上一步的反向走法 −0.7。
        "desc": "一步贪心：只看走完这一步的**即时得失**，不建博弈树、不预判对手回应。"
                "评分 = 吃子(车9/炮4.5/马4/象2/士2/兵1，吃帅另 +900) + 将军 +8"
                " − 被反吃(仅吃子时评估) − 帅受威胁 6 + 出子展开 0.8，同分随机选。"
                "适合刚开始熟悉规则。",
    },
    {
        "level": 2, "name": "入门", "plies": 3, "brief": "3 plies",
        "model_id": "__search__", "depth": 1, "time_limit": 3.0,
        "desc": "博弈树逐层预判 3 plies（我 1 步 + 两个对手各 1 步）。"
                "实测 0.01 秒/步（numba 内核），适合日常对弈。",
    },
    {
        "level": 3, "name": "进阶", "plies": 6, "brief": "6 plies",
        "model_id": "__search__", "depth": 2, "time_limit": 8.0,
        "desc": "预判 6 plies（两个对手各想 2 步）。"
                "实测开局 0.29 秒/步、中局 0.19 秒/步，棋力与流畅度平衡。",
    },
    {
        "level": 4, "name": "大师", "plies": 9, "brief": "9 plies",
        "model_id": "__search__", "depth": 3, "time_limit": 45.0,
        "desc": "预判 9 plies（两个对手各想 3 步）。"
                "实测开局 2.6 秒/步、中局 0.6 秒/步 —— numba 内核接入后"
                "比加速前快约 10 倍，**不必再等几十秒**，适合当主力陪练。",
    },
    # ---- 档5：老师 2026-09-25「可以考虑让bot加更多挑战难度档」 ----
    #   ✅ 2026-09-26 numba 内核（方案 ①）接入后重测（`tests/_bench_jit_levels.py`）：
    #      档5（12 plies）**能真正跑满**：开局 42.3 s、中局 41.1 s（预算 60 s）。
    #   ✅ 不烧钱：本地搜索，0 token。
    #   ✅ 不卡死：time_limit 是**硬上限**，迭代加深每层前做时间外推，
    #      开不完的层直接不开，到点必返回。
    #   ★ 2026-10-02：档6「传奇 · 15 plies」**已撤除**（老师：「去掉 15 piles
    #      这第 6 档难度，因为时间太久，性价比不高，下棋太慢」）。
    #      撤除依据（三条都在环实测，见模块 docstring）：
    #        ① 名义 15 plies，**实到只有 12 plies** ⇒ 与档5 同果，属"名不副实"；
    #        ② 12→15 节点放大 8~27 倍（约 10 分钟），而 9→12 已是 noise 级；
    #        ③ 陪练想 10 分钟 ⇒ 对弈节奏被打死。
    #      ⇒ 12 plies（depth=4）成为**本表上限**。加回来只需在本表补一条 +
    #        同步改 `_selftest()` ⑥ 的上限守卫（`MAX_LEVEL` 自动跟随）。
    {
        "level": 5, "name": "宗师", "plies": 12, "brief": "12 plies · 长考",
        "model_id": "__search__", "depth": 4, "time_limit": 60.0,
        "desc": "预判 12 plies（两个对手各想 4 步）。"
                "实测开局 42 秒/步、中局 41 秒/步 —— **真能搜满 12 plies**"
                "（numba 内核接入前做不到，故旧描述「只能搜到 9 plies」已作废）。"
                "硬性 60 秒上限，到点必返回。**本表最高档**。",
    },
]

#   老师 2026-09-25 指定：网页默认第二档
DEFAULT_LEVEL = 2
MAX_LEVEL = len(LEVELS)

#   只有这两个 id 属于「本地 Bot」——**难度档只接管它们**。
#   填了真实大模型的那一方（model_id 是具体模型名）不受难度档影响，
#   否则「换个难度」会把老师配好的 LLM 对手悄悄换成本地 Bot。
LOCAL_IDS = ("__search__", "__local__")

_BY_LEVEL = {lv["level"]: lv for lv in LEVELS}


def is_local(cfg):
    """这一方是不是「本地 Bot」（= 可以被难度档接管的）"""
    return (cfg.get("model_id") or "") in LOCAL_IDS


# ------------------------------------------------------------------ 查询
def get(level):
    """取档位定义（非法值 → 默认档）"""
    return _BY_LEVEL.get(norm(level), _BY_LEVEL[DEFAULT_LEVEL])


def norm(v):
    """把任意输入（str/int/None/越界）归一化成 1..MAX_LEVEL 的 int"""
    try:
        n = int(v)
    except (TypeError, ValueError):
        return DEFAULT_LEVEL
    return min(max(n, 1), MAX_LEVEL)


def all_levels():
    """给前端画按钮用的清单（只含需要暴露的字段）"""
    return [{"level": lv["level"], "name": lv["name"], "plies": lv["plies"],
             "brief": lv["brief"], "desc": lv["desc"]} for lv in LEVELS]


def describe(level):
    """当前档的精简描述（进 /api/state，前端据此高亮按钮）"""
    lv = get(level)
    return {"level": lv["level"], "name": lv["name"], "plies": lv["plies"],
            "brief": lv["brief"], "desc": lv["desc"],
            "depth": lv.get("depth"), "time_limit": lv.get("time_limit")}


# ------------------------------------------------------------------ 应用
def apply(cfg, level):
    """把档位套到某一方的 player 配置上 → **新的** cfg（不改原对象）

    档1 会把 depth/time_limit 一并删掉（贪心 Bot 不看这两个键，
    留着会让 agents.json 出现「明明写着 depth 却在贪心」的误导）。
    """
    lv = get(level)
    out = dict(cfg)
    out["model_id"] = lv["model_id"]
    if lv["model_id"] == "__search__":
        out["depth"] = lv["depth"]
        out["time_limit"] = lv["time_limit"]
        # 方案 ②：静态搜索（各搜索档统一开启，见顶部 QS_DEFAULT）
        out["qs_depth"] = lv.get("qs_depth", QS_DEFAULT)
    else:
        out.pop("depth", None)
        out.pop("time_limit", None)
        out.pop("qs_depth", None)
    army = cfg.get("army") or ""
    tag = f"{lv['name']}（{lv['brief']}）"
    out["label"] = f"{army}方·{tag}" if army else tag
    return out


def default_options():
    """给 agents.json 的 options 段用：默认档（老师指定第二档）"""
    return {"difficulty": DEFAULT_LEVEL}


# ------------------------------------------------------------------ 自检
def _selftest():
    ok = 0
    bad = []
    # ① 各档 plies 必须是 3 的倍数（档1 为 0）
    want = [0, 3, 6, 9, 12]
    got = [lv["plies"] for lv in LEVELS]
    if got == want:
        ok += 1
    else:
        bad.append(f"plies 表 {got} != {want}")
    # ② plies = 3 × depth（档1 无 depth）
    for lv in LEVELS:
        if lv["plies"] == 0:
            if lv["model_id"] != "__local__":
                bad.append(f"档{lv['level']} 应走贪心")
            else:
                ok += 1
        else:
            if lv["plies"] != 3 * lv["depth"]:
                bad.append(f"档{lv['level']} plies≠3×depth")
            elif lv["model_id"] != "__search__":
                bad.append(f"档{lv['level']} 应走搜索")
            else:
                ok += 1
    # ③ 默认档 = 2，且归一化健壮
    if DEFAULT_LEVEL == 2 and norm(None) == 2 and norm("x") == 2 and \
            norm(0) == 1 and norm(9) == MAX_LEVEL:
        ok += 1
    else:
        bad.append(f"默认档/归一化异常 DEFAULT={DEFAULT_LEVEL}")
    # ④ apply 不改原对象、标签正确
    src = {"army": "魏", "model_id": "__local__", "url": "http://x"}
    a2 = apply(src, 2)
    a1 = apply(src, 1)
    if src.get("model_id") == "__local__" and a2["model_id"] == "__search__" \
            and a2["depth"] == 1 and a2["time_limit"] == 3.0 \
            and a1["model_id"] == "__local__" and "depth" not in a1 \
            and a2["label"] == "魏方·入门（3 plies）" and a2["url"] == "http://x":
        ok += 1
    else:
        bad.append(f"apply 结果异常 a1={a1} a2={a2}")
    # ⑤ 档4 预算必须 >= 30s（否则 9 plies 开不出来，名不副实）
    if get(4)["time_limit"] >= 30.0:
        ok += 1
    else:
        bad.append(f"档4 预算 {get(4)['time_limit']}s 太小，9 plies 会退回 6 plies")
    # ⑥ ★ 上限守卫（2026-10-02）：档位表最高 plies 必须是 12。
    #    第 6 档「传奇 · 15 plies」已撤除（实到只有 12 plies ⇒ 与档5 同果，
    #    且 12→15 节点放大 8~27 倍 / 约 10 分钟 ⇒ 交互场景下纯属烧时间）。
    #    这条断言的作用是**拦住"顺手又加回来"**：想加回 15 plies，
    #    先要重新做 16 局面标定（`tests/_analyze_gold.py`）并改这里，
    #    不允许它悄悄回到档位表里。
    _maxp = max(lv["plies"] for lv in LEVELS)
    if _maxp == 12 and MAX_LEVEL == 5:
        ok += 1
    else:
        bad.append(f"档位上限 {_maxp} plies / MAX_LEVEL={MAX_LEVEL}"
                   f" —— 期望 12 plies / 5 档（15 plies 档已于 2026-10-02 撤除）")
    # ⑦ 档位号必须连续 1..MAX_LEVEL（前端按钮按下标高亮，跳号会错位）
    if [lv["level"] for lv in LEVELS] == list(range(1, MAX_LEVEL + 1)):
        ok += 1
    else:
        bad.append(f"level 号不连续：{[lv['level'] for lv in LEVELS]}")
    print(f"difficulty.py 自检：{ok} 通过 / {len(bad)} 失败")
    for b in bad:
        print("   ✗", b)
    return not bad


if __name__ == "__main__":
    import sys
    sys.exit(0 if _selftest() else 1)
