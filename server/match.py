# -*- coding: utf-8 -*-
"""对局调度器：后台线程跑三方 LLM 对弈，对外提供状态快照

统一 agent 接口：agent.choose(state, legal, text, army_name) -> dict
"""
import copy
import json
import os
import threading
import time
import zlib

try:
    from .engine import game_dxf as GA
    from .engine import rules_dxf as R
    from .engine import patent as P
    from .agents.llm import LLMAgent, load_roster, describe
    from .agents.bots import LocalBot, VALUE
    from .agents.search_bot import SearchBot
    from .agents import arena
    from .agents import difficulty as DIFF
    from .agents import seats as SEATS
except ImportError:
    from engine import game_dxf as GA
    from engine import rules_dxf as R
    from engine import patent as P
    from agents.llm import LLMAgent, load_roster, describe
    from agents.bots import LocalBot, VALUE
    from agents.search_bot import SearchBot
    from agents import arena
    from agents import difficulty as DIFF
    from agents import seats as SEATS

HERE = os.path.dirname(os.path.abspath(__file__))

# 棋子 kind → **简体**中文，给**文字叙述**用（战报、推荐说明）。
#   ⚠️ 与 `GA.KIND_CN`（繁体「車馬帥炮」，棋盘上画的那个）刻意不同 ——
#      老师读规则文档用简体，棋盘用繁体；两套并存是有意的，别"顺手统一"。
_KIND_CN = {"general": "帅", "advisor": "士", "elephant": "象",
            "horse": "马", "rook": "车", "cannon": "炮", "pawn": "兵"}

# 「一键推荐下一步」的搜索预算（秒）与默认档位。
#
# ★ 2026-10-01 实测定了口径（`tests/_bench_ply_saturation.py`，2 个真实中局逐层对照
#   3→15 plies，原始数据 `tests/_bench_ply_sat.json`）：
#     · 12 plies ≈ 30~36s / 3200 万节点；15 plies ≈ 639~731s / 5.3~5.9 亿节点
#       ⇒ **×20 的时间与节点**（旧注释推测的"8~27 倍"实测落在 21 倍附近）。
#     · 而 12→15 的"变招"在棋力上是**噪声级**：两个局面里 12 plies 选的那手
#       与 15 plies 榜首只差 **+0.04 / +0.06 分**（该层估值量级 4031）≈ 0.001%；
#       局面#1 甚至 12 与 15 选同一手却只排第 2（榜首差 0.04）。
#     ⇒ 瓶颈不是"深度不够"，是**估值函数分不开这几手**；再加深只是把噪声重洗一遍。
#     ⇒ 结论：默认 **12 plies**（老师等得起），15 plies 降级为**可选深搜**。
#
# ⚠️ 预算不能按"档位表的 time_limit"抄：最高档（宗师 12 plies）也只有 60s
#    （那是给自动对弈的节奏定的；原档6「传奇 15 plies」已于 2026-10-02 撤除），
#    而推荐是老师主动点的一次性离线查询，不受对局节奏约束。
#    ⚠️ 也别按裸搜耗时给：对弈台在跑时推荐与 Bot 抢 JIT 搜索锁，实测 12 plies 从
#    30s 涨到 62s ⇒ 留 5 倍余量。
# ★★【2026-10-02 老师定】默认档从 12 → **9 plies**。
#   老师原话：「网页 AI 推荐用 9 plies，12 用的时间太长了」。
#
#   两批独立实测在本档位上是**互相矛盾**的，一并留档，谁也别当没发生：
#     · 批一（`tests/_bench_ply_saturation.py` → `_bench_ply_sat.json`，**2 个局面**）：
#       9 选的手在 12 的榜单里只排第 5、第 6（差 +0.88 / +6.03）；9 自己的前 4 名
#       只差 0.24 分 ⇒ 判为"在噪声里挑一手、分辨率不够"。
#     · 批二（`tests/_analyze_gold.py`，**16 个局面**，2026-10-01）：
#       6→9 的中位 ratio **3.54**（12 个局面真变招）⇒ 这一段值钱；
#       **9→12 的 ratio 只有 1.00、噪声占比 45%、耗时 ×24**（≈43s / 3345 万节点）
#       ⇒ 判为"9 已是智力饱和点，再加深只是烧时间"。
#   ⇒ 批次二样本量大一个数量级，且老师的**体感**（12 太慢）与它一致 ⇒ 默认取 **9**；
#      12 / 15 保留为下拉框里的"慢档"，谁想拼再自己选。
#      ⚠️ 以后再有"该用几层"的争论，先看 `_analyze_gold.py` 的 16 局面口径，
#         别拿 2 个局面的批次一声量更大的结论拍板。
HINT_BUDGET = {9: 12.0, 12: 150.0, 15: 720.0}
HINT_PLIES_DEFAULT = 9


def _hint_seed(snap):
    """推荐的随机种子 —— **由局面决定**，不是 `time.time()`

    ★ 为什么必须跟时间脱钩（老师 2026-10-01 报「同预算连要两次给出两手」）：
      原先写的是 `int(time.time() * 1000) % 99991` ⇒ 同一局面点两次「推荐下一步」
      会拿到**两个不同的建议**。对自动对弈这样写没错（避免每局一模一样），
      但推荐是"给人看的意见"：一手要等 30 秒，老师点两次看到两个答案只会觉得
      功能不可信（而且 `tests/_verify_hint.py` §4 的"可复现"断言也守不住）。

      现口径 = `crc32(ply + 回合方 + 棋盘快照)`：
        · 同一局面 ⇒ 永远同一手（点多少次都一样）；
        · 局面一变 ⇒ 种子变，搜索里的噪声也跟着换，不会"每局都按同一套偏好走"。
      ⚠️ 用 `zlib.crc32` 而不是内置 `hash()`：后者对 str 带随机盐（PYTHONHASHSEED），
        跨进程不稳定 ⇒ "重启服务后又给出另一手"。
    """
    board = snap.get("board") or {}
    sig = "|".join(f"{k}:{v.get('army')}{v.get('kind')}"
                   for k, v in sorted(board.items()))
    raw = f"{snap.get('ply')}-{snap.get('turn')}-{sig}"
    return zlib.crc32(raw.encode("utf-8")) % 99991

# ---------------------------------------------------------------- 续局存档
# 【老师 2026-10-01】「如何设计能否重启网页后继续之前的棋局继续下？」
#   答案 = 每手落盘 + 启动恢复。三个设计要点（少一个都会出事）：
#   ① **默认不开**：只有 app.py 显式 `enable_autosave()` 才写盘。
#      否则 tests/ 里成百上千个 `Match()` 实例会把老师的真实存档冲掉。
#   ② **原子写**：先写 `autosave.tmp` 再 `os.replace` —— 中途断电/崩溃
#      也不会留下半截 JSON（宁可没有存档，也不能读出个错盘面）。
#   ③ **版本校验**：改了规则/结构就 bump 版本号 ⇒ 旧存档**弃用并另存备份**，
#      不尝试兼容 —— 三人象棋的 state 字段全是引擎内部约定，硬兼容比开新局危险。
#   ⚠️ 不存的：模型延迟/临时错误（纯页面观感）；"思考中"（恢复后在轮到的
#      那一方重新出招即可，不需要把长考状态也存下来）。
SAVE_VERSION = 3
SAVE_FILE = os.path.join(HERE, "data", "autosave.json")
SNAP_KEEP = 60          # 悔棋存档只留最近 60 条（连悔 3 次最多用 9 条，绰绰有余）
LOG_KEEP = 400          # 战报只留最近 400 条（前端本来也只显示最近 80 条）


def build_agent(cfg):
    """按 model_id 造 agent

    三种取值：
        "__search__" → SearchBot（minimax 搜索，棋力最强，2 层预判）
        "__local__"  → LocalBot（一步贪心，纯兜底，最省）
        其他          → LLMAgent（真实大模型）
    """
    mid = cfg.get("model_id")
    if mid == "__search__":
        return SearchBot(depth=cfg.get("depth", 2),
                         time_limit=cfg.get("time_limit", 1.5),
                         seed=cfg.get("seed"),
                         # 静态搜索层数（方案 ②）：None → SearchBot 默认 QS_DEFAULT(6)；
                         # cfg 里显式给 0 可关掉（退回"纯固定深度"）。
                         qs_depth=cfg.get("qs_depth"),
                         # ---- ★ 价值网络**按座位**开关（2026-10-02）----
                         #   为什么必须做成"按席"而不是只有全局一个开关：
                         #   实测（`tools/ab_match.py`，各 300 局，tl=5.0）
                         #     {纯搜索, 纯搜索, 价值Bot} ⇒ 价值Bot 26.7% vs 20.0%/19.7%
                         #                               （合并序数检验 p≈0.03）
                         #     {纯搜索, 价值Bot, 价值Bot} ⇒ 判和率 31%→54%，三方全平
                         #   也就是说：**价值网络在同场只有一台时明显更强，
                         #   同场两台会把对局拖成和棋、优势互相抵消。**
                         #   ⇒ 全局一个开关无论怎么设都不是最优；必须能一席一席配。
                         #   `None` = 跟随 `agents.json` 的 `value_net.enabled`（旧行为）。
                         use_value=cfg.get("use_value"),
                         value_lambda=cfg.get("value_lambda"),
                         value_kind=cfg.get("value_kind"),
                         value_file=cfg.get("value_file"),
                         value_topk=cfg.get("value_topk", 0),
                         label=cfg.get("label", "搜索Bot（minimax·2层）"))
    if mid == "__local__":
        return LocalBot(cfg.get("local_mode", "greedy"))
    return LLMAgent(cfg)


def material(state):
    """各方在场子力价值（不含帅）"""
    out = {1: 0.0, 2: 0.0, 3: 0.0}
    for p in state["board"].values():
        if p["kind"] == R.GENERAL:
            continue
        out[p["army"]] = out.get(p["army"], 0.0) + VALUE.get(p["kind"], 1.0)
    return {str(k): round(v, 1) for k, v in out.items()}


def _score_txt(v):
    """把搜索分数印成人话。±900000 以上是「已被将死/必胜」的哨兵值，
    直接写 -1000000.0 只会让人以为程序坏了（老师截图里就撞见过）。"""
    try:
        v = float(v)
    except (TypeError, ValueError):
        return f"估值 {v}"
    if v >= 900000:
        return "估值 必胜（对方无解）"
    if v <= -900000:
        return "估值 必败（己方被将死）"
    return f"估值 {v:+.1f}"


# 综合实力评分权重：斩帅 >> 在场子力 > 吃子收益 > 存活 > 非法输出扣分
# 三人象棋天然容易打满手数判和（棋盘开阔、三家互相牵制），
# 所以在和棋时用这套评分回答「到底哪个 AI 下得更好」。
W_SLAIN, W_MAT, W_KILL, W_ALIVE, W_WRONG = 1000.0, 8.0, 3.0, 300.0, 20.0

# 「回退」和「悔棋」是两件事，别混：
#   回退（fallback）＝ 模型输出了**非法**着法 → 由兜底 Bot 代走一步。这是**缺陷**，
#                      记在 wrong[] 里，衡量的是"模型会不会遵守规则"。
#   悔棋（undo）   ＝ 模型走出了**合法但很臭**的棋 → 消耗一次机会重走。这是**机制**，
#                      只在网页勾选后启用，每方 3 次，衡量的是"给机会能不能下得更好"。
LABEL_BAD = ("mistake", "blunder")

# 副帅被斩的记账价值。【2026-09-24 新增】
# 副帅也是 kind=general，但吃掉它**不代表哪一方出局** —— 它代表的那个方早就出局了。
# 旧代码只判 `kind == GENERAL`，于是吃副帅被记成「斩帅」：slain +1 → 综合分凭空
# +1000（W_SLAIN），前端还会渲染成「斩帥 X方主帅」（见 web/app.js:149 的三元链）。
# 这里给它一个近似价值：真正收益是「那批残兵易主」，已由 material 体现，
# 所以按一枚车计即可，不重复计价。
DEPUTY_VALUE = VALUE[R.ROOK]


def credit_kill(m, army, victim):
    """把一次吃子记进战绩（斩帅 / 吃子）

    唯一判据：**只有非副帅的主帅**才算「斩帅」。
    """
    if victim["kind"] == R.GENERAL and not victim.get("deputy"):
        m.slain[army] = m.slain.get(army, 0) + 1
    elif victim["kind"] == R.GENERAL:                       # 副帅
        m.kills[army] = m.kills.get(army, 0) + DEPUTY_VALUE
    else:
        m.kills[army] = m.kills.get(army, 0) + VALUE.get(victim["kind"], 1.0)


