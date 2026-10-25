# -*- coding: utf-8 -*-
"""三人象棋 · 搜索 Bot（paranoid minimax + alpha-beta 剪枝 + 宽度限制）

【为什么用 paranoid —— 三人棋的搜索难题】
    二人象棋是零和博弈，"最优策略"定义清晰，minimax 直接可用。
    但三人棋**不是零和**：不能简单地说"最大化我的收益 = 最小化对手收益"，
    严格解法要用 Max-n 搜索（每个节点存一个三方分数向量），剪枝困难、极慢。

    paranoid 的做法最简单、也最贴合实战：**把另外两方都当成敌人**。
    因为规则上任何一方吃掉我的帅我都立刻出局，
    所以"两个对手都在想办法弄死我"不是保守假设，而是对局面的忠实近似。

    于是博弈重新变回零和：
        轮到我   → max 节点（最大化"我"的分数）
        轮到对手 → min 节点（最小化"我"的分数，两方一视同仁）
    alpha-beta 剪枝可以直接用。

【三重加速（Python 里必须做，否则 6 plies 要跑几十秒）】
    ① make/unmake：搜索里不做引擎级的"出局/收编"重逻辑，只移动子（O(1)）
    ② alive 集合随 make 增量维护，取代每次 O(40) 遍历找主帅
    ③ 宽度限制：非根节点只保留启发式最优的前 K 个着法
       （根节点不限宽 —— 保证不会漏掉任何合法着法）

【AlphaZero 的"无为"体现在哪】
    本文件只提供**搜索框架**（怎么想），不提供**棋理**（想什么）。
    评估函数的权重由 selfplay.py 靠自我对弈进化出来（weights.json），
    全程只告诉它"这局谁赢了"，不告诉它"什么是好棋"。
"""
import json
import os
import random
import threading
import time

import numpy as np               # 仅用于给 JIT 内核准备宽度表/工作区（见 _choose_jit）

try:
    from ..engine import game_dxf as GA
    from ..engine import geometry_dxf as G
    from ..engine import rules_dxf as R
    from . import eval_dxf as E
except ImportError:                      # 以 server/ 为工作目录时走这条
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from engine import game_dxf as GA
    from engine import geometry_dxf as G
    from engine import rules_dxf as R
    import eval_dxf as E

# ------------------------------------------------------------------ numba 内核
# 方案 ①（2026-09-25 落地）：把「表构建 + 着法生成 + 叶评估 + 搜索」整体编译成
# 机器码，实测 nps 3~4 万 → **43 万**，同层数提速 **12~22 倍**（见
# tests/_verify_nb_search.py：plies=6 的 26 个「局面·方」全部
# **根着法集合一致 26/26、最大分数偏差 0.00e+00**）。
#
# 门禁（老师定的规矩：新内核必须与现有 Python 引擎随机局面对拍）：
#   tests/_verify_numba_parity.py  OK=3514 FAIL=0   （着法/攻击表/编码/叶评估/专项）
#   tests/_verify_nb_search.py     OK=156  FAIL=0   （分数逐位一致 + 根着法集合一致）
#   tests/_verify_leaf_order.py    OK=81   FAIL=0   （_leaf 遍历顺序定死的回归）
#
# 关闭方式：环境变量 `CHESS_NO_JIT=1`，或 `SearchBot(..., use_jit=False)`。
_JIT = None
_JIT_WARMED = [False]
_JIT_LOCK = threading.Lock()
# ★【2026-09-26】搜索**串行锁**：JIT 内核用的是 `nb_core._SEARCHSCR` 这块
#   **模块级全局工作区**（着法缓冲 / 历史表 / 杀手表 / 输出区全部共享）。
#   两个线程同时搜索会互相覆盖对方的工作区 ⇒ 结果错乱甚至越界。
#   当前实际路径是串行的（`Match.step()` 单线程驱动三方），但服务用的是
#   `ThreadingHTTPServer`，将来一旦有人并发调 `choose()`（例如同时给三方
#   评分、或多请求触发）就会踩上 —— 这里加锁把它变成"排队"，代价为零。
_JIT_SEARCH_LOCK = threading.Lock()
if not os.environ.get("CHESS_NO_JIT"):
    try:
        try:
            from ..engine import nb_core as _JIT
        except ImportError:
            from engine import nb_core as _JIT
    except Exception:                        # numba 没装/版本不符 → 静默降级
        _JIT = None


def _jit_warmup():
    """预热 JIT（全模块去 cache 后每次进程启动要编译 ~15s；服务启动时调一次）

    ⚠️ **必须加锁 + 双检**（2026-09-26）：服务启动时是**后台线程**在预热，
    而老师若在预热完成前就点「自动对弈」，主线程 `_choose` 也会同步调到这里 ——
    两个线程**同时编译同一批 numba 函数**。numba 的编译与 dispatcher 初始化
    **不是线程安全的**，并发编译可能崩进程（本机实测过 numba 相关的 SEGV）。
    加锁后只有一个线程真正编译，另一个等它完成后直接返回。
    """
    if _JIT is None or _JIT_WARMED[0]:
        return
    with _JIT_LOCK:
        if _JIT is None or _JIT_WARMED[0]:       # 双检：等锁期间可能已被别人做完
            return
        try:
            _JIT.warmup()
            _JIT.warmup_search()
            _JIT_WARMED[0] = True
        except Exception:
            pass

VALUE = R.VALUE
GENERAL = R.GENERAL
WEIGHTS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "weights.json")

INF = 1e9
# 零窗口（PVS）宽度。**必须远小于 INF 的量级**，否则 alpha + EPS 在浮点里
# 会被舍入回 alpha，窗口宽度变成 0、搜索直接判剪枝，结果全错 —— 这是把
# INF 从 1e18 降到 1e9 的原因：1e9 在 double 里还留着 1e-7 的分辨率。
EPS = 1e-3

# 各深度层的着法宽度上限（越深越窄 —— 深层的垃圾着法不值得展开）
WIDTH = {1: 14, 2: 10, 3: 8, 4: 6, 5: 5, 6: 4}

# 静态搜索（quiescence）默认最大额外吃子层数。0 = 关闭（退回纯固定深度）。
# 见 `SearchBot._qsearch` 的完整说明。
#
# 【为什么是 2 而不是更大 —— 2026-09-26 实测定的】
#   `_verify_qsearch_parity.py` 的节点计数（plies=5，20 个「局面·方」合计）：
#       qs=0 →   842,007   （1.0×，基准）
#       qs=2 → 3,882,606   （4.6×）
#       qs=4 → 16,756,928  （19.9×）
#   而**收益是递减的**：plies=3 时 qs=2 与 qs=4 改变估值的局面数**一样**（17/20）；
#   plies=5 时只从 15/20 涨到 17/20。也就是说"最贵的那两层吃子"几乎不改结论。
#   深档本来就在抢深度（档5/6 的预算是 60/120 s），qs 每 +2 就是 ×4 节点 ⇒
#   qs=4 会让档4（9 plies）从 ~8 s 涨到 ~34 s、档5 直接开不进 12 plies。
#   ⇒ 取**性价比拐点 qs=2**：把最主要的两层"吃-反吃"修掉，代价只要 4.6×。
#   （三方棋吃子机会比国际象棋多，吃子链不易自然收敛 —— 这也是必须设上限的原因。）
QS_DEFAULT = 2

# 静态搜索的**硬上限**，与 `nb_core.QS_CAP` 必须一致。
# ⚠️ 为什么 Python 侧也要截断：JIT 的 `search_plies(qs=)` 内部会 clip 到 QS_CAP，
#    若 Python 侧不截，用户在 agents.json 里填 `qs_depth=100` 时两边行为不同
#    （一个搜 100 层、一个搜 32 层）⇒ 对拍/一致性全乱。
QS_CAP = int(getattr(_JIT, "QS_CAP", 32))

# 根节点渐进加宽（PVS 思路）：先用全宽做浅搜，深搜只展开浅搜选出的前几名。
# 40 个根着法全展开深搜要几百万节点；砍到 14 名后能快 3 倍以上。
ROOT_KEEP = {3: 99, 6: 14, 9: 8, 12: 5}


def width_for(plies):
    return WIDTH.get(plies, 4)


def load_weights():
    """加载自我对弈进化出来的权重；没有就用手工起点"""
    try:
        with open(WEIGHTS_FILE, encoding="utf-8") as f:
            d = json.load(f)
        w = dict(E.DEFAULT_W)
        w.update({k: float(v) for k, v in d.get("weights", {}).items() if k in w})
        return w
    except Exception:
        return dict(E.DEFAULT_W)


class _Timeout(Exception):
    pass