def move_log_entry(army, frm, to, ply, note, **extra):
    """构造一条 `type='move'` 战报 —— **全项目唯一的落子战报构造点**。

    🔴【2026-10-01 修的 bug · 字段丢失】
      老师报：「蜀的车吃完吴的帅后，蜀的车没有升级成副帅」。
      存档重放（`server/data/autosave.json` 全 109 手）还原的真相：
        · ply 27 `229-225` 魏**炮**吃吴**真帅** ⇒ 炮**已经正确**就地升格为副帥（驻 225）；
        · ply 28 `227-225` **蜀車**吃掉的正是**那枚副帥** ⇒ 依《一、7》原文
          「副帅……直至被吃掉（**棋子再次易主**）」⇒ **不产生新副帅**（引擎行为正确）。
      之所以看着像 bug：这两条战报都只显示「吃 帥」——
        `game_dxf.apply()` 会写 `note["is_deputy"]` / `note["promoted_from"]`，
        `web/app.js` 的 `evHTML()` 也**读**这两个字段，但**服务端两处战报构造
        （`step()` / `manual_move()`）都漏抄** ⇒ 前端恒读 undefined：
          · 斩真帅 → 少了「炮→副帥」那一格（老师 09-25 明确要求过，等于没生效）；
          · 斩副帅 → `e.eliminated` 为空、`e.is_deputy` 又 undefined ⇒
            落到 `e.captured ? 吃 帥` 分支，显示成**「吃 帥」**，
            于是老师看到「吃了帅却没升级成副帅」。
      ⇒ 对策两条：(1) 本函数作为**唯一构造点**，字段只写一处，防再丢；
                 (2) `_repair_move_log()` 续局时按回看缓冲**回填**历史条目。
    """
    entry = {
        "type": "move", "army": army, "from": frm, "to": to, "ply": ply,
        "captured": note.get("captured"),
        "captured_army": note.get("captured_army"),
        "eliminated": note.get("eliminated"),
        # ★ 就是这两个字段被丢过：缺了它们前端只会渲染成「吃 帥」
        "is_deputy": note.get("is_deputy"),
        "promoted_from": note.get("promoted_from"),
    }
    entry.update(extra)
    return entry


def score(state, kills, slain, wrong):
    """综合实力评分（数值越高越强），供排名使用"""
    mat = {int(k): v for k, v in material(state).items()}
    alive = set(GA.alive_armies(state))
    out = {}
    for k in (1, 2, 3):
        out[k] = round(
            slain.get(k, 0) * W_SLAIN
            + mat.get(k, 0.0) * W_MAT
            + kills.get(k, 0.0) * W_KILL
            + (W_ALIVE if k in alive else 0.0)
            - wrong.get(k, 0) * W_WRONG, 1)
    return out


def rank_of(scores, state):
    """排出名次：分数降序，同分则在场者优先"""
    alive = set(GA.alive_armies(state))
    order = sorted(scores, key=lambda k: (-scores[k], 0 if k in alive else 1, k))
    return {k: i + 1 for i, k in enumerate(order)}, order