class SearchBot:
    """带 2~3 层预判的本地 Bot（不调用任何网络）"""

    kind = "search"

    def __init__(self, depth=2, time_limit=1.6, seed=None, weights=None,
                 label="搜索Bot（minimax）", width=None, noise=0.5,
                 use_jit=None, qs_depth=None):
        self.depth_layers = int(depth)          # 1 层 = 三方各走一步 = 3 plies
        self.time_limit = float(time_limit)     # 单步时间上限（秒）
        self.width = dict(width) if width else dict(WIDTH)
        self.noise = float(noise)       # 根节点探索噪声幅度
        self.rng = random.Random(seed)
        self.offline = False
        self.w = weights or load_weights()
        self.label = label
        # ---- 静态搜索（方案 ②，2026-09-26 落地）----
        #   >0：plies 用尽后继续只搜"吃子"，直到盘面安静或吃满 `qs_depth` 层
        #    0：关闭，退回纯固定深度（方案②之前的旧行为）
        #   见 `_qsearch` 的完整说明；JIT 侧对应 `nb_core.search_plies(qs=...)`。
        #   ⚠️ 必须 clip 到 QS_CAP（与 JIT 的 `search_plies` 同口径），否则
        #      传超大值（如 100）时两边搜的层数不同。
        qs = QS_DEFAULT if qs_depth is None else int(qs_depth)
        self.qs_depth = max(0, min(qs, QS_CAP))
        # ---- numba 内核开关（方案 ①）----
        #   None = 自动（装了 numba 就用）；True/False = 强制
        self.use_jit = (_JIT is not None) if use_jit is None else bool(use_jit)
        if self.use_jit and _JIT is None:
            self.use_jit = False            # 强制开但内核不可用 → 退回纯 Python
        #   JIT 的宽度表要当**数组参数**传（模块级全局数组会被 numba 常量折叠）
        self._width_arr = np.zeros(_JIT.MAX_PLY + 1, dtype=np.int32) if _JIT else None
        if _JIT:
            for _p in range(_JIT.MAX_PLY + 1):
                self._width_arr[_p] = int(self.width.get(_p, 5))
        self.stats = {"calls": 0, "ptokens": 0, "ctokens": 0, "latency": [],
                      "fallbacks": 0, "retries": 0, "netfail": 0}
        self.nodes = 0
        self.last_info = {}
        self._hist = {}                 # 历史启发表：曾引发剪枝的着法加分
        self._killers = {}              # 杀手着法：plies -> [着法1, 着法2]
        # rank_root 是否用全窗口（真值）打分。True 尺子准但慢约 2 倍；
        # 只做「谁更好」的排序时设 False 即可。
        self.rank_exact = True
        self._ply = 0                   # 当前对局手数（供"进攻压力"用）
        self._ur = 1.0                  # 进攻压力系数（随手数上升）

    # ------------------------------------------------------------ 对外接口
    def choose(self, state, legal, text="", army_name=""):
        t0 = time.time()
        res = self._choose(state, legal, text, army_name)
        dt = round((time.time() - t0) * 1000, 3)
        self.stats["latency"].append(dt)
        if isinstance(res, dict):
            res["latency"] = dt
        return res

    def _choose(self, state, legal, text="", army_name=""):
        self.stats["calls"] += 1
        if not legal:
            return {"move": None, "reason": "无合法着法", "ok": False, "raw": "",
                    "latency": 0.0, "usage": {}}

        # ---- 方案 ①：有 numba 内核就走 JIT ----
        #   与纯 Python 的 `_choose` 逐位一致（tests/_verify_nb_search.py: 偏差 0.00e+00），
        #   同层数快 12~22 倍。任何意外都**退回纯 Python**，不让内核问题阻断对局。
        if self.use_jit:
            try:
                _jit_warmup()
                return self._choose_jit(state, legal, army_name)
            except Exception:
                self.use_jit = False
                self.stats["fallbacks"] = self.stats.get("fallbacks", 0) + 1

        me = state["turn"]
        dist = E.distances()
        self._deadline = time.time() + self.time_limit
        self.nodes = 0
        self._hist = {}
        self._killers = {}
        self._ply = int(state.get("ply", 0) or 0)
        # 进攻压力：对局越往后越急（否则三方对称博弈必然僵持到天荒地老）
        self._ur = 1.0 + self._ply * self.w.get("urgency", 0.0)

        root = list(legal)
        # ★ 复制一份棋盘再搜。搜索的 make/unmake 只保证「内容」还原，
        #   但 dict 的**插入顺序**会被 pop/回填永久打乱，
        #   而 _leaf 里浮点求和、以及着法生成都是按 dict 顺序遍历的 ——
        #   顺序一变，末位浮点就差 ~1e-13，足以翻转 alpha-beta 的相等比较，
        #   于是「同一个局面连搜两次」会得到不同结果（实测节点数 611551 → 454366）。
        #   复制之后调用方的局面对象毫发无伤，搜索结果也就完全可复现了。
        board = dict(state["board"])
        alive = frozenset(self._gen_alive(board))
        best_move, best_score = root[0], -INF
        reached = 0
        cand = root                              # 本轮的候选根着法

        # 迭代加深：从浅到深，超时就停在上一层（保证永远有答案）
        #
        # ★ 时间预算预判：先估「这一层大概要花多久」，不够就干脆别开。
        #   否则会出现这种情况 —— 预算 5s、6 plies 只花 0.3s，
        #   然后 9 plies 跑到一半被超时打断，**整层结果全部作废**，
        #   最后还是拿 6 plies 的答案，白白烧掉 4.7s（实测如此）。
        #   外推比例用实测的「层间节点放大倍数」，比写死常数靠谱。
        times = []                              # 每层的 (节点数, 秒数)
        for plies in range(3, self.depth_layers * 3 + 1, 3):
            if times:
                n_last, t_last = times[-1]
                if len(times) > 1:
                    # 实测层间节点放大倍数**波动极大**（同一台机器上 6→9 实测
                    # 8.2 ~ 27.7 倍，取决于局面分支数），所以这里取**保守上界 20.0**：
                    #   宁可不开深一层，也不要「开了却做不完」白烧整个预算
                    #   （实测：中局 6 plies 0.67s，9 plies 18.6s ⇒ 白烧 8s 且结果照旧）。
                    # 只有某一层跑得**特别快**时，才会去够下一层。
                    ratio = min(n_last / max(times[-2][0], 1), 20.0)
                else:
                    ratio = 30.0            # 只有一层数据时用实测常数
                # ★【2026-09-25 修】旧写法是 `上次耗时 × (节点比 × 2.0) × 1.2`，
                #   「×2.0」本意是补偿「放大倍数自身还在增长」，但它把预测**系统性高估
                #   约 2.5 倍**（实测 6 plies 后预测 134s，真实只要 ~54s）——
                #   后果是 depth=3 的 9 plies 层**永远开不起来**（给 30s 预算也只搜到 6 plies）。
                #   改用**实测 nps 换算**：nps 在整局里近乎常数，比「耗时×常数」稳得多。
                nps = n_last / max(t_last, 1e-6)
                est = n_last * ratio / max(nps, 1.0)
                # 留 15% 余量：外推本身有波动，不留余量会卡在边界「开了却做不完」。
                if time.time() + est * 1.15 > self._deadline:
                    break
            keep = ROOT_KEEP.get(plies, 6)
            t_it = time.time()
            n0 = self.nodes
            try:
                mv, sc, ranked = self._root_search(board, cand, alive,
                                                   plies, me, dist)
                if mv is not None:
                    best_move, best_score = mv, sc
                    reached = plies
                    # 渐进加宽：深搜只展开浅搜排名靠前的着法
                    cand = [x[1] for x in ranked[:keep]]
            except _Timeout:
                break
            times.append((self.nodes - n0, time.time() - t_it))
            if time.time() > self._deadline:
                break

        self.last_info = {"plies": reached, "score": round(best_score, 2),
                          "nodes": self.nodes, "cands": len(cand)}
        return {"move": f"{best_move[0]}-{best_move[1]}",
                "reason": f"搜索{reached}步(上限{self.depth_layers}层) 估值{best_score:+.1f}",
                "ok": True, "raw": "", "latency": 0.0, "usage": {}}

    # ------------------------------------------------------------ numba 内核版
    def _choose_jit(self, state, legal, army_name=""):
        """与 `_choose` **同结构、同口径**的 JIT 版（方案 ①）

        逐字对应关系（对拍脚本 `tests/_verify_nb_search.py` 守这条）：
            · 迭代加深：3 → 6 → 9 …，每层前的**时间外推**逻辑与 `_choose` 完全一样
            · 历史/杀手表：**每手棋清一次**（第一次调用 `reset=True`，后续 False）
              —— 与 `_choose` 里 `self._hist = {}` / `self._killers = {}` 同义
            · 根着法：必须是**引擎过滤后的合法着法**（`legal`），
              搜索树内部才用伪合法着法（否则会生成"送帅"自毁着法）
            · 根节点渐进加宽：`ROOT_KEEP`，与 `_choose` 同一张表
            · exact=False（选着法）：根着法用 (alpha, INF) 窗口，与 Python 版一致
            · noise：根节点探索噪声（打破三方镜像平局），JIT 侧用 numpy RNG
              —— 与 Python 版的 `self.rng` **不是同一路随机流**，
                 但都是同一分布的探索噪声，不影响"选出的棋"的合理性
        """
        me = state["turn"]
        self._deadline = time.time() + self.time_limit
        self.nodes = 0
        self._ply = int(state.get("ply", 0) or 0)
        self._ur = 1.0 + self._ply * self.w.get("urgency", 0.0)

        root = list(legal)
        cand = root
        best_move, best_score = root[0], -INF
        reached = 0
        times = []
        first = True

        for plies in range(3, self.depth_layers * 3 + 1, 3):
            if times:
                n_last, t_last = times[-1]
                if len(times) > 1:
                    ratio = min(n_last / max(times[-2][0], 1), 20.0)
                else:
                    ratio = 30.0
                nps = n_last / max(t_last, 1e-6)
                est = n_last * ratio / max(nps, 1.0)
                if time.time() + est * 1.15 > self._deadline:
                    break
            keep = ROOT_KEEP.get(plies, 6)
            remain = self._deadline - time.time()
            if remain <= 0:
                break
            t_it = time.time()
            mv, sc, ranked, nodes, aborted = self._jit_search(
                state["board"], me, plies, cand, remain, first)
            first = False
            # ★【2026-09-26 修】`search_root` 开头会 `CTX[0]=0; CTX[1]=0` ——
            #   所以 JIT 返回的 `nodes` 是**本层节点数（每层重置）**，
            #   而 Python 的 `_root_search` 是**累计**（只在 `_choose` 开头清一次）。
            #   旧写法 `self.nodes = nodes` 会把累计值覆盖成本层值 ⇒
            #   `nodes - n0` 变负 ⇒ 时间外推的 ratio 被 `max(...,1)` 兜底钳成 20，
            #   「该不该开更深一层」的判断失准；打印的节点数也与 Python 版口径不符。
            #   统一成累计：本层增量就是 `nodes` 自身。
            self.nodes += nodes
            if aborted or mv is None:
                break
            best_move, best_score = mv, sc
            reached = plies
            cand = [(f, t) for f, t, _s in ranked[:keep]]   # 渐进加宽
            times.append((nodes, time.time() - t_it))       # 本层增量（非累计）
            if time.time() > self._deadline:
                break

        self.last_info = {"plies": reached, "score": round(best_score, 2),
                          "nodes": self.nodes, "cands": len(cand), "jit": True}
        return {"move": f"{best_move[0]}-{best_move[1]}",
                "reason": f"搜索{reached}步(上限{self.depth_layers}层·JIT) 估值{best_score:+.1f}",
                "ok": True, "raw": "", "latency": 0.0, "usage": {}}

    def _jit_search(self, board, me, plies, cand, remain, reset):
        """调 JIT 内核搜一层 —— **串行化**入口（内核工作区是模块级全局，不可并发）

        口径与 `_choose` 的 `_root_search` 一致：`exact=False`（选着法用 PVS 窗口）、
        `noise=self.noise`（根节点探索噪声）、`qs=self.qs_depth`（静态搜索层数）。
        加锁理由见 `_JIT_SEARCH_LOCK` 的注释。
        """
        with _JIT_SEARCH_LOCK:
            return _JIT.search_plies(
                board, me, plies, self.w, cand,
                ply_no=self._ply, time_limit=remain, exact=False,
                reset=reset, width=self._width_arr, noise=self.noise,
                qs=self.qs_depth)

    def rank_root(self, state, legal, plies=3, top=0):
        """给根节点**全部**合法着法打分，返回 [(着法, 分数)] 按分数降序。

        这是"失误谱"的基础设施：把某一步实走着法丢进同一个榜单比一比，
        就知道它离最优着法差多远（best_score - played_score = cp_loss）。
        有了它才谈得上给每一步打 best/excellent/inaccuracy/mistake/blunder 标签——
        这比"谁赢了"稳定得多：一局分不出胜负（三人棋极易长期僵持），
        但每一步的质量分布天天都能测。

        plies 必须是 3 的倍数：三方各走一步才算"一层预判"。
        根节点**不设宽度**（_root_search 走全宽），保证榜单不漏任何合法着法。
        """
        me = state["turn"]
        dist = E.distances()
        self._deadline = time.time() + max(self.time_limit * 4, 3.0)
        self.nodes = 0
        self._hist = {}
        self._killers = {}
        self._ply = int(state.get("ply", 0) or 0)
        self._ur = 1.0 + self._ply * self.w.get("urgency", 0.0)
        alive = frozenset(self._gen_alive(state["board"]))
        board = dict(state["board"])             # 同上：不污染调用方的局面对象
        _, _, ranked = self._root_search(board, list(legal), alive,
                                         plies, me, dist, exact=self.rank_exact)
        out = [(f"{f}-{t}", sc) for sc, (f, t) in ranked]
        return out[:top] if top else out

    # ------------------------------------------------------------ 根搜索
    def _root_search(self, board, root, alive, plies, me, dist, exact=False):
        """返回 (最佳着法, 分数, 全部候选按分数降序的排名)

        exact=False（默认，选着法用）：根着法依次用窗口 (alpha, +INF) 搜，
            alpha 是"目前最好"。**没超过 alpha 的着法返回的是上界、不是精确值** ——
            剪枝省时间，但那些分数不能当绝对值用。
        exact=True（当尺子用）：每个根着法都用全窗口 (-INF, +INF)，
            分数是精确值，代价是慢一些。

        为什么必须区分：失误谱算的是 loss = best - played。
        用上界去算，没超过最优的着法会被**系统性地高估损失**（实测偏差 1.7 分），
        于是所有"次优着法"都被判得更差，失误率虚高。
        尺子必须准 —— 所以 rank_root() 走 exact=True。
        """
        moves = self._order(board, root, me, plies)
        alpha = -INF
        best_move, best_score = None, -INF
        ranked = []
        for frm, to in moves:
            self.nodes += 1
            undo = self._make(board, frm, to)
            nxt = alive - {undo["home"]} if _is_general(undo) else alive
            try:
                sc = self._search(board, self._next(alive, me), nxt, plies - 1,
                                  -INF if exact else alpha, INF, me, dist)
            finally:
                self._unmake(board, frm, to, undo)
            ranked.append((sc, (frm, to)))
            # 探索噪声：三方完全镜像对称的局面会永远平局（谁都走镜像着法、
            # 谁都无法占优）。加一点噪声让某一方先"走岔"，局面才会分出高下。
            # 这也是 AlphaZero 用 Dirichlet 噪声做探索的同一层意思。
            sc_sel = sc + self.rng.random() * self.noise
            if sc_sel > best_score:
                best_score, best_move = sc_sel, (frm, to)
            if sc > alpha:
                alpha = sc
            if time.time() > self._deadline:
                raise _Timeout()
        ranked.sort(key=lambda x: -x[0])
        return best_move, best_score, ranked

    # ------------------------------------------------------------ 核心搜索
    def _search(self, board, turn, alive, plies, alpha, beta, me, dist):
        self.nodes += 1
        if not (self.nodes & 1023) and time.time() > self._deadline:
            raise _Timeout()

        if plies <= 0:
            # ---- 方案 ② 静态搜索：固定深度用尽后不立即停，继续只搜吃子 ----
            #   `qs_depth == 0` 时退回旧行为（直接叶评估）。
            if self.qs_depth > 0:
                return self._qsearch(board, turn, alive, alpha, beta, me, dist,
                                     self.qs_depth)
            return self._leaf(board, me, dist)

        moves = []
        ap = moves.append
        for pos, pc in board.items():
            if pc["army"] != turn:
                continue
            for q in R.moves_of(board, pos, pc):        # 跳过 pseudo_moves 的包装层
                ap((pos, q))

        if not moves:
            return self._search(board, self._next(alive, turn), alive, plies - 1,
                                alpha, beta, me, dist)

        # 宽度限制：深层的垃圾着法不值得展开（根节点不限）
        lim = self.width.get(plies, 5)
        ordered = self._order(board, moves, turn, plies)
        if len(ordered) > lim:
            ordered = ordered[:lim]

        nxt_turn = self._next(alive, turn)
        kill = self._killers

        if turn == me:                              # ---- max 节点
            best = -INF
            first = True
            for frm, to in ordered:
                undo = self._make(board, frm, to)
                nxt = alive - {undo["home"]} if _is_general(undo) else alive
                try:
                    if first:
                        v = self._search(board, nxt_turn, nxt, plies - 1,
                                         alpha, beta, me, dist)
                        first = False
                    else:
                        # ★PVS（主变例搜索）：先用零窗口试探「这步棋能不能
                        #   超过已知最好」。绝大多数着法在这里就被否掉，一行
                        #   都不用重搜；只有真的更好的才展开完整窗口复算。
                        #   位置评分几乎不变，节点数能省掉两三成。
                        v = self._search(board, nxt_turn, nxt, plies - 1,
                                         alpha, alpha + EPS, me, dist)
                        if alpha < v < beta:
                            v = self._search(board, nxt_turn, nxt, plies - 1,
                                             v, beta, me, dist)
                finally:
                    self._unmake(board, frm, to, undo)
                if v > best:
                    best = v
                if v > alpha:
                    alpha = v
                if alpha >= beta:
                    self._hist[(frm, to)] = min(self._hist.get((frm, to), 0.0) + plies * plies, 90000.0)
                    # 杀手着法：**在这一层**引发剪枝的安静好棋（不是吃子，
                    # 吃子已由排序覆盖）。它捕捉的是"当前局面"的信息，
                    # 比历史表的全局统计更贴身，下一层遇到先试它。
                    if to not in board:
                        k = kill.get(plies)
                        if k is None:
                            kill[plies] = [(frm, to)]
                        elif (frm, to) not in k:
                            k.insert(0, (frm, to))
                            del k[2:]
                    break
            return best

        best = INF
        first = True
        for frm, to in ordered:
            undo = self._make(board, frm, to)
            nxt = alive - {undo["home"]} if _is_general(undo) else alive
            try:
                if first:
                    v = self._search(board, nxt_turn, nxt, plies - 1,
                                     alpha, beta, me, dist)
                    first = False
                else:
                    v = self._search(board, nxt_turn, nxt, plies - 1,
                                     beta - EPS, beta, me, dist)
                    if alpha < v < beta:
                        v = self._search(board, nxt_turn, nxt, plies - 1,
                                         alpha, v, me, dist)
            finally:
                self._unmake(board, frm, to, undo)
            if v < best:
                best = v
            if v < beta:
                beta = v
            if alpha >= beta:
                self._hist[(frm, to)] = min(self._hist.get((frm, to), 0.0) + plies * plies, 90000.0)
                if to not in board:
                    k = kill.get(plies)
                    if k is None:
                        kill[plies] = [(frm, to)]
                    elif (frm, to) not in k:
                        k.insert(0, (frm, to))
                        del k[2:]
                break
        return best

    # ------------------------------------------------------------ 静态搜索
    def _qsearch(self, board, turn, alive, alpha, beta, me, dist, qs):
        """静态搜索 / 静止搜索（quiescence）—— 方案 ②，消除「水平线效应」

        【要解决的问题】
            固定深度搜索的最后一步如果是「我吃了对方一个大子」，评估只看结果盘面
            ⇒ 看起来我白赚；但对手下一步能**反吃回来**，真实分数要低得多。
            这就是水平线效应：估值在搜索边界处**系统性高估"吃子"**，
            于是 bot 爱做"一步吃、被反吃"的亏本买卖（开局尤其明显：
            两个大子互吃、分数虚高、着法看起来激进其实是送）。
            解法（Knuth & Moore 1975 的经典手法）：plies 用尽后**不要立即停**，
            继续只展开「吃子」着法，直到盘面安静（谁都没得吃）或吃满 `qs` 层。

        【结构 —— 与 `_search` 逐字同构，只把"全部着法"换成"吃子着法"】
            · **stand-pat**：不动手的分数就是 `_leaf()`
                - max 节点：不动是"至少能拿到 stand"⇒ `stand >= beta` 直接返回
                - min 节点：不动是"对手至少能让我掉到 stand"⇒ `stand <= alpha` 直接返回
                （吃子**不是义务**，可以不吃 —— 这正是静态搜索与"强制延伸"的区别）
            · 吃子着法 = `to in board` 的伪合法着法（`rules_dxf._can_land` 已保证
              不会走到己子上，所以"目标有子"等价于"吃敌子"）
            · 一个吃子都没有 → 安静节点，直接返回 stand-pat
            · 排序**复用 `_order`**：吃子档位（吃帅 1e9 / 吃子 1e6+子力×100）
              与 `_search` 完全同一套，且 `_order` 内部同分按 mv 降序
              ⇒ 与输入顺序无关 ⇒ 与 JIT 的 `_order` 逐位可对拍
              （⚠️ 不要在这里另写 MVV-LVA —— 口径一分岔，两边剪枝路径就不同）

        【qs 用尽 / 循环风险】
            吃子链长度有上限（每吃一次盘上子力总数 -1），但仍设 `qs_depth` 硬上限，
            防止极端局面下递归过深。`qs_depth = 0` 时 `_search` 根本不进这里。

        【剪枝口径】
            与 `_search` 一致用 (alpha, beta) 全窗口直接递归 —— 静态搜索里
            吃子着法本来就少，再做 PVS 零窗口复算反而多一层开销。JIT 侧同口径。
        """
        self.nodes += 1
        if not (self.nodes & 1023) and time.time() > self._deadline:
            raise _Timeout()

        if qs <= 0:
            return self._leaf(board, me, dist)

        stand = self._leaf(board, me, dist)

        caps = []
        ap = caps.append
        for pos, pc in board.items():
            if pc["army"] != turn:
                continue
            for q in R.moves_of(board, pos, pc):
                if q in board:                          # 目标有子 = 吃子
                    ap((pos, q))
        if not caps:
            return stand
        caps = self._order(board, caps, turn, 0)

        nxt_turn = self._next(alive, turn)

        if turn == me:                                  # ---- max 节点
            best = stand
            if best >= beta:
                return best
            if best > alpha:
                alpha = best
            for frm, to in caps:
                undo = self._make(board, frm, to)
                nxt = alive - {undo["home"]} if _is_general(undo) else alive
                try:
                    v = self._qsearch(board, nxt_turn, nxt, alpha, beta, me,
                                      dist, qs - 1)
                finally:
                    self._unmake(board, frm, to, undo)
                if v > best:
                    best = v
                if v > alpha:
                    alpha = v
                if alpha >= beta:
                    break
            return best

        best = stand                                    # ---- min 节点
        if best <= alpha:
            return best
        if best < beta:
            beta = best
        for frm, to in caps:
            undo = self._make(board, frm, to)
            nxt = alive - {undo["home"]} if _is_general(undo) else alive
            try:
                v = self._qsearch(board, nxt_turn, nxt, alpha, beta, me,
                                  dist, qs - 1)
            finally:
                self._unmake(board, frm, to, undo)
            if v < best:
                best = v
            if v < beta:
                beta = v
            if alpha >= beta:
                break
        return best

    # ------------------------------------------------------------ 叶节点评估
    def _leaf(self, board, me, dist):
        """叶节点评估（内联版：单遍收集 + 单遍求和，省掉函数调用开销）

        这是全搜索最热的地方 —— 每次搜索要调用几万次，
        所以这里不追求可读性，只追求少几次 dict 查找。
        公式与 eval_dxf.evaluate 一致（威胁 / 危险 / 子力 / 副帅 / 斩帅）。

        ⚠️⚠️【2026-09-25 定案】**必须按点位排序遍历**（`sorted(board.items())`），
        不能直接 `board.items()`。原因（JIT 对拍挖出来的真问题）：

          · 本函数是**浮点连加**，加法顺序不同 → 末位差 ~1e-13。
          · `board` 是 dict，它的迭代顺序 = **插入顺序**，而 `_make/_unmake`
            每次吃子/悔子都会 `pop` + 重新插入 ⇒ **同一局面可以有不同的
            字典顺序**，取决于"怎么走到这里的"。于是评估值**不可复现**。
          · 平时这 1e-13 无所谓；但棋盘是 **120° 旋转对称**的（开局尤甚），
            大量着法的叶值**精确相等**，这 1e-13 就足以翻转
            `alpha >= beta` / `v > best` 这类**等值比较** ⇒ 剪枝路径分岔
            ⇒ 历史/杀手表分岔 ⇒ 宽度截断截掉的着法不同 ⇒ 结果差得看得见。
            实测：开局 plies=6，Python=19.246582 / JIT 内核=14.396582（Δ=4.85）；
                  把本函数改成排序遍历后，两边**逐位一致（偏差 0.000e+00）**。

          · 排序顺序（3 位数字串的字典序）正好等于**点位序号顺序**
            `range(N)`，与 `engine/nb_core.py` 的 `leaf` 完全一致。
          · 代价：每次叶评估多一次 `sorted`（~48 个元素）。换来的是
            **结果与吃子历史无关**、两边逐位可比 —— 这买卖划算。

        回归测试：`tests/_verify_leaf_order.py`（打乱字典顺序 → 结果必须不变）。
        """
        w = self.w
        gens = {}
        by_army = {}
        mat = {}
        deputies = 0
        for pos, pc in sorted(board.items()):        # ★ 顺序必须定死，见上文
            a = pc["army"]
            k = pc["kind"]
            if k == GENERAL:
                if pc.get("deputy"):
                    if pc["home"] == me:
                        deputies += 1
                else:
                    gens[pc["home"]] = pos
                continue
            by_army.setdefault(a, []).append((pos, k))
            mat[a] = mat.get(a, 0.0) + VALUE[k]

        my_gen = gens.get(me)
        if my_gen is None:
            return -1e6

        mine = by_army.get(me, [])
        dgr = w["danger"]
        maxd = E.MAX_DIST
        ur = self._ur                                  # 进攻压力（随手数上升）
        wprs = ur * w["pressure"]
        sc = 0.0

        # 我对各敌帅的进攻压强（Σ 子力价值 × 逼近量）
        # 用"求和"而非"取最近一颗"：否则一个孤兵冲到河界就拿满分，
        # Bot 会只派一个兵顶上去、其余子在家看戏，永远打不起来。
        c1 = ur * w.get("close1", 0.0)
        c2 = ur * w.get("close2", 0.0)
        wchk = ur * w.get("check", 0.0)
        sv = E._SQRT_VALUE
        for enemy, gpos in gens.items():
            if enemy == me:
                continue
            dmap = dist[gpos]
            # 将军判定用的反向索引（wchk=0 时整块跳过，方便做 A/B 对照）
            atk = R.ATK_BY.get(gpos) if wchk else None
            chk = False
            for pos, k in mine:
                d = dmap[pos]
                sc += wprs * sv[k] * (maxd - d)    # sqrt 加权（见 eval_dxf 说明）
                if d <= 1:
                    sc += c1                       # 贴到敌帅 1 步之内
                elif d == 2:
                    sc += c2                       # 一步之遥
                # 将军：**就着这一轮已经遍历到的子**顺手判掉，不另开一遍扫描。
                # 旧实现是「挑出距敌帅 4 步以内的子、逐个生成全部着法、看打不打得着」，
                # 既慢又有真实盲区：车/炮远距离同线将军时图距 > 4 会被整条漏掉，
                # 而"将军"正是三人棋里唯一能强制对手应对、打破僵持的机制（权重 120）。
                if atk is not None and not chk:
                    specs = atk.get(pos)
                    if specs is not None:
                        pc = board[pos]
                        for kind, extra in specs:
                            if kind == k and R._hit(board, pos, pc, kind, extra, gpos):
                                chk = True
                                break
            if chk:
                sc += wchk

        # 各敌对我帅的压强（负分，不带 urgency）
        dmap = dist[my_gen]
        for enemy in gens:
            if enemy == me:
                continue
            for pos, k in by_army.get(enemy, []):
                sc -= dgr * VALUE[k] * (maxd - dmap[pos])

        # 对手主帅已被斩 → 该方出局，我离"只剩一方"更近一步
        for a in (1, 2, 3):
            if a != me and a not in gens:
                sc += 4000.0

        # 子力：只与最强的对手比（三人棋里最强者才是最终对手）
        my_mat = mat.get(me, 0.0)
        top = 0.0
        for enemy in gens:
            if enemy != me:
                m = mat.get(enemy, 0.0)
                if m > top:
                    top = m
        sc += w["material"] * (my_mat - top)
        sc += w["deputy"] * deputies
        return sc

    # ------------------------------------------------------------ 工具
    @staticmethod
    def _make(board, frm, to):
        """走一步（轻量 make：只动物子；引擎里那些"出局/收编"重逻辑搜索用不起）"""
        pc = board.pop(frm)
        vic = board.pop(to, None)
        board[to] = pc
        return vic

    @staticmethod
    def _unmake(board, frm, to, vic):
        """撤销一步：移动的子送回原位，被吃的子还原"""
        board[frm] = board.pop(to)
        if vic is not None:
            board[to] = vic

    @staticmethod
    def _gen_alive(board):
        """盘上还有主帅的方"""
        out = set()
        for pc in board.values():
            if pc["kind"] == GENERAL and not pc.get("deputy"):
                out.add(pc["home"])
        return out

    @staticmethod
    def _next(alive, turn):
        """按 1→2→3→1 推进，跳过主帅已不在盘上的方"""
        a = turn
        for _ in range(3):
            a = a % 3 + 1
            if a in alive:
                return a
        return a

    def _order(self, board, moves, viewer, plies=0):
        """着法排序 —— alpha-beta 剪枝率的最大杠杆。

        优先级（数值尺度刻意拉开，保证互不串档）：
            吃敌方主帅  1e9
            其它吃子    1e6 + 子力价值×100     （最大 1e6+1000）
            杀手着法1   5e5 + 历史分           （历史分已封顶 9e4 → ≤ 5.9e5）
            杀手着法2   4e5 + 历史分
            安静着法    历史分                 （≤ 9e4）

        为什么历史分要封顶：否则长时间搜索后某个安静着法的历史分会膨胀到
        超过吃子档，把"吃过路兵"这种着法排到"吃车"前面，剪枝率反而下降。

        历史启发看的是「这类着法以前好不好用」（全局统计）；
        杀手着法看的是「**在这一层**什么着法刚引发过剪枝」（局部信息）。
        两者互补：前者在开局就有效，后者在进入固定战术模式后更准。
        """
        hist = self._hist
        k = self._killers.get(plies)
        k1 = k[0] if k else None
        k2 = k[1] if k and len(k) > 1 else None
        out = []
        ap = out.append
        for mv in moves:
            vic = board.get(mv[1])
            if vic is None:
                h = hist.get(mv, 0.0)
                if mv == k1:
                    ap((500000.0 + h, mv))
                elif mv == k2:
                    ap((400000.0 + h, mv))
                else:
                    ap((h, mv))
            elif vic["kind"] == GENERAL:
                ap((1e9, mv))
            elif vic["army"] == viewer:
                ap((-1e5, mv))                  # 送自己的子：最差
            else:
                ap((1e6 + VALUE[vic["kind"]] * 100.0, mv))
        out.sort(reverse=True)
        return [m for _s, m in out]


def _is_general(vic):
    return vic is not None and vic["kind"] == GENERAL and not vic.get("deputy")


# ---------------------------------------------------------------- 自检
if __name__ == "__main__":
    import sys
    sys.path.insert(0, ".")
    from engine import game_dxf as GA2

    A = {1: "魏", 2: "吴", 3: "蜀"}
    s = GA2.new_game()
    for layers in (1, 2, 3):
        bot = SearchBot(depth=layers, time_limit=8.0, seed=1)
        legal = GA2.legal_moves(s, 1)
        t0 = time.time()
        r = bot.choose(s, legal, "", "魏")
        dt = time.time() - t0
        i = bot.last_info
        print(f"  {layers} 层: 实到 {i['plies']} plies  {dt:5.2f}s  "
              f"{i['nodes']:>7d} 节点  {i['nodes']/max(dt,1e-6):>7.0f} 节点/秒  "
              f"{r['move']}  {r['reason']}")