class Match:
    def __init__(self, roster=None, auto=False):
        self.roster = roster or load_roster()
        self.opts = self.roster.get("options", {})
        self.agents = {int(k): build_agent(v)
                       for k, v in self.roster["players"].items()}
        self.meta = {int(k): describe(v) for k, v in self.roster["players"].items()}
        self.lock = threading.RLock()
        self.cv = threading.Condition(self.lock)
        self.auto = auto
        self.pending = False
        self.alive = True
        # ---- 「一键推荐下一步」的重入保护（老师 2026-10-01）----
        #   推荐用的是最高档 12 plies（实测 40+ 秒），老师很可能等不及连点几次。
        #   没有这个标志的话，N 次点击 = N 个搜索线程同时跑满 CPU，
        #   反而让**真正在跑的对局**（_loop 里的 Bot）抢不到核、越点越慢。
        self._hint_busy = False
        # ---- 续局存档（默认关；app.py 调 enable_autosave() 才落盘）----
        #   ⚠️ autosave_path=None ⇒ 所有 `_autosave()` 都是空转。
        #      这是**故意**的：tests 里到处 `Match()`，一旦默认落盘，
        #      跑一次回归就把老师正在下的一局覆盖掉了。
        self.autosave_path = None
        self.saved_at = None            # 最近一次成功落盘的时间戳
        self.restored_from = None       # 若是恢复来的：存档里的 saved_at（前端提示用）
        self.save_error = ""            # 最近一次落盘失败原因（不抛，只记）
        # ---- 失误谱评分器（Arena）｜【2026-09-24 老师定案：默认关闭】----
        # 实测代价：评分器 9.47s/手（6 层全宽）→ 300 手 47.4 分钟；
        #           而 LocalBot 走棋仅 0.019s/手（差 500 倍）。
        # 收益核对（消费点已全项目 grep）：
        #   · arena.grade_move 在 apply() **之前**打分 → **不进决策**，对棋力零贡献；
        #   · graded/bad/loss_sum、log["grade"] → 只喂前端「失误 3/40」与战报徽章 = 观感；
        #   · 唯一与棋力有关的用途是「悔棋自动重走」（LABEL_BAD），但它依赖 allow_undo，
        #     而 allow_undo 默认 False → **默认路径下评分器是纯观感开销**。
        # 结论：默认关。要看失误谱/Arena 榜时，把 agents.json 的 grade_moves 置 true。
        # ⚠️ 一旦打开 allow_undo（悔棋），必须同时打开评分器 —— 否则悔棋判定失去尺子，
        #    自动悔棋会**静默失效**（set_undo() 里有防呆提示兜底）。
        self.grade_on = bool(self.opts.get("grade_moves", False))
        self.grade_plies = int(self.opts.get("grade_plies", arena.GRADE_PLIES))
        self.grade_exact = bool(self.opts.get("grade_exact", True))
        self.grader = SearchBot(depth=1, time_limit=30.0, seed=20260923,
                                label=f"评分器（{'全宽' if self.grade_exact else '快速'}"
                                      f"{self.grade_plies}步）") \
            if self.grade_on else None
        if self.grader is not None:
            # exact=True：每个根着法用全窗口搜，分数是**真值**，
            #   失误谱的 loss 才不会被系统性高估（实测偏差 1.7 分）。慢约 2 倍。
            # exact=False：根着法沿用 alpha 剪枝，分数只是上界，只适合排序。
            self.grader.rank_exact = self.grade_exact
        # ---- 悔棋（默认关闭，网页勾选后启用）----
        # 每一方各自 3 次机会，用在自己"刚走出一步失误/大漏"的时候。
        # 悔棋依赖失误谱：没有评分器就无从判断"这步该不该悔"，自动悔棋不生效。
        self.allow_undo = bool(self.opts.get("allow_undo", False))
        self.undo_per_side = int(self.opts.get("undo_per_side", 3))
        # ---- 《一.5》连吃上限 ----
        # 老师 2026-09-24 定案：**默认不限制**（None），网页可自行输入整数。
        #   原文：「为避免蓄意的"二打一"，玩家可提前约定，连吃一方棋子不能超 (*) 个。」
        #   None=不限 / 0=禁止连吃 / N=同一方棋子最多连吃 N 个。
        self.chain_limit = self._norm_chain(self.opts.get("chain_limit"))
        # ---- 《一、3》回合与步数（老师 2026-09-24 引原文）----
        #   「三方对战，一方走一步或走多步（按约定步数）为一回合，直到决出胜负；
        #     各方使完约定步数时轮转到下一方。」
        #   默认 1 = 传统口径；N = 一方连走 N 步后才轮转到下一方。
        self.steps_per_turn = self._norm_steps(self.opts.get("steps_per_turn"))
        # ---- 人类接管（老师 2026-09-24）----
        #   「人类接管可任选一方，剩下两方或一方就是 bot 自动接管。」
        #   human_armies = 由**人类**走棋的方；不在集合里的方由 Bot 自动走。
        #   空集 = 三方全 Bot（观战档）。
        #   ★ 2026-10-01 老师：「开局默认，人类掌控魏国棋子，打勾」
        #     ⇒ 默认值由 `agents.json` 的 `options.human_armies` 决定（现为 [1] = 魏）。
        #       本类不再内置任何"默认哪一方"，一律读配置 —— 免得两处默认值打架。
        self.human_armies = set(self._norm_armies(self.opts.get("human_armies")))
        # ---- Bot 难度档（老师 2026-09-25 定案）----
        #   1 新手（不预判）/ 2 入门（3 plies）/ 3 进阶（6 plies）/ 4 大师（9 plies）
        #   默认读 agents.json 的 options.difficulty —— 老师指定 **第二档**；
        #   网页「难度」按钮随时可切。只换 Bot 的思考深度，不动对局本身。
        self.difficulty = DIFF.norm(self.opts.get("difficulty", DIFF.DEFAULT_LEVEL))
        # ---- 每方主控席位（老师 2026-10-02）----
        #   「有没有可能选择让魏国给人类，另外两个接入 deepseek 和 hy4 api？」
        #   「做成可选的选项，用本地 bot 或者 api」
        #   seats[k] = 老师**选的选项 id**（`__search__` / `deepseek-v4-flash` / `hy4`…），
        #   ⚠️ 它**不等于** cfg["model_id"]：难度档 1（新手）会把 cfg 的 model_id
        #      变成 `__local__`（一步贪心就是这个档的定义），但老师选的那一项
        #      仍然是"本地Bot" ⇒ 记"选项 id"下拉才不会自己跳回别的项。
        #   目录与逻辑在 agents/seats.py；这里只存状态。
        self.seats = {int(k): (v.get("model_id") or "")
                      for k, v in self.roster["players"].items()}
        #   「每方主控」下拉目录的**缓存**。为什么必须缓存而不是在 snapshot() 里现算：
        #   算 readiness 要读 ~/.workbuddy/models.json，而 /api/state 每 ~800ms 被
        #   轮询一次 ⇒ 现算等于把磁盘 I/O 塞进锁内（本项目明令禁止）。
        #   只在 3 处刷新：构造（经 apply_difficulty）/ set_seat / apply_difficulty。
        self._seat_ui = {"local": [], "api": []}
        self.reset()
        # ⚠️ 必须在 reset() 之后：apply_difficulty 会往 self.log 写记录，
        #    而 self.log 是 reset() 里才建出来的。
        #    （apply_difficulty 末尾会顺手刷新 `self._seat_ui` 下拉目录缓存）
        self.apply_difficulty(self.difficulty, quiet=True)
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()

    # ------------------------------------------------------------ 生命周期
    @staticmethod
    def _norm_chain(v):
        """把网页/agents.json 传来的连吃上限归一化：空串 / None / 负数 → None（不限制）"""
        if v is None or v == "":
            return None
        try:
            n = int(v)
        except (TypeError, ValueError):
            return None
        return n if n >= 0 else None

    def set_chain_limit(self, v):
        """网页输入框：《一.5》连吃上限。空 = 不限制；0 = 禁止连吃；N = 最多 N 个。"""
        with self.lock:
            self.chain_limit = self._norm_chain(v)
            self.state["chain_limit"] = self.chain_limit
            n = self.chain_limit
            self.log.append({
                "type": "info",
                "text": ("连吃上限：**不限制**（传统象棋口径）" if n is None
                         else ("连吃上限：**禁止连吃**（(*)=0）" if n == 0
                               else f"连吃上限：同一方棋子最多连吃 **{n}** 个"))})
            self._autosave()
            return {"ok": True, "chain_limit": self.chain_limit}

    @staticmethod
    def _norm_steps(v):
        """把约定步数归一化：空 / None / 非法 / <1 → 1；上限 20（防呆）"""
        if v is None or v == "":
            return 1
        try:
            n = int(v)
        except (TypeError, ValueError):
            return 1
        return min(max(n, 1), 20)

    def set_steps_per_turn(self, v):
        """网页输入框：《一、3》约定步数。1 = 传统（走一步即轮转）；N = 连走 N 步。"""
        with self.lock:
            self.steps_per_turn = self._norm_steps(v)
            n = self.steps_per_turn
            self.state["steps_per_turn"] = n
            self.state["turn_steps"] = 0
            self.log.append({
                "type": "info",
                "text": ("每回合步数：**1**（传统口径，走一步即轮转）" if n == 1
                         else f"每回合步数：**{n}**（一方连走 {n} 步后才轮转到下一方）")})
            self._autosave()          # 规则约定跨重启保留
            return {"ok": True, "steps_per_turn": n}

    @staticmethod
    def _norm_armies(v):
        """把「人类接管的方」归一化为 1/2/3 的整数列表（兼容 [1,2] / "1,2" / ""）"""
        if v is None or v == "":
            return []
        if isinstance(v, str):
            parts = [x for x in v.replace("，", ",").split(",") if x.strip()]
        elif isinstance(v, (list, tuple, set)):
            parts = list(v)
        else:
            parts = [v]
        out = []
        for x in parts:
            try:
                k = int(x)
            except (TypeError, ValueError):
                continue
            if k in (1, 2, 3) and k not in out:
                out.append(k)
        return out

    def set_human(self, armies):
        """网页勾选框：哪几方由**人类**接管，其余方 Bot 自动走

        老师 2026-09-24：「人类接管可任选一方，剩下两方或一方就是 bot 自动接管。」
        """
        with self.lock:
            s = self.state
            arms = [k for k in self._norm_armies(armies)
                    if k not in s.get("out", [])]      # 已失去资格的方不接管
            self.human_armies = set(arms)
            if arms:
                txt = "、".join(GA.ARMY_CN[k] for k in arms)
                bot = "、".join(GA.ARMY_CN[k] for k in (1, 2, 3)
                                if k not in self.human_armies) or "无"
                self.log.append({"type": "info",
                                 "text": f"人类接管：**{txt}**；其余（{bot}）由 Bot 自动接管"})
            else:
                self.log.append({"type": "info", "text": "人类接管：**无**（三方全 Bot）"})
            self._autosave()          # 席位变更跨重启保留（否则重启又要手勾）
            return {"ok": True, "human_armies": sorted(self.human_armies)}

    # ------------------------------------------------------------ 每方主控
    #   老师 2026-10-02：
    #     「有没有可能选择让魏国给人类，另外两个接入 deepseek 和 hy4 api？」
    #     「做成可选的选项，用本地 bot 或者 api」
    #   ⇒ 网页「每方主控」魏/吴/蜀 三个下拉，各选「本地Bot」或某个 API 大模型。
    #   · 本地Bot 那一项**受「Bot 难度」档位接管**（想变弱就调难度档 1，不是在这里选贪心）
    #   · API 那一项**不受难度档影响**（`difficulty_skipped` 会如实列出这一方）
    #   · 目录/配置在 agents/seats.py + agents.json 的 `model_options`（前端不用改）
    def _refresh_seat_ui(self):
        """刷新「每方主控」下拉目录缓存（本地Bot 的 brief 会跟着难度档变）"""
        try:
            self._seat_ui = SEATS.describe_for_ui(self.roster, self.difficulty)
        except Exception:                          # noqa: BLE001
            pass
        return self._seat_ui

    def seat_options(self):
        """给网页画「每方主控」下拉的目录（**读缓存**，不做磁盘 I/O）"""
        return self._seat_ui

    def set_seat(self, army, model_id, quiet=False, save=True):
        """网页下拉：把某一方的脑子换成「本地Bot / API 大模型」

        红线（三条，都有专项断言）：
          1. **只换** `agents[k]` / `meta[k]` —— 棋盘 / 轮次 / 战绩 / 悔棋次数 /
             规则约定 / 人类接管设置 **一律不动**（与切难度档同一条口径）。
          2. 未就绪的 API 条目**明确拒绝**并说明原因 —— **绝不静默换成本地 Bot**
             （"选了没反应 / 悄悄换了模型"是最难查的一类 bug）。
          3. 同时**写回** `self.roster["players"][k]` —— 否则之后切难度档会按
             旧 cfg 重建，把刚换上去的模型冲掉。
        """
        try:
            k = int(army)
        except (TypeError, ValueError):
            return {"ok": False, "error": f"军队编号必须是 1 / 2 / 3（收到 {army!r}）"}
        if k not in (1, 2, 3):
            return {"ok": False, "error": f"军队编号必须是 1 / 2 / 3（收到 {army!r}）"}
        opt = SEATS.find(self.roster, model_id)
        if opt is None:
            return {"ok": False,
                    "error": f"未知的主控选项：{model_id!r}（可选见 /api/state 的 seat_options）"}
        ready, why = SEATS.readiness(opt)
        if not ready:
            return {"ok": False, "error": why, "model_id": opt["id"], "ready": False}
        with self.lock:
            # 从 **原始 roster 里的那一方** 出发，保住 use_value / max_tokens / seed 等
            base = dict(self.roster["players"][str(k)])
            cfg = SEATS.apply(base, opt, self.difficulty)
            self.roster["players"][str(k)] = cfg
            self.agents[k] = build_agent(cfg)
            self.meta[k] = describe(cfg)
            self.seats[k] = opt["id"]       # 记**选项 id**（不是 cfg 的 model_id，见类头注释）
            if not quiet:
                cn = GA.ARMY_CN[k]
                if opt.get("local"):
                    lv = DIFF.get(self.difficulty)
                    txt = (f"{cn}方主控 → **本地Bot · 搜索**"
                           f"（受难度档「{lv['name']} {lv['brief']}」接管）")
                else:
                    txt = (f"{cn}方主控 → **{opt.get('label') or opt['id']}**"
                           f"（API 大模型，**不受难度档影响**；单步耗时见下拉提示）")
                self.log.append({"type": "info", "text": txt})
        self._refresh_seat_ui()
        if save:
            self._autosave()           # 席位变更跨重启保留
        return {"ok": True, "army": k, "model_id": opt["id"],
                # ⚠️ `actual_model` 必须是**真正请求的那个模型名**。
                #   用 `cfg["model_id"]` 是错的：目录条目一旦用 `key_from` 借密钥，
                #   `model_id` 就变成了**凭据来源那条**（借密钥的代价），
                #   直接返回会让老师看到"我选的是 Nemotron，回执却写 DiffusionGemma"。
                #   `api_model` 才是真正的模型名，没有时才回落到 model_id。
                "actual_model": cfg.get("api_model") or cfg.get("model_id"),
                "cred_from": cfg.get("model_id") if cfg.get("api_model") else None,
                "label": cfg.get("label"),
                "seats": {str(a): v for a, v in self.seats.items()}}

    # ------------------------------------------------------------ 难度档
    def apply_difficulty(self, level, quiet=False):
        """把三方 Bot 重建为指定难度档（内部实现；带日志的入口是 set_difficulty）

        老师 2026-09-25：
            「网页设置难度4个档，最低档不需要树状预判，属于新手，然后第二档，
              就是博弈树逐层 3 plies，第3档6 plies，第4档9 plies」
            「bot挑战难度档位可以在网页里面选择，默认选第二档」
        档位表见 agents/difficulty.py（单一事实来源）。

        为什么**重建对象**而不是改属性：SearchBot 在 __init__ 里就把
        depth / time_limit 吃进了迭代加深的内部状态（_deadline / _hist /
        _killers / weights 等），运行中改属性容易留下半新半旧的脏状态；
        直接换对象最干净，代价只是一次实例化（微秒级）。

        ⚠️ 只换「Bot 的脑子」：棋盘 / 轮次 / 战绩 / 悔棋次数 / 规则约定
           一律保留；人类接管的那几方本来就不走 Bot ⇒ 不受影响。
        """
        lv = DIFF.get(level)
        skipped = []                     # 被跳过的方（真实大模型，不受难度档影响）
        with self.lock:
            self.difficulty = lv["level"]
            for k, cfg in self.roster["players"].items():
                # ★ 只接管**本地 Bot**。填了真实大模型（model_id 是具体模型名）
                #   的那一方原样保留 —— 否则「切个难度」会把老师配好的 LLM
                #   对手悄悄换成本地 Bot，这是静默破坏功能。
                if not DIFF.is_local(cfg):
                    skipped.append(cfg.get("army") or str(k))
                    continue
                cfg2 = DIFF.apply(cfg, lv["level"])
                kk = int(k)
                self.agents[kk] = build_agent(cfg2)
                self.meta[kk] = describe(cfg2)
            # 被跳过的方把已有 label 保留（meta 里已经是 LLM 的描述）
            if not quiet:
                extra = f"（{'、'.join(skipped)}方为大模型，不受影响）" if skipped else ""
                self.log.append({
                    "type": "info",
                    "text": f"Bot 难度 → **{lv['name']}（{lv['brief']}）**："
                            f"{lv['desc'].split('。')[0]}。{extra}"})
        out = DIFF.describe(lv["level"])
        out["ok"] = True
        out["skipped"] = skipped
        self._refresh_seat_ui()        # 本地Bot 那一项的 brief（N plies）跟着难度档变
        self._autosave()               # 难度档跨重启保留
        return out

    def set_difficulty(self, level):
        """网页「难度」按钮入口：{level: 1..4}（档位没变则不记战报）"""
        lv = DIFF.get(level)
        return self.apply_difficulty(lv["level"], quiet=(lv["level"] == self.difficulty))

    def reset(self):
        with self.lock:
            # ★ 世代号（2026-09-25 · 为长考档而生）：每次重开一局 +1。
            #   高档位单步 45~120 秒，老师等不及点「重开一局」是常态；
            #   正在思考的那一手回来时若发现世代号变了，必须**整手丢弃**
            #   （见 step() 里同名校验处的说明）。
            self.epoch = getattr(self, "epoch", 0) + 1
            self.state = GA.new_game(first=self.opts.get("first", 1))
            self.state["chain_limit"] = self.chain_limit   # 《一.5》约定（跨局保留）
            self.state["chain"] = {}
            self.state["steps_per_turn"] = self.steps_per_turn   # 《一、3》约定（跨局保留）
            self.state["turn_steps"] = 0
            self.log = []
            self.kills = {1: 0.0, 2: 0.0, 3: 0.0}      # 吃掉的敌子价值（不含帅）
            self.slain = {1: 0, 2: 0, 3: 0}            # 斩帅次数
            self.wrong = {1: 0, 2: 0, 3: 0}            # 非法输出/回退次数
            self.bad = {1: 0, 2: 0, 3: 0}              # 失误+大漏 次数（失误谱）
            self.graded = {1: 0, 2: 0, 3: 0}           # 已评分步数
            self.loss_sum = {1: 0.0, 2: 0.0, 3: 0.0}   # 累计归一化损失
            self.undo_left = {1: self.undo_per_side, 2: self.undo_per_side,
                              3: self.undo_per_side}   # 各方剩余悔棋机会
            self.undo_used = {1: 0, 2: 0, 3: 0}
            self.snapshots = []                        # 每步落子前的存档（供悔棋回滚）
            self.thinking = None
            # 「判和」终止标志。【2026-09-24 修复】原实现只往 log 塞一条 draw 就 return，
            # 既不写 winner 也不推 ply → _finished() 恒为 False → _loop() 每 0.2s
            # 再调一次 step()、再刷一条 draw，永不终止（实测 4 次 step 出 4 条判和）。
            # 前端 app.js 早就有 `finished && !winner → 终局：按综合分排名` 的分支，
            # 是后端没把这个契约补上。这里用独立标志表达「三方均无法取胜」，
            # 不改 winner 语义（判和不该伪造胜方），也不动 ply（那不是着法数）。
            self.drawn = False
            self.started = time.time()
            # ---- 回看缓冲（老师 2026-09-24 夜）----
            #   「点击一次回退一个，可以一直往前回退，弄个按钮继续下，
            #     这样我就知道 bot 走哪里了」
            #   语义：**只读**历史回放，绝不改对局状态（不是悔棋）。
            #   `replay[i]` = 第 i 手**走完之后**的局面 ⇒ 索引就是 ply，天然对齐。
            #   内存：每项 = 48 个点位 dict（≈1KB）×最多 (max_ply+1) 项
            #         → 默认 max_ply=240 时约 0.25MB，可忽略。
            #   ⚠️ 不设上限会随 ply 无限涨；但 ply 本身受 max_ply 约束（_finished），
            #      所以这里只做一道宽松防呆（见 _record_replay）。
            self.replay = []
            self._record_replay()          # 第 0 项 = 开局（"回退到底"能看到原始布局）
            self.restored_from = None      # 重开一局 ⇒ 不再是"恢复来的"
            # 重开一局 ⇒ 立刻覆盖存档（否则下次启动会"续"回已被弃掉的那局）
            self._autosave()

    # ======================================================== 续局存档（老师 2026-10-01）
    #   设计说明见文件顶部 SAVE_VERSION 附近。核心三段：_save_payload / _autosave /
    #   restore —— 外加一个"坏了也绝不崩"的兜底 _quarantine。
    @staticmethod
    def _norm_state_types(st):
        """把 JSON 往返变成**字符串键**的 int-key dict 还原回 int 键。

        ⚠️ 不做这步的后果不是报错，而是**静默下错棋**：`combat[1]` 取不到
        `"1"` 的值 → `s["combat"].get(army, True)` 一律走默认 True ⇒
        已判负/已认输的一方又能动了。这类"读得出来但语义变了"的坑最难查，
        所以这里只列**引擎里确实是 int 键**的字段，不做"顺手全转"。
        """
        if not isinstance(st, dict):
            return st
        for k in ("vitality", "combat", "annexed", "deputies", "chain", "repeat"):
            v = st.get(k)
            if isinstance(v, dict):
                nv = {}
                for kk, vv in v.items():
                    if isinstance(vv, dict):        # annexed/chain 的值可能是 dict
                        vv = {(int(k3) if str(k3).lstrip("-").isdigit() else k3): v3
                              for k3, v3 in vv.items()}
                    try:
                        nv[int(kk)] = vv
                    except (TypeError, ValueError):
                        nv[kk] = vv
                st[k] = nv
        # history / passed 里存的是点位号（字符串）或着法，原样即可
        return st

    @staticmethod
    def _norm_snap(sn):
        """把**从存档读回的悔棋快照**做同样的键归一化。

        ⚠️ 这是一个既有缺陷的修复（2026-10-02 由终局自救暴露）：
           `_save_payload()` 把 `snapshots` 原样写进 JSON，JSON 往返会把
           `{"kills": {1: 0}}` 变成 `{"kills": {"1": 0}}`；`restore()` 却把
           snapshots **原样 list() 回来**。于是"重启续局后再悔棋"时，
           回滚出来的 `self.graded` / `kills` / `slain` / `bad` / `loss_sum`
           全是**字符串键**，而 `snapshot()` 与前端一律按 int 取值 ⇒
           实测崩在 `snapshot()` 的 `self.graded[k]`（KeyError: 1）。

           以前没暴露：老师过去都在**同一进程内**悔棋，快照是刚 `_push_snapshot`
           出来的、int 键完好；终局自救是第一条"必然要跨存档用快照"的路径。

           `state` 同样要过 `_norm_state_types` —— 里面 annexed / combat /
           deputies 等也是 int 键，不转就会"读得出来但语义变了"（静默出错）。
        """
        if not isinstance(sn, dict):
            return sn
        sn = dict(sn)
        sn["state"] = Match._norm_state_types(sn.get("state"))
        for k in ("kills", "slain", "bad", "graded", "loss_sum"):
            v = sn.get(k)
            if isinstance(v, dict):
                nv = {}
                for kk, vv in v.items():
                    try:
                        nv[int(kk)] = vv
                    except (TypeError, ValueError):
                        nv[kk] = vv
                sn[k] = nv
        return sn

    def _save_payload(self):
        """构造存档内容（调用方须已持锁）"""
        with self.lock:
            return {
                "version": SAVE_VERSION,
                "saved_at": time.time(),
                "state": self.state,
                "log": self.log[-LOG_KEEP:],
                "kills": self.kills, "slain": self.slain, "wrong": self.wrong,
                "bad": self.bad, "graded": self.graded,
                "loss_sum": self.loss_sum,
                "undo_left": self.undo_left, "undo_used": self.undo_used,
                "allow_undo": self.allow_undo,
                "undo_per_side": self.undo_per_side,
                "chain_limit": self.chain_limit,
                "steps_per_turn": self.steps_per_turn,
                "human_armies": sorted(self.human_armies),
                "difficulty": self.difficulty,
                # 每方主控席位（老师 2026-10-02）：记**选项 id**，不打散成 cfg。
                #   ⇒ 换模型/改密钥后重开一局，老师的席位选择照样能复原。
                "seats": {str(k): v for k, v in self.seats.items()},
                "auto": self.auto,
                "epoch": self.epoch,
                "started": self.started,
                "drawn": self.drawn,
                # 悔棋存档：只留最近 SNAP_KEEP 条（栈式使用，裁头部无副作用）
                "snapshots": self.snapshots[-SNAP_KEEP:],
                # 回看缓冲：**完整**存。它的索引 == ply（replay_at 的契约），
                #   裁头部会破坏这个契约（"第 i 手"会指到别的局面）。
                #   代价可接受：240 手 × 2.4KB ≈ 580KB。
                "replay": self.replay,
            }

    def _autosave(self):
        """每手落子 / 悔棋 / 改配置后调用。**任何失败都不许影响对局**。"""
        p = self.autosave_path
        if not p:
            return False
        try:
            return self.save(p)
        except Exception as e:              # noqa: BLE001 —— 存盘永远不能拖垮下棋
            self.save_error = f"{type(e).__name__}: {e}"
            return False

    def save(self, path=None):
        """原子写存档：先写 .tmp 再 os.replace（中途崩溃不留半截 JSON）

        ⚠️ **序列化在锁内、写文件在锁外**：`_save_payload()` 返回的是 `self.state`
           等对象的**引用**，若在锁外再 json.dumps，别的线程正好落子就会序列化出
           "盘面是新的、ply 是旧的"这种撕裂状态。字符串化只花几毫秒，锁内做完；
           真正慢的磁盘 I/O 放到锁外，不挡下棋。
        """
        p = path or self.autosave_path
        if not p:
            return False
        with self.lock:
            blob = json.dumps(self._save_payload(), ensure_ascii=False,
                              separators=(",", ":"))
            saved_at = time.time()
        d = os.path.dirname(p)
        if d:
            os.makedirs(d, exist_ok=True)
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(blob)
            f.flush()
            os.fsync(f.fileno())            # 落盘再改名，避免"文件有了但内容是空的"
        os.replace(tmp, p)
        self.saved_at = saved_at
        self.save_error = ""
        return True

    def _quarantine(self, p, why):
        """存档不可用 → 改名留档（便于事后看），绝不阻塞启动"""
        try:
            bad = f"{p}.bad_{time.strftime('%Y%m%d_%H%M%S')}"
            os.replace(p, bad)
            self.log.append({"type": "warn",
                             "text": f"⚠ 存档不可用（{why}）→ 已另存为 "
                                     f"{os.path.basename(bad)}，本次开新局"})
        except Exception:
            pass

    def restore(self, path=None, quiet=False):
        """读存档续上上一局。返回 {"restored", "reason", "ply", "saved_at"}

        红线：**任何异常都不许冒泡** —— 存档坏了也必须能正常开新局。
        """
        p = path or self.autosave_path or SAVE_FILE
        if not os.path.exists(p):
            return {"restored": False, "reason": "无存档", "ply": 0}
        try:
            with open(p, "r", encoding="utf-8") as f:
                d = json.load(f)
        except Exception as e:              # noqa: BLE001
            self._quarantine(p, f"解析失败 {type(e).__name__}")
            return {"restored": False, "reason": f"存档损坏（已备份）：{e}", "ply": 0}
        try:
            ver = int(d.get("version") or 0)
        except (TypeError, ValueError):
            ver = 0
        if ver != SAVE_VERSION:
            self._quarantine(p, f"版本 {ver} ≠ {SAVE_VERSION}")
            return {"restored": False,
                    "reason": f"存档版本不匹配（{ver} ≠ {SAVE_VERSION}，已备份）",
                    "ply": 0}
        st = self._norm_state_types(d.get("state"))
        if not isinstance(st, dict) or not isinstance(st.get("board"), dict) \
                or not st["board"]:
            self._quarantine(p, "state 缺失")
            return {"restored": False, "reason": "存档缺少盘面（已备份）", "ply": 0}
        try:
            with self.lock:
                self.state = st
                self.log = list(d.get("log") or [])
                self.kills = {int(k): v for k, v in (d.get("kills") or {}).items()}
                self.slain = {int(k): v for k, v in (d.get("slain") or {}).items()}
                self.wrong = {int(k): v for k, v in (d.get("wrong") or {}).items()}
                self.bad = {int(k): v for k, v in (d.get("bad") or {}).items()}
                self.graded = {int(k): v for k, v in (d.get("graded") or {}).items()}
                self.loss_sum = {int(k): v
                                 for k, v in (d.get("loss_sum") or {}).items()}
                up = int(d.get("undo_per_side") or self.undo_per_side)
                self.undo_per_side = up
                self.undo_left = {int(k): v
                                  for k, v in (d.get("undo_left") or {}).items()} \
                    or {1: up, 2: up, 3: up}
                self.undo_used = {int(k): v
                                  for k, v in (d.get("undo_used") or {}).items()} \
                    or {1: 0, 2: 0, 3: 0}
                for k in (1, 2, 3):         # 缺键补齐，防半截存档
                    self.undo_left.setdefault(k, up)
                    self.undo_used.setdefault(k, 0)
                self.allow_undo = bool(d.get("allow_undo", self.allow_undo))
                self.chain_limit = self._norm_chain(d.get("chain_limit"))
                self.state["chain_limit"] = self.chain_limit
                self.steps_per_turn = self._norm_steps(d.get("steps_per_turn"))
                self.state["steps_per_turn"] = self.steps_per_turn
                # ★【2026-10-02】只修**副帅登记表**，不重算 vitality/combat。
                #   `deputies` 是派生表，老存档里可能残留"已升格成别方副帅"的旧条目
                #   （老师那局 ply 64：驻吴帐的蜀方副帅跑去斩魏帥 ⇒ 盘上只剩 1 枚、
                #    登记表却有 2 条）⇒ 不清的话前端状态条会多显一条**幽灵副帅**。
                #   ⚠️ 刻意不调 refresh_combat：那会重算 vitality/combat，把存档里
                #     已算好的值覆盖掉，破坏 restore 的"忠实还原"语义
                #     （`_verify_resume.py` 的语义级往返断言就是这么抓到的）。
                P.prune_deputies(self.state)
                self.human_armies = set(self._norm_armies(d.get("human_armies")))
                self.difficulty = DIFF.norm(d.get("difficulty", self.difficulty))
                self.auto = bool(d.get("auto", False))
                self.epoch = int(d.get("epoch") or 0)
                self.started = float(d.get("started") or time.time())
                self.drawn = bool(d.get("drawn", False))
                self.snapshots = [self._norm_snap(sn)
                                  for sn in (d.get("snapshots") or [])]
                # 回看缓冲同理：`annexed` / `combat` 等 int 键要转回来，
                #   否则"续局后回看早期局面"的状态条会静默显示成空。
                self.replay = [self._norm_state_types(rp)
                               for rp in (d.get("replay") or [])]
                # 历史快照同样去残留（否则点「回看」翻到第 64 手也见幽灵副帅）。
                for _rp in self.replay:
                    if _rp.get("board"):
                        P.prune_deputies(_rp)
                if not self.replay:         # 老存档没有 replay ⇒ 补个第 0 项
                    self._record_replay()
                else:
                    self._repair_move_log()   # 老战报缺 is_deputy/promoted_from ⇒ 回填
                self.restored_from = float(d.get("saved_at") or 0) or None
                self.saved_at = self.restored_from
        except Exception as e:              # noqa: BLE001
            self._quarantine(p, f"恢复失败 {type(e).__name__}")
            return {"restored": False, "reason": f"恢复失败（已备份）：{e}", "ply": 0}
        # 恢复后按存档的难度档重新装配 Bot（robot 的 depth 等要跟着走）
        try:
            self.apply_difficulty(self.difficulty, quiet=True)
        except Exception:
            pass
        # ---- 每方主控席位（老师 2026-10-02）：显式选择 > agents.json 的默认 ----
        #   ⚠️ 必须在 apply_difficulty **之后**：set_seat 换回本地 Bot 时要套上
        #      当前难度档，否则会掉回 agents.json 的兜底 depth。
        #   ⚠️ save=False：此刻 `self.autosave_path` 还没设好（enable_autosave 里
        #      先 restore 再设路径），在这里存盘会写错地方。
        seatfail = []
        for _k, _mid in (d.get("seats") or {}).items():
            try:
                _kk = int(_k)
            except (TypeError, ValueError):
                continue
            if _kk not in (1, 2, 3):
                continue
            if SEATS.find(self.roster, _mid) is None:
                # 这一方的模型是**agents.json 里直接配的**（不在下拉目录里），
                # 跟"老师的席位选择"无关 ⇒ 静默跳过，别报"恢复失败"的假警报。
                continue
            r = self.set_seat(_kk, _mid, quiet=True, save=False)
            if not r.get("ok"):
                seatfail.append(f"{_k}:{_mid}")
        self._seat_ui = SEATS.describe_for_ui(self.roster, self.difficulty)
        if seatfail and not quiet:
            # 存档里记的席位现在不可用（例如 HY4 的密钥被删了）⇒ **如实说**，
            # 不要静默掉回本地 Bot —— 那正是最难查的一类 bug。
            self.log.append({"type": "info",
                             "text": f"⚠️ 存档里的席位未能恢复（已保留原主控）："
                                     f"{'、'.join(seatfail)}"})
        if not quiet:
            who = "、".join(GA.ARMY_CN[k] for k in sorted(self.human_armies)) or "无（观战）"
            lvname = (DIFF.get(self.difficulty) or {}).get("name") or self.difficulty
            self.log.append({
                "type": "info",
                "text": f"↻ 已恢复上次对局：第 {self.state.get('ply')} 手，"
                        f"轮到{GA.ARMY_CN[self.state.get('turn', 1)]}方"
                        f"（人类席位：{who}；难度：{lvname}）"})
        return {"restored": True, "reason": "已恢复", "ply": self.state.get("ply"),
                "saved_at": self.saved_at, "turn": self.state.get("turn")}

    def enable_autosave(self, path=None, restore=True):
        """开启自动存盘（app.py 专用）。restore=True 时先续上上一局。"""
        info = {"restored": False, "reason": "未尝试", "ply": 0}
        if restore:
            info = self.restore(path)       # 先恢复（用同一路径）
        self.autosave_path = path or SAVE_FILE
        try:
            os.makedirs(os.path.dirname(self.autosave_path), exist_ok=True)
        except Exception:
            pass
        # ★【2026-10-01 修】**只有没恢复成功时**才立刻落一次盘。
        #   恢复成功 ⇒ 存档内容本来就等于当前状态，再存一次纯属多余，
        #   而且会把 `restore()` 末尾那条「↻ 已恢复上次对局…」**瞬时提示日志**
        #   一起固化进存档 ⇒ 下次启动又读出来、再加一条 ⇒ **每次重启累加一条**
        #   （实测第 2 次启动就已出现两条完全相同的提示）。
        #   恢复失败（无存档/损坏/版本不符）才需要落盘，把新开局变成存档。
        if not info.get("restored"):
            self._autosave()
        return info

    def discard_save(self):
        """丢弃存档并开新局（前端「重开新局」/「不要再续」用）"""
        p = self.autosave_path or SAVE_FILE
        with self.lock:
            self.reset()
            self.restored_from = None
        for f in (p, p + ".tmp"):
            try:
                if os.path.exists(f):
                    os.remove(f)
            except Exception:
                pass
        self._autosave()
        return {"ok": True, "ply": self.state.get("ply")}

    # ------------------------------------------------------------ 回看（只读）
    def _recent_move_notes(self, n=2):
        """从 log 里倒着找最近 n 手走子，返回 **[最近, 再往前, ...]** 或 []

        老师 2026-09-25：「目前你会用红色虚线显示前一次走棋，但不够，我需要
        前两次，分别用红色和橙色虚线表示前一次和前两次」——因为"吃子"往往只是
        结果，根因常在上上一步（对方刚把子送到这里 / 自己刚让开炮架）。

        ⚠️ 无需担心悔棋：`undo_last()` 里已 `del self.log[snap["log_len"]:]`
           真正删掉被撤回的记录 ⇒ 这里读到的永远是**有效历史**。
        ⚠️ `pass`（无棋可走）不产生路径，会被跳过（老师要看的是"走棋路径"）。
        """
        out = []
        n = max(1, int(n))
        for e in reversed(self.log):
            if e.get("type") == "move":
                out.append({"from": e.get("from"), "to": e.get("to"),
                            "army": e.get("army"),
                            "captured": e.get("captured"),
                            # 【2026-10-01】带上 is_deputy：否则棋盘上的走子痕迹对
                            #   「吃副帥」也只写「吃帥」，与战报同一个误读来源。
                            "is_deputy": e.get("is_deputy"),
                            "ply": e.get("ply")})
                if len(out) >= n:
                    break
        return out

    def _last_move_note(self):
        """最近一手的走子信息（保留单数接口，等价于 _recent_move_notes(1) 首项）"""
        r = self._recent_move_notes(1)
        return r[0] if r else None

    def _record_replay(self):
        """把**当前**局面存进回看缓冲（在每手落子之后 / 开局时调用）

        只存回看真正需要的字段（棋盘 + 轮次 + 手数 + 上一步），
        不存 scores/log 等派生数据 —— 那些由前端按"回看中"另行提示。
        """
        with self.lock:                        # RLock，可重入（step/manual_move 里已持锁）
            s = self.state
            self.replay.append({
                "ply": int(s.get("ply") or 0),
                "turn": int(s.get("turn") or 1),
                "pieces": [{"pos": p, **v} for p, v in s["board"].items()],
                "last": self._last_move_note(),
                # 【2026-09-25】老师要「前两次」⇒ 回看也要能显示两手，
                #   否则回看时橙色那手会缺失（只剩红色一手）。
                "recent": self._recent_move_notes(2),
            })
            # 宽松防呆：正常对局（max_ply 默认 240）永远碰不到；只有把 max_ply
            # 调到极大时才需要，此时保留最近 4000 手足够回看。
            if len(self.replay) > 4000:
                del self.replay[:-4000]

    def _repair_move_log(self):
        """按**回看缓冲**回填战报里丢过的 `is_deputy` / `promoted_from`

        背景见 `move_log_entry()` 的 bug 注。老存档里的战报是旧代码写的，
        这两个字段是缺的 ⇒ 续局后老师翻历史仍然会看到「吃 帥」（而不是
        「斩副帥」/「炮→副帥」）。本函数负责把它们补上。

        做法（**只读回看缓冲，不动任何棋局状态**）：
          `replay[i]` 存的是**第 i 手走完之后**的盘面，所以一条 `ply = p` 的战报
          对应「走这手**之前**」的盘面 = `replay[p - 1]`。取之：
            · 落点 `to` 上的子带 `deputy` ⇒ `is_deputy = True`（斩的是副帥）；
            · 否则 `is_deputy = False`，`promoted_from` = 起点 `from` 上的子种类
              （= 那枚就地升格为副帥的棋子）。

        幂等：值非空的条目不碰；找不到对应快照的条目跳过。
        返回补好的条数（供测试断言）。
        """
        if not self.replay:
            return 0
        fixed = 0
        for e in self.log:
            if e.get("type") != "move" or e.get("captured") != R.GENERAL:
                continue
            if e.get("is_deputy") is not None:      # 已经是新代码写的，别动
                continue
            p = int(e.get("ply") or 0)
            if not (0 < p < len(self.replay)):
                continue
            before = {q.get("pos"): q
                      for q in (self.replay[p - 1].get("pieces") or [])}
            vic = before.get(e.get("to")) or {}
            if vic.get("deputy"):
                e["is_deputy"] = True
                e["promoted_from"] = None
            else:
                e["is_deputy"] = False
                e["promoted_from"] = (before.get(e.get("from")) or {}).get("kind")
            fixed += 1
        return fixed

    def _note_repeat_verdict(self, s, note):
        """把引擎的「重复着法」结论翻译成对局层后果

        【2026-10-02 老师改口径 · 本方法的**唯一权威表述**】老师原话：
          「长将判负：魏方反复走同一条路径（222-232）并且一直在将军，超过 3 次 →
            依传统中国象棋「长将判负」，该方失去行棋资格（帅留盘、棋子不易主，≠ 出局）
            **不对，为何魏方被判出局，你只要限制它不走重复路径就 ok 了**」

        ⇒ 本方法**不再有"判负"这条分支**：
          · 主路径是**事前拦截** —— `game_dxf.repeat_blocked` 把"第 4 次"直接从
            `legal_moves` 里摘掉，所以正常对局里**根本走不出**超限重复，
            连 `note` 都不会带重复标记；
          · 只有兜底场景（某方**除这条重复路径外无着可走**）才会走到这里
            ⇒ 判「不变作和」，对局结束、按综合分排名。
          · ⚠️ 绝不写 `out` / `declared_lose`：前端 `web/app.js` 把 `st.out`
            渲染成「已出局」，而本项目「出局」的**唯一**触发条件是**主帅被吃**。
            旧写法正是把"长将判负"塞进 `out` ⇒ 老师屏幕上出现"魏方被判出局"。

        返回 True 表示对局因重复而结束（判和）。
        """
        if not note.get("repeat_draw"):
            return False
        edge = note.get("repeat_edge")
        army = note.get("repeat_army")
        who = f"{GA.ARMY_CN[army]}方" if army in (1, 2, 3) else "某方"
        self.drawn = True
        self.log.append({
            "type": "draw", "ply": s["ply"], "army": army, "edge": edge,
            "text": f"重复判和：{who}反复走同一条路径（{edge}）已走满 "
                    f"{GA.REPEAT_LIMIT} 次上限，且**除这条路以外无着可走** → "
                    f"依传统中国象棋「不变作和」，判定在局各方平局"})
        return True

    def replay_at(self, i):
        """取第 i 手**走完之后**的局面（只读，不改对局）

        i 省略 / 非法 / 负数 → 最新一手；越界则夹到 [0, total]。
        返回 total = 最新一手的编号（= ply），前端据此算"共 N 手"。
        """
        with self.lock:
            n = len(self.replay)
            if n == 0:
                return {"ok": False, "error": "暂无历史"}
            try:
                i = int(i)
            except (TypeError, ValueError):
                i = n - 1
            if i < 0:
                i = n - 1
            i = max(0, min(i, n - 1))
            s = self.replay[i]
            return {"ok": True, "i": i, "total": n - 1,
                    "ply": s["ply"], "turn": s["turn"],
                    "pieces": s["pieces"], "last": s.get("last"),
                    # 最近两手（最新在前）：前端 红=第0项、橙=第1项
                    "recent": s.get("recent")
                              or ([s["last"]] if s.get("last") else []),
                    # 回看的是历史 → 明确告诉前端"这一手之后轮到谁"
                    "finished": bool(self._finished()) and i == n - 1}

    # ------------------------------------------------------------ 一键推荐下一步
    # 【老师 2026-10-01】原话：「加一个功能，可以一键推荐人类玩家走一下一步在棋盘上
    #   示意，但不帮他落子。你可以用蓝色虚线箭头加文字示意，推荐下一步必须专业，
    #   用上你最高档的 15 plies 的下棋智商」（★ 当天二次改口径：先 12 → 后 15）。
    #
    #   ★ 这是**只读**接口 —— 与 `/api/move` 的本质区别，四条设计约束缺一不可：
    #     ① **深拷贝再搜**：`SearchBot` 内部本来就会 `dict(state["board"])` 复制一次
    #        （见 search_bot._choose 的注），这里再 `copy.deepcopy` 一层是**双保险** ——
    #        万一将来搜索改成原地走子再撤销，也污染不到真实棋局。
    #        写测试时不能只断"返回的着法合法"，必须**逐字段比对调用前后的整个 state**
    #        （`_verify_hint.py` §只读红线）。
    #     ② **锁外搜索**：15 plies 是分钟级长考，绝不能抱着 `self.lock` 跑 ——
    #        `/api/state` 每 800ms 轮询一次，锁被占住 ⇒ 整个页面在长考期间卡死，
    #        老师会以为服务挂了。所以只在取快照/收尾时短暂持锁。
    #     ③ **带回 ply 与 epoch**：搜索期间局面可能变（老师自己落子、悔棋、重开、Bot 接着走）
    #        ⇒ 返回时把 `ply`/`epoch` 一起给前端，对不上就让前端丢弃
    #        （画一条"基于旧局面"的蓝线比不画更糟 —— 会诱导走错）。
    #     ④ **重入保护**：`_hint_busy` —— 老师容易连点，N 个 12 plies 同时跑会把
    #        真实对局的 Bot 挤到没核可用。
    def hint(self, plies=None, army=None, budget=None):
        """给某方推荐一手棋（默认当前回合方）。**绝不改对局。**

        plies  : 搜索 plies（3 的倍数）。
                 默认 **9**（`HINT_PLIES_DEFAULT`，2026-10-02 老师定：
                 「12 用的时间太长了」）—— 实测 0.05~1.8s **秒回**，
                 16 局面标定显示 9→12 无实质收益（ratio 1.00）而耗时 ×24。
                 **12** 是"慢档"（实测 ≈30s，对弈台在跑时可达 60s+，老师嫌久）；
                 **15** 是"深搜"选项 —— 2026-10-01 实测它与 12 的选招差别只有
                 0.04~0.06 分（噪声级），代价却是 20 倍时间（约 11 分钟）
                 ⇒ 只在老师明确要"拼到极限"时才用。
        army   : 1/2/3，默认当前回合方。
        budget : 时间上限（秒）。默认按 plies 查 `HINT_BUDGET`，硬上限，到点必返回。
        """
        with self.lock:
            if self._finished():
                return {"ok": False, "error": "对局已结束"}
            if self._hint_busy:
                return {"ok": False, "busy": True,
                        "error": "上一次推荐还在长考中，请稍候"}
            s = self.state
            try:
                a = int(army) if army not in (None, "") else int(s["turn"])
            except (TypeError, ValueError):
                return {"ok": False, "error": "方号非法"}
            if a not in (1, 2, 3):
                return {"ok": False, "error": f"方号非法：{army}"}
            # 已失去行棋资格的方（出局 / 判负 / 认输）不给推荐 —— 它本来就不能走棋。
            # ⚠️ 认输标志在 **state** 里（`s["resigned"]`），不是 Match 的属性
            #    —— `GA.resign()` 是往局面对象上写的。
            st = GA.status(s)
            if a in (st.get("resigned") or []):
                return {"ok": False, "error": f"{GA.ARMY_CN[a]}方已认输"}
            if a not in (st.get("alive") or [1, 2, 3]):
                return {"ok": False, "error": f"{GA.ARMY_CN[a]}方已出局"}
            legal = GA.legal_moves(s, a)
            if not legal:
                return {"ok": False, "error": f"{GA.ARMY_CN[a]}方当前无合法着法"}
            snap = copy.deepcopy(s)            # ① 深拷贝：搜索碰不到真实棋局
            ply0 = int(s.get("ply") or 0)
            ep0 = self.epoch                    # ③ 世代号（重开一局会 +1）
            self._hint_busy = True

        try:
            # 【2026-10-02 老师定】默认 **9 plies**（12 太慢）；12/15 保留为可选慢档。
            #   依据见 `HINT_BUDGET` 上方的两批实测注（批二 16 局面：9→12 ratio 1.00、
            #   耗时 ×24）。两个"诚实"的设计决定保留：
            #     ① 预算单独给（不抄档位表的 120s，也不按裸搜耗时给：对弈台
            #        在跑时推荐与 Bot 抢 JIT 锁，实测 12 plies 30s → 62s）。
            #     ② **实到深度如实回报**：返回的 `plies` 是实际搜到的层数，
            #        `depth` 是目标上限，前端两个都显示，不虚标。
            n_plies = (HINT_PLIES_DEFAULT if plies in (None, "")
                       else max(3, (int(plies) // 3) * 3))
            depth = max(1, n_plies // 3)
            tl = (HINT_BUDGET.get(n_plies, 180.0) if budget in (None, "")
                  else float(budget))
            bot = SearchBot(depth=depth, time_limit=tl,
                            seed=_hint_seed(snap),
                            label=f"推荐引擎（{depth * 3} plies）")
            res = bot.choose(snap, legal, "", GA.ARMY_CN[a])   # ② 锁外长考
            mv = (res or {}).get("move")
            info = getattr(bot, "last_info", None) or {}
            if not mv:
                return {"ok": False, "error": "搜索未给出着法"}
            frm, to = mv.split("-")[0], mv.split("-")[1]
            vic = snap["board"].get(to) or {}
            out = {
                "ok": True, "army": a,
                "from": frm, "to": to,
                "captured": vic.get("kind"),
                "captured_army": vic.get("army"),
                # ③ 局面指纹：前端拿它比对，不一致就丢弃（别画过期的线）
                "ply": ply0, "epoch": ep0,
                "depth": depth, "plies": info.get("plies"),
                "nodes": info.get("nodes"), "score": info.get("score"),
                "latency": round(float((res or {}).get("latency") or 0) / 1000.0, 2),
                "reason": (res or {}).get("reason", ""),
            }
            self.log.append({
                "type": "hint", "army": a, "from": frm, "to": to, "ply": ply0,
                "text": f"💡 推荐{GA.ARMY_CN[a]}方 {frm} → {to}"
                        + (f"（吃{_KIND_CN.get(vic.get('kind'), vic.get('kind'))}）"
                           if vic else "")
                        + f"：AI 搜到 {out['plies']} plies、{_score_txt(out['score'])}、"
                          f"耗时 {out['latency']}s（仅示意，未落子）"})
            return out
        finally:
            with self.lock:
                self._hint_busy = False

    def _loop(self):
        while self.alive:
            if not (self.auto or self.pending):
                time.sleep(0.15)
                continue
            if self._finished() or self.state["winner"]:
                self.auto = False
                self.pending = False
                time.sleep(0.4)
                continue
            # 轮到「人类接管」的方 → 停下来等玩家落子（不消费 pending）
            if self.state["turn"] in self.human_armies:
                time.sleep(0.2)
                continue
            self.pending = False
            try:
                self.step()
            except Exception as e:                     # 任何异常都不能弄死线程
                self.log.append({"type": "error", "text": f"{type(e).__name__}: {e}"})
                time.sleep(1.0)
            if self.auto:
                time.sleep(self.opts.get("delay_between_moves", 0.8))

    def _finished(self):
        """终局判据：①有帅被斩（winner）②三方均无法取胜（drawn）③着法数达上限

        注：③ 的 max_ply 是「撑满上限也分不出胜负」的兜底和棋，与 ② 的区别只是
        触发路径不同——② 是当下就已无着，③ 是耗尽了预算。两者都属「无 winner 的终局」。

        【2026-10-01】② 补了**重复判和**（`state["repeat_draw"]`）：
          不能只认 `self.drawn` —— 老存档恢复时 `self.drawn` 可能没带上，
          而 `repeat_draw` 是写在局面里的（会随存档一起回来）。
        """
        return (self.state["winner"] or self.drawn
                or GA.repeat_draw(self.state)
                or self.state["ply"] >= self.opts.get("max_ply", 120))

    # ------------------------------------------------------------ 可调参数
    # 手数上限做成网页可调（老师 2026-10-25）：
    #   评审想快速看完一局 → 48（每方 16 手）；想看复杂局面 → 240/300。
    #   改的是**内存里的 opts**，不写回 agents.json，也不写进存档
    #   （_save_payload 里没有 opts）⇒ 重启服务仍是文件里的默认值（120）。
    PLY_MIN, PLY_MAX = 24, 300

    def set_max_ply(self, n):
        """设置手数上限。返回 {"ok":bool, "max_ply":int} 或 {"ok":false,"error":...}"""
        try:
            n = int(n)
        except (TypeError, ValueError):
            return {"ok": False, "error": "手数上限必须是整数"}
        if not (self.PLY_MIN <= n <= self.PLY_MAX):
            return {"ok": False,
                    "error": f"手数上限需在 {self.PLY_MIN}–{self.PLY_MAX} 之间"}
        with self.lock:
            old = self.opts.get("max_ply", 120)
            self.opts["max_ply"] = n
            if n != old:
                over = (self.state["ply"] >= n and not self.state["winner"]
                        and not self.drawn)
                self.log.append({
                    "type": "pass",
                    "text": f"手数上限 {old} → {n}（每方 {n // 3} 手）"
                            + ("；本局已超过新上限，按当前排名结束" if over else "")})
        self._autosave()                  # 与其它配置项一致：改了立刻落盘
        return {"ok": True, "max_ply": n}


    def play(self):
        with self.lock:
            self.auto = True
        self._autosave()                  # auto 也存 ⇒ 重启后自动对弈状态一致

    def pause(self):
        with self.lock:
            self.auto = False
        self._autosave()

    def single_step(self):
        with self.lock:
            self.pending = True

    # ------------------------------------------------------------ 悔棋机制
    def set_undo(self, on, per_side=None):
        """网页勾选框：开/关悔棋。开的时候把各方机会重置满。

        【防呆】悔棋的自动触发条件是「走法被判失误/大漏」，那个判定由评分器给出。
        评分器默认关闭（grade_moves=false）→ 若此时勾上悔棋，按钮会亮、机会也扣得掉，
        但**自动悔棋永远不会发生**，且原本没有任何提示。这里补一条明确警告。
        """
        with self.lock:
            self.allow_undo = bool(on)
            if per_side:
                self.undo_per_side = max(0, int(per_side))
            if self.allow_undo:
                for k in (1, 2, 3):
                    self.undo_left[k] = self.undo_per_side
                    self.undo_used[k] = 0
            self.log.append({"type": "info",
                             "text": ("悔棋已开启：每方 %d 次机会"
                                      % self.undo_per_side) if self.allow_undo
                                     else "悔棋已关闭"})
            if self.allow_undo and self.grader is None:
                # ⚠️ 2026-10-01 文案订正：旧文写「自动悔棋不会生效」，容易被读成
                #   「悔棋坏了」。其实**人类手动悔棋完全不依赖评分器**，
                #   只有「Bot 走失误自动重走」才需要。改成如实说明，并降为 info。
                self.log.append({
                    "type": "info",
                    "text": f"悔棋已开启：每方 {self.undo_per_side} 次机会。"
                            "手动点「⤺ 悔棋」随时可用；"
                            "仅「Bot 走失误自动重走」需要评分器（grade_moves）。"})
            self._autosave()
            return {"ok": True, "allow_undo": self.allow_undo,
                    "per_side": self.undo_per_side, "left": dict(self.undo_left),
                    "grade_on": self.grade_on, "undo_effective": self.grader is not None}

    def _push_snapshot(self, army):
        """落子前存档：局面 + 全部随局面变化的统计量。

        存档里**不含 wrong[]**：那是"模型输出非法着法"的记录，属于模型行为，
        悔棋撤掉的是棋，不该把"模型确实违规过"这件事也抹掉。
        """
        self.snapshots.append({
            "state": GA.clone(self.state), "army": army, "log_len": len(self.log),
            "kills": dict(self.kills), "slain": dict(self.slain),
            "bad": dict(self.bad), "graded": dict(self.graded),
            "loss_sum": dict(self.loss_sum),
            # 【2026-10-02】终局自救悔棋用。`winner`/`eliminated`/`out`/`resigned`
            #   都在 `state` 里（随 `GA.clone` 一起回滚），但**判和标志 `drawn`
            #   是 Match 的进程内字段**，不存就回滚不掉 ⇒ 悔棋后悔了、立刻又终局。
            "drawn": bool(self.drawn),
            # 【2026-09-24 夜】回看缓冲的长度。悔棋回滚时按它截断，
            #   否则"回退一步"会退到一个**已经被撤回**的局面（与真实历史不符）。
            "replay_len": len(self.replay),
        })
        if len(self.snapshots) > 400:            # 防内存膨胀（一局不会有 400 手）
            self.snapshots = self.snapshots[-200:]

    # ------------------------------------------------------------ 悔棋
    def _rescue_army(self):
        """终局后「谁还能悔棋自救」—— 被斩方里最近出局、且还有机会的一方。

        【老师 2026-10-02】「虽然是游戏结束了，但是魏国还剩一次悔棋机会，
        应该允许魏国退回到将军之前」

        只有**主帅被斩**（进了 `state["eliminated"]`）才谈得上"退回将军之前"。
        判和 / 超时和棋没有受害者 ⇒ 返回 None（不给自救，否则等于取消终局）。

        ★ 只认 `eliminated` 的**最后一个**（＝最后被斩、也就是造成当前终局的那一方）：
          若顺次回退到更早出局的一方，会出现"魏被斩、机会用完了，玩家一点悔棋
          却让**更早出局的吴退 34 手**"这种荒唐结果（探针 §C 实测抓到的）。
          "退回将军之前"里的"将军"，指的只能是**当前这一手**。
          该方机会用完 / 快照链里已无它的棋 ⇒ 返回 None（老实拒绝）。
        """
        elim = list(self.state.get("eliminated") or [])
        if not elim:
            return None
        a = elim[-1]
        arms = {sn["army"] for sn in self.snapshots}
        if self.undo_left.get(a, 0) > 0 and a in arms:
            return a
        return None

    def _undo_plan(self, army=None):
        """算出「点一次悔棋」会撤到哪儿。返回 `(target, n, err)`。

        【老师 2026-10-01 口径】「当我魏国点悔棋的时候，其它方不算悔棋次数，
        但是其它方要退回一步，只有魏国算一次悔棋次数。否则不合理」

        三方棋回合顺序是 魏→吴→蜀→魏…，所以"轮到我走"时，最后落子的一方
        其实是**对手**。旧实现只撤最后一步 ⇒ 魏方点悔棋撤的是蜀方的棋、
        还白扣蜀方一次机会，与"悔棋"的直觉完全相反（且悔完仍轮不到自己重走）。

        新语义：撤到 `target` 方**自己上一次落子之前**为止 —— 连带把中间
        对手的那一两手一起退回（回到"轮 target 走、且 target 未落子"的时点），
        但**只扣 target 方一次**机会，被连带退回的方一次都不扣。
          · 魏刚走完就点悔棋   → n = 1（纯单步，与旧行为一致）
          · 轮到魏、蜀刚走完   → n = 3（蜀 + 吴 + 魏），回到魏上次落子前

        `army=None` → 自动推定目标方：优先「人类席位里最近落过子的一方」
        （＝人类按的按钮，撤自己的棋）；无人类席位（纯观战）时退回"最后落子方"。
        """
        if not self.snapshots:
            return None, 0, "没有可悔的棋"
        target = int(army) if army is not None else None
        # 【2026-10-02】终局推定目标方要**先认被斩方**：走默认的「人类席位里
        #   最近落子方」会撤到**刚斩帅的对手**，与"退回将军之前"语义完全相反。
        if target is None and self._finished():
            target = self._rescue_army()
        if target is None:
            hu = set(getattr(self, "human_armies", None) or ())
            for sn in reversed(self.snapshots):
                if sn["army"] in hu:
                    target = sn["army"]
                    break
            if target is None:                       # 观战档：撤最后一步
                target = self.snapshots[-1]["army"]
        n = 0
        for sn in reversed(self.snapshots):
            n += 1
            if sn["army"] == target:
                return target, n, None
        return target, 0, f"{GA.ARMY_CN[target]}方还没有可悔的棋"

    def undo_last(self, army=None, reason="悔棋"):
        """悔棋：回到目标方**上一次落子之前**，该方重走。返回结果给网页。

        口径见 `_undo_plan()`。要点：连带退回其他方的那一手，但只扣自己次数。
        """
        with self.lock:
            if not self.allow_undo:
                return {"ok": False, "error": "未开启悔棋（请先勾选）"}
            # 【2026-10-02 老师】「虽然是游戏结束了，但是魏国还剩一次悔棋机会，
            #   应该允许魏国退回到将军之前」
            #   ⇒ 终局后**不再一律拒绝**：只要"被斩方"还有剩余机会就放行，
            #     让它退回自己上次落子前（＝被将军之前）重走。
            #   ⚠️ 只认被斩方：判和 / 超时和棋时 `_rescue_army()` 返回 None，
            #     维持原判（否则"悔棋"就成了取消终局的万能钥匙）。
            if self._finished():
                if army is None:
                    army = self._rescue_army()
                try:
                    want = int(army)
                except (TypeError, ValueError):
                    want = 0
                # 终局自救的**准入三条**：① 是 1/2/3；② 在 `eliminated` 里
                #   （＝主帅真被斩，不是判和/超时）；③ 还剩机会。
                if (want not in (1, 2, 3)
                        or want not in (self.state.get("eliminated") or [])
                        or self.undo_left.get(want, 0) <= 0):
                    return {"ok": False, "error": "对局已结束"}
                army = want
                reason = "终局自救"
            target, n, err = self._undo_plan(army)
            if err:
                return {"ok": False, "error": err}
            if self.undo_left.get(target, 0) <= 0:
                return {"ok": False, "error": f"{GA.ARMY_CN[target]}方悔棋机会已用完"}

            # ---- 连续回滚到「target 方上次落子之前」----
            popped, snap = [], None
            while self.snapshots and n > 0:
                sn = self.snapshots.pop()
                popped.append(sn)
                n -= 1
                if sn["army"] == target:
                    snap = sn
                    break
            if snap is None:                         # 理论上到不了，防御性放回
                for sn in reversed(popped):
                    self.snapshots.append(sn)
                return {"ok": False, "error": f"{GA.ARMY_CN[target]}方还没有可悔的棋"}

            # ---- 回滚（用 target 那一手的存档 = 它落子前的状态）----
            s = self.state
            s.clear()
            s.update(GA.clone(snap["state"]))
            del self.log[snap["log_len"]:]
            # 【2026-09-24 夜】回看缓冲同步截断到"落子前"的长度。
            #   用存档里的 replay_len（而不是 s["ply"]）更稳：将来若有一类
            #   **不推 ply 却改盘面**的操作，这里也不会跟真实历史错位。
            self.replay = self.replay[:snap.get("replay_len", len(self.replay))]
            self.kills = dict(snap["kills"])
            self.slain = dict(snap["slain"])
            self.bad = dict(snap["bad"])
            self.graded = dict(snap["graded"])
            self.loss_sum = dict(snap["loss_sum"])
            # 【2026-10-02】判和标志回滚（state 里没有它，是 Match 进程内字段）。
            #   终局自救后悔棋 ⇒ `drawn` 必须跟着回到"落子前"的 False，
            #   否则 `_finished()` 仍为真、对局当场又结束。
            self.drawn = bool(snap.get("drawn", False))

            # ---- ★ 只扣 target 方一次；被连带退回的方一次都不扣 ----
            self.undo_left[target] -= 1
            self.undo_used[target] = self.undo_used.get(target, 0) + 1

            others = [GA.ARMY_CN[sn["army"]] for sn in popped if sn["army"] != target]
            if others:
                txt = (f"{GA.ARMY_CN[target]}方【{reason}】回到自己上次落子前："
                       f"退回 {len(popped)} 手（本方 1 手 ＋ "
                       f"{'、'.join(others)}各 1 手，后二者不消耗机会）；"
                       f"本方剩 {self.undo_left[target]} 次")
            else:
                txt = (f"{GA.ARMY_CN[target]}方【{reason}】撤回一步，"
                       f"剩 {self.undo_left[target]} 次机会")
            self.log.append({"type": "undo", "army": target, "ply": s["ply"],
                             "text": txt})
            self.auto = False                    # 手动悔棋后先停下，避免连悔
            self._autosave()                     # 悔棋也要落盘（否则续局会回到悔之前）
            return {"ok": True, "army": target, "left": dict(self.undo_left),
                    "rolled_back": len(popped), "others": others,
                    "turn": s["turn"]}

    # ------------------------------------------------------------ 单步
    def _decide(self, agent, s, legal, army, mode, alive_ok=None):
        """让某方走一步：模型出招 → 非法则兜底 → 失误则悔棋重走。

        返回 (res, mv, legal_list, used_fallback, grade, undos)
        """
        show_legal = (mode != "raw")
        show_hist = bool(self.opts.get("show_history", False))
        text = GA.render_text(s, legal, show_legal=show_legal, show_history=show_hist)
        res = agent.choose(s, legal, text, GA.ARMY_CN[army])
        mv = res.get("move")
        legal_set = {f"{a}-{b}" for a, b in legal}
        used_fallback = False
        if not mv or mv not in legal_set:
            # 「回退」＝ 模型输出了非法着法，由兜底 Bot 代走（这是缺陷，不是悔棋）
            used_fallback = True
            self.wrong[army] = self.wrong.get(army, 0) + 1
            fb = SearchBot(depth=1, time_limit=0.4,
                           seed=int(time.time() * 1000) % 99991)
            res = fb.choose(s, legal, text, GA.ARMY_CN[army])
            mv = res["move"]

        grade = None
        if self.grader is not None and not used_fallback:
            try:
                grade = arena.grade_move(s, legal, mv, self.grader,
                                         plies=self.grade_plies)
            except Exception:
                grade = None

        # ---- 悔棋重走：合法但很臭（失误/大漏）→ 消耗一次机会换一步 ----
        # 最多重走 1 次：把原着法从候选剔除，否则模型极可能原样再走一遍 → 死循环。
        undos = 0
        while (self.allow_undo and grade and not used_fallback and undos < 1
               and grade["label"] in LABEL_BAD and self.undo_left.get(army, 0) > 0):
            self.undo_left[army] -= 1
            self.undo_used[army] = self.undo_used.get(army, 0) + 1
            undos += 1
            self.log.append({
                "type": "undo", "army": army, "ply": s["ply"],
                "text": f"{GA.ARMY_CN[army]}方【悔棋】{mv} 被判「"
                        f"{arena.LABEL_CN[grade['label']]}」，重走"
                        f"（剩 {self.undo_left[army]} 次）"})
            alt = [m for m in legal if f"{m[0]}-{m[1]}" != mv] or legal
            res = agent.choose(s, alt,
                               GA.render_text(s, alt, show_legal=show_legal,
                                              show_history=show_hist),
                               GA.ARMY_CN[army])
            mv2 = res.get("move")
            if mv2 and mv2 in {f"{a}-{b}" for a, b in alt}:
                mv, legal = mv2, alt
            try:
                grade = arena.grade_move(s, legal, mv, self.grader,
                                         plies=self.grade_plies)
            except Exception:
                grade = None
        return res, mv, legal, used_fallback, grade, undos

    def step(self):
        s = self.state
        ep = self.epoch                 # 本轮思考属于哪一个「世代」（见下方校验）
        army = s["turn"]
        # 双保险：轮到「人类接管」的方，Bot 绝不代走（即使 _loop 漏了判断）
        if army in self.human_armies:
            return
        # 残局判平（老师 2026-09-24）：
        #   「场上车马炮兵都没有了，谁也将不死谁，留下的都是象、士，
        #     9 次轮盘之后多方帅都不照面 → 自动判定场上剩下的各方平局」
        if GA.stalemate_draw(s):
            self.drawn = True
            self.log.append({
                "type": "draw", "ply": s["ply"],
                "text": f"残局判平：在局各方只剩象/士，"
                        f"{GA.STALEMATE_ROUNDS} 轮内谁也将不死谁 → 判定剩下各方平局"})
            return
        legal = GA.legal_moves(s, army)
        # 【2026-09-25 删】原《一、10》「帅被动见面」的**自动判负**与"本回合只能
        #   阻隔/移开己方帅"的提示，在这里整段退役。
        #   老师 2026-09-25 定夺的新规则：照见即可射杀（帅/副帅沿见面线直接吃对方帅），
        #   照面从"违规禁忌"变成"互为人质" ⇒ `GA.pending_judge()` 恒为 None，
        #   判负失去全部触发条件。留此注释是为了让后来者知道这里曾有什么、为何没了。
        if not legal:
            GA._advance(s)
            legal = GA.legal_moves(s, s["turn"])
            self.log.append({"type": "pass", "army": army,
                             "text": f"{GA.ARMY_CN[army]}方无合法着法（停走一次）"})
            if not legal:
                # 三方都无合法着法 → 判和，并**置终止标志**（否则 _loop 会无限重入）
                self.drawn = True
                self.log.append({"type": "draw", "text": "三方均无法取胜，判和"})
                return
        army = s["turn"]
        agent = self.agents.get(army)
        # 赛制：choice=给棋盘+全部合法着法（测纯决策质量）/ raw=只给棋盘（测规则内化）
        mode = self.opts.get("arena_mode", "choice")
        if self.allow_undo:
            self._push_snapshot(army)
        with self.lock:
            self.thinking = army
        tok0 = (agent.stats.get("ptokens", 0), agent.stats.get("ctokens", 0))
        t0 = time.time()
        res, mv, legal, used_fallback, grade, undos = \
            self._decide(agent, s, legal, army, mode)
        dt = time.time() - t0
        tok1 = (agent.stats.get("ptokens", 0), agent.stats.get("ctokens", 0))
        # ★ 世代号校验（2026-09-25 · 长考档的必备保护）
        #   高档位单步要 45~120 秒，老师等不及点「重开一局」是常态。
        #   reset() 会把 self.state 换成**新对象**，而本轮的 `s` 还指着旧对象 ⇒
        #   若照旧往下走：`GA.apply(s, ...)` 落在旧对象上（棋盘无害），但
        #   `credit_kill()` 会改**全局**战绩、`self.log.append()` 会往**新局**
        #   战报里塞一条幽灵着法、`self.graded/loss_sum` 同被污染。
        #   ⇒ 世代号一变，这一整手（含统计与战报）全部丢弃。
        if ep != self.epoch:
            with self.lock:
                self.thinking = None
            return
        if grade:
            self.graded[army] = self.graded.get(army, 0) + 1
            self.loss_sum[army] = self.loss_sum.get(army, 0.0) + grade["loss_norm"]
            if grade["label"] in LABEL_BAD:
                self.bad[army] = self.bad.get(army, 0) + 1
        a, b = mv.split("-")
        victim = s["board"].get(b)
        if victim and victim["army"] != army:
            credit_kill(self, army, victim)
        note = GA.apply(s, a, b)
        with self.lock:
            self.thinking = None
        self.log.append(move_log_entry(
            army, a, b, s["ply"], note,
            reason=res.get("reason", ""), latency=round(dt, 2),
            fallback=used_fallback,
            model=self.meta.get(army, {}).get("label", ""),
            # 失误谱 + 预算（每步 token 增量）
            grade=grade["label"] if grade else None,
            loss=grade["loss"] if grade else None,
            best_move=grade["best_move"] if grade else None,
            undos=undos,
            ptok=tok1[0] - tok0[0], ctok=tok1[1] - tok0[1],
        ))
        # 【2026-10-01】重复着法落判（老师报"反复走同一路径 → 死循环"）。
        #   必须**紧跟落子之后**立刻判定：判和后对局就结束了，不能等到下一次
        #   step() 才发现 —— 三方棋很容易"轮到人类玩家就一直没人动"，
        #   那样这个判和会永远不生效（`self.drawn` 只用在下一次的 `_finished()`）。
        self._note_repeat_verdict(s, note)
        # 【2026-09-24 夜】给回看缓冲存一份"这一手走完"的局面
        self._record_replay()
        self._autosave()          # ★ 每手落子即落盘 ⇒ 关窗口/断电都不丢棋

    # ------------------------------------------------------------ 手动接管
    def manual_move(self, frm, to):
        """人类接管：直接走一步当前回合方的棋

        【2026-09-25】原伪着法 `judge-<方>`（《一、10》方案①「把 B 判负」）
        已随该条款退役，现在只会收到一条解释性错误（见下方分支）。
        """
        with self.lock:
            s = self.state
            if self._finished():
                return {"ok": False, "error": "对局已结束"}
            army = s["turn"]
            # 【2026-09-24 夜加 · 与前端 app.js 的 onPick 守卫**逐字对齐**】
            #   前端只允许两种情形替「当前回合方」落子：
            #     ① 该方已被勾选「人类接管」（`step()` 里的双保险也不会代走它）；
            #     ② 对局处于**暂停**状态（Bot 谁都不走，允许人类临时介入）。
            #   而后端此前**完全不校验** —— 理论上只要有任何请求打到 /api/move，
            #   就能以「人类接管」的名义替**任意**当前回合方走一步，日志里便出现
            #   "我没点过，却有人替我走了"的着法，且无从分辨。
            #   老师 2026-09-24 报「魏国的士凭空消失」时，ply10（士 E6→D5）正是
            #   这种标着「人类接管」的着法。回放证明它是页面点击产生的**合法**着法
            #   （全程 0 步非法），但"前端拦、后端不拦"终究是漏洞 ——
            #   前端是体验，后端才是防线。此处补齐，判断条件与前端完全一致。
            if self.auto and army not in self.human_armies:
                return {
                    "ok": False,
                    "error": (f"现在是{GA.ARMY_CN[army]}方回合，由 Bot 自动走 "
                              f"—— 未勾选「人类接管 {GA.ARMY_CN[army]}」时不能替它落子"
                              f"（想自己下：勾上 {GA.ARMY_CN[army]}，或先按「⏸ 暂停对弈」）")}
            if frm == "judge":
                # 【2026-09-25 退役】伪着法 `judge-<方>` 原用于《一、10》「把 B 判负」。
                #   新规则（照见即可射杀）下照面不再违规 ⇒ 判负无从触发。
                #   保留这个分支，只为给旧请求（或未刷新的页面）一个**明确解释**，
                #   而不是一句莫名的"不是合法着法"。
                return {"ok": False,
                        "error": "《一、10》判负机制已于 2026-09-25 退役 —— "
                                 "照面不再违规，改为「照见即可射杀」：帅/副帅沿见面线"
                                 "可直接吃掉对方帅。请刷新页面（Ctrl+F5）后重试"}
            legal = {f"{a}-{b}" for a, b in GA.legal_moves(s, s["turn"])}
            mv = f"{frm}-{to}"
            if mv not in legal:
                return {"ok": False, "error": f"{mv} 不是合法着法"}
            if self.allow_undo:
                self._push_snapshot(army)
            victim = s["board"].get(to)
            if victim and victim["army"] != army:
                credit_kill(self, army, victim)
            note = GA.apply(s, frm, to)
            self.log.append(move_log_entry(
                army, frm, to, s["ply"], note,
                reason="人类接管", latency=0, fallback=False, model="人类"))
            self._note_repeat_verdict(s, note)     # 同上：人类走子也要判重复
            # 【2026-09-24 夜】人类走子同样进回看缓冲
            self._record_replay()
            self._autosave()          # ★ 你落的每一手都立刻落盘
            return {"ok": True}

    def resign(self, army=None):
        """认输：某方主动放弃行棋资格（老师 2026-09-24：不存在求和，只允许认输）

        · army 省略时默认当前回合方；
        · 语义与《一、10》判负同类（帅留盘、棋子不易主），**不等于出局**；
        · 三方局里非当前回合方也允许认输。
        """
        with self.lock:
            s = self.state
            if self._finished():
                return {"ok": False, "error": "对局已结束"}
            try:
                army = int(army) if army else s["turn"]
            except (TypeError, ValueError):
                return {"ok": False, "error": "army 必须是 1/2/3"}
            if army not in (1, 2, 3):
                return {"ok": False, "error": "army 必须是 1/2/3"}
            if army in s.get("out", []):
                return {"ok": False,
                        "error": f"{GA.ARMY_CN[army]}方已失去行棋资格，无需认输"}
            GA.resign(s, army)
            self.log.append({
                "type": "resign", "army": army, "ply": s["ply"], "reason": "认输",
                "text": f"{GA.ARMY_CN[army]}方 认输"})
            self._autosave()
            return {"ok": True, "army": army}

    def takeover(self, army):
        """人类接管：把**行棋权**交给指定的一方（魏/吴/蜀都行）

        老师 2026-09-24：「人类接管当前回合 这按钮随时按下后，
          玩家可以选择三方任一方接着下。」

        实现方式很直接：把 `turn` 改成指定方 + 清空本回合步数计数。
        这样后续一切（前端的合法着法高亮、`/api/move`、`_advance` 的轮转）
        都自然按新的行棋方工作，不必给每个接口都加一个 army 参数。
        """
        with self.lock:
            s = self.state
            if self._finished():
                return {"ok": False, "error": "对局已结束"}
            try:
                army = int(army)
            except (TypeError, ValueError):
                return {"ok": False, "error": "army 必须是 1/2/3"}
            if army not in (1, 2, 3):
                return {"ok": False, "error": "army 必须是 1/2/3"}
            if army in s.get("out", []):
                return {"ok": False,
                        "error": f"{GA.ARMY_CN[army]}方已失去行棋资格，不能接管"}
            old = s["turn"]
            s["turn"] = army
            s["turn_steps"] = 0
            self._autosave()          # 接管后的轮次也要跨重启保留
            return {"ok": True, "army": army, "from": old}

    # ------------------------------------------------------------ 快照
    def snapshot(self):
        with self.lock:
            s = self.state
            st = GA.status(s)
            # Python 整数键经 JSON 往返会变成字符串键，这里统一转好，
            # 免得前端（或其它语言）读 annexed 时踩坑。
            st["annexed"] = {str(k): v for k, v in st["annexed"].items()}
            # 下一次悔棋的"落点"（老师 2026-10-01）：目标方 + 连带退回手数。
            #   纯只读（_undo_plan 不加锁），放在这里是为了让前端能如实提示
            #   「这一下会撤谁、退几步」，而不是笼统写"撤回最后一步"。
            _uw = self._undo_plan()
            fin = bool(self._finished())
            # 【2026-10-02】终局后可自救方（0 = 无）。前端据此在"终局"时
            #   仍放行悔棋按钮（老师：「游戏结束了，但魏国还剩一次悔棋机会」）。
            #   ⚠️ **只在终局时才算**：对局进行中 `eliminated` 里可能还留着
            #     早先出局的方，若照输出，前端会误以为"随时可自救"。
            rescue = (self._rescue_army() or 0) if fin else 0
            legal = [f"{a}-{b}" for a, b in GA.legal_moves(s, s["turn"])] \
                if not fin else []
            agents = {}
            for k, ag in self.agents.items():
                la = ag.stats.get("latency") or []
                calls = ag.stats.get("calls", 0)
                agents[str(k)] = {
                    "label": self.meta[k]["label"], "model": self.meta[k]["model"],
                    "url": self.meta[k]["url"], "has_key": self.meta[k]["has_key"],
                    "local": ag.__class__.__name__ in ("LocalBot", "SearchBot"),
                    "offline": bool(getattr(ag, "offline", False)),
                    "last_error": getattr(ag, "last_error", "")[:120],
                    "calls": calls,
                    "retries": ag.stats.get("retries", 0),
                    "netfail": ag.stats.get("netfail", 0),
                    "avg_latency": round(sum(la) / len(la), 2) if la else 0,
                    "ptokens": ag.stats.get("ptokens", 0),
                    "ctokens": ag.stats.get("ctokens", 0),
                    # 合法率：回退次数 / 请求次数 —— 评测的第一指标
                    "illegal": ag.stats.get("fallbacks", 0),
                    "legal_rate": round(1 - ag.stats.get("fallbacks", 0) / calls, 4)
                                  if calls else None,
                    # ★「实际搜到几 plies」—— 老师 2026-09-25 要求加更多高档位，
                    #   但高档位在预算内可能搜不满（如选 12 plies 实际只搜到 9）。
                    #   这里把 SearchBot.last_info 的真实深度透出去，网页**如实显示**，
                    #   避免「档位数字」与「实际算到多深」不一致带来的误导。
                    "last_plies": (ag.last_info or {}).get("plies")
                                  if hasattr(ag, "last_info") else None,
                    "last_nodes": (ag.last_info or {}).get("nodes")
                                  if hasattr(ag, "last_info") else None,
                }
            sc = score(s, self.kills, self.slain, self.wrong)
            ranks, order = rank_of(sc, s)
            return {
                "pieces": [{"pos": p, **v} for p, v in s["board"].items()],
                "status": st,
                "material": material(s),
                "scores": {str(k): v for k, v in sc.items()},
                "ranks": {str(k): v for k, v in ranks.items()},
                "order": order,
                "kills": {str(k): round(v, 1) for k, v in self.kills.items()},
                "slain": {str(k): v for k, v in self.slain.items()},
                "wrong": {str(k): v for k, v in self.wrong.items()},
                # ---- 失误谱（Arena 评分器汇总）----
                "grades": {str(k): {
                    "graded": self.graded[k],
                    "bad": self.bad[k],
                    "loss_avg": round(self.loss_sum[k] / self.graded[k], 4)
                                if self.graded[k] else None,
                } for k in (1, 2, 3)},
                "grade_on": self.grade_on,
                "grade_plies": self.grade_plies,
                "grade_exact": self.grade_exact,
                "arena_mode": self.opts.get("arena_mode", "choice"),
                # ---- 悔棋状态 ----
                "allow_undo": self.allow_undo,
                "undo_per_side": self.undo_per_side,
                "undo_left": {str(k): v for k, v in self.undo_left.items()},
                "undo_used": {str(k): v for k, v in self.undo_used.items()},
                "can_undo": bool(self.allow_undo and self.snapshots
                                 and (not fin or rescue)),
                # 终局自救（老师 2026-10-02）：被斩方还剩机会时可"退回将军之前"。
                #   0 = 没有可自救方 ⇒ 前端照旧禁用悔棋按钮。
                "undo_rescue": rescue,
                # 下一次点悔棋会撤到哪儿（老师 2026-10-01 口径）：
                #   undo_who = 目标方（人类席位里最近落子的一方）；undo_rollback = 连带退回的手数。
                #   前端据此把按钮提示写成「撤回自己上次落子（连带对手各退 1 手）」。
                "undo_who": _uw[0], "undo_rollback": _uw[1],
                # ---- 续局存档状态（老师 2026-10-01）----
                #   restored = 本进程启动时是否续上了上一局（前端据此弹提示）
                "autosave": bool(self.autosave_path),
                "saved_at": self.saved_at,
                "restored": self.restored_from is not None,
                "restored_from": self.restored_from,
                "save_error": self.save_error,
                # ---- 《一.5》连吃上限 ----
                "chain_limit": self.chain_limit,
                "chain": {str(k): v for k, v in (s.get("chain") or {}).items()},
                # ---- 《一、3》回合与步数 ----
                "steps_per_turn": self.steps_per_turn,
                "turn_steps": int(s.get("turn_steps") or 0),
                # ---- 人类接管（哪几方由人走，其余 Bot 自动）----
                "human_armies": sorted(self.human_armies),
                # ---- Bot 难度档（老师 2026-09-25）----
                #   difficulty        = 当前档 1..4
                #   difficulty_meta   = 当前档的说明（名称 / plies / 预计耗时）
                #   difficulty_levels = 四档全表（前端据此画按钮，增档不用改前端）
                "difficulty": self.difficulty,
                "difficulty_meta": DIFF.describe(self.difficulty),
                "difficulty_levels": DIFF.all_levels(),
                # 哪些方是真实大模型（不受难度档影响）—— 前端要如实提示，
                # 否则老师「切了难度却没变化」会以为是 bug。
                "difficulty_skipped": [cfg.get("army") or k
                                       for k, cfg in self.roster["players"].items()
                                       if not DIFF.is_local(cfg)],
                # ---- 每方主控：本地Bot / API 大模型（老师 2026-10-02）----
                #   seats[k]      = 老师**选的选项 id**（`__search__` / `deepseek-v4-flash` / `hy4`）
                #   seat_options  = 下拉目录（含 ready/why；未配置的 API 条目前端置灰）
                #   ⚠️ 读缓存，不做磁盘 I/O（/api/state 每 ~800ms 被轮询）
                "seats": {str(k): v for k, v in self.seats.items()},
                "seat_options": self._seat_ui,
                # 三方**实际搜到的深度**（plies）：档位是"目标"，这才是"实到"。
                # 例：选「宗师 12 plies」，纯 Python 内核下可能只到 9 plies。
                "actual_plies": {str(k): ((getattr(ag, "last_info", None) or {})
                                          .get("plies"))
                                 for k, ag in self.agents.items()},
                "agents": agents,
                "log": self.log[-80:],
                "legal": legal,
                "auto": self.auto,
                "thinking": self.thinking,
                "elapsed": round(time.time() - self.started, 1),
                "finished": fin,
                "drawn": bool(self.drawn),
                "max_ply": self.opts.get("max_ply", 120),
                # ---- 回看（只读）----
                #   供前端「⏪ 回退一步」知道最多能退多少手。
                #   老师 2026-09-24 夜：「点击一次回退一个，可以一直往前回退，
                #   弄个按钮继续下，这样我就知道 bot 走哪里了」。
                "replay_total": max(0, len(self.replay) - 1),
            }


if __name__ == "__main__":
    import sys
    m = Match(auto=True)
    print("三方对弈开始（Ctrl+C 结束）\n")
    last = 0
    while not m._finished():
        time.sleep(1.2)
        if len(m.log) != last:
            for e in m.log[last:]:
                if e["type"] == "move":
                    print(f"  #{e['ply']:>3} {GA.ARMY_CN[e['army']]}方 {e['from']}-{e['to']:<8}"
                          f" {e['latency']:>5.1f}s  {e.get('reason','')[:26]}"
                          + (f"  吃{e['captured']}" if e.get("captured") else "")
                          + ("  [回退]" if e["fallback"] else ""))
                else:
                    print("  *", e["text"])
            last = len(m.log)
    print("\n结束。战绩：", json.dumps(m.snapshot()["kills"], ensure_ascii=False))
