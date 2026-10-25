# -*- coding: utf-8 -*-
"""三人象棋 · 专利版对局状态机（DXF 几何版）

与旧 game.py 的区别：几何与走法全部换成 `geometry_dxf` / `rules_dxf`
（以老师的 DXF 工程图为权威坐标），专利版机制（副帅 / 军帐 / 生命力 / 战斗力 / 易主）不变。
"""
import copy

from . import geometry_dxf as G
from . import patent as P
from . import rules_dxf as R

B = G.BOARD
TURN_ORDER = [1, 2, 3]
KIND_CN = R.KIND_CN
ARMY_CN = G.ARMY_CN


def new_game(first=1):
    """开局。first 指定起手方（1魏/2蜀/3吴）。

    【为什么起手方要可指定】三人棋三个位置在几何上等价，但"谁先动"这件事
    并不对称：先动的一方会先暴露意图、也先进入另两方的视野。
    做棋力评测时若固定魏方起手，胜率差异会被系统性归因给"起手优势"而不是"棋力"。
    Arena 采用**起手方轮换**（魏起手/蜀起手/吴起手各跑一遍），
    把起手优劣摊平掉 —— 与二人棋评测里"双色轮换"是同一个道理。
    """
    s = {"board": {}, "turn": int(first), "eliminated": [], "annexed": {},
         "history": [], "passed": [], "winner": None, "ply": 0, "first": int(first)}
    s.update(P.new_fields())
    for it in G.initial_position():
        s["board"][it["pos"]] = {
            "kind": it["kind"], "army": it["army"], "home": it["army"]}
    return s


def clone(s):
    return copy.deepcopy(s)


def general_pos(s, army):
    for pos, p in s["board"].items():
        if p["kind"] == R.GENERAL and p["home"] == army and not p.get("deputy"):
            return pos
    return None


def alive_armies(s):
    """还在局中（有行棋资格）的方。

    【2026-09-24 修 · 按老师口径区分「出局」与「判负」】
      老师原话：「某一方'出局'的触发条件就是主帅被吃，变成副帅。」
      → **出局**（`eliminated`）只有一条途径：主帅被吃。
      → 《一、10》的**判负**是另一种"失去资格"：帅仍在盘上、棋子一本不易主
        （《一、6》：另两方不能控制、但可以吃，直到这枚帅被吃才归吃帅方）。
        它同样不能再走棋，所以也必须排除在"在局方"之外。

    旧写法按 `eliminated` 判定 → 被判负的一方仍算"在局"，还会被轮到走棋。
    故统一以 `out`（= 失去行棋资格，出局 ∪ 判负）为准；
    `eliminated` 退化为纯展示字段（谁是真·被斩主帅）。
    """
    out_of = set(s.get("out") or ())
    return [k for k in TURN_ORDER if k not in out_of]


def check_map(s, frozen=frozenset()):
    out = {}
    for k in alive_armies(s):
        gp = general_pos(s, k)
        if gp is None:
            continue
        atk = {a for a in alive_armies(s) if a != k
               and R.attacked(s, gp, {a}, frozen)}
        if atk:
            out[k] = atk
    return out


def frozen_now(s):
    cm = check_map(s)
    if not cm:
        return set()
    involved = set(cm) | {a for v in cm.values() for a in v}
    return set(alive_armies(s)) - involved


# ---------------------------------------------------------------- 帅见面 / 被动见面
def facing_pairs(s, strict=False):
    """互相见面的【主帅】对（副帅不参与，见 docs §9.2）。

    【2026-09-25 语义更新 · 射杀规则上线后】
      本函数**统计事实**的部分不变（谁和谁共线、中间有无子，是客观盘面）；
      但"见面"的**后果**被改了：
        · 旧：《一、9》禁止照面 → 造成照面即违规，被动方可按《一、10》判对方负；
        · 新：**照见即可射杀** → 见面 = 互为人质，**轮到谁，谁能吃**
          （见 `rules_dxf.snipe_targets`）。

      随之退役的是 `strict=True` 的「豁免对剔除」（原《一、9》豁免 2：
      "在局方帅可与出局方帅见面"）—— 新规则下这种照面**同样能互相射杀**
      （老师原话问的正是"魏国控制的副帅照见 I5 主帅，为何不能射杀"）。

    `strict` 形参**保留只为兼容既有调用方**，两个取值现在返回相同结果。
    若哪天要彻底清理，可把形参连同调用处的 `strict=True` 一起删掉。
    """
    res = []
    for p, q in R.generals_facing(s):
        res.append(frozenset((p, q)))
    return res


def pending_judge(s, army=None):
    """【已退役 · 2026-09-25】《一、10 帅被动见面》的"待决"状态 —— **恒为 None**

    退役前的原文（《一、10》）：
        「A 帅和 B 帅同在上述（标题 8）任一条仅有 C 棋阻隔的线路上，C 棋抽离，
          致使 A 帅、B 帅见面。此时 A 必须二选一：直接把 B 判负…；
          或用自己的棋阻隔在两帅之间、或移开己方的帅，不把 B 判负。（走棋顺序：C⇒A）」

    【为什么整个退役】老师 2026-09-25 定夺的新规则把"照面"从**违规禁忌**改成了
      **互为人质**：照见即可射杀，轮到谁谁能吃。既然照面不再违规，
      就不存在"A 被迫二选一"的待决局面 —— 判负机制失去全部触发条件。

    保留函数名与签名，是因为 `match.py` / `status()` / 若干测试仍按旧接口引用；
    语义已中性化（永远"不待决"），不会再影响任何走法、轮转或胜负判定。
    """
    return None


def snipe_pairs(s):
    """盘上全部「射杀」关系对 (攻击方点位, 被射杀的帅/副帅点位)。

    【2026-09-25 新增 · 随射杀规则】
    与 `facing_pairs` 的两点区别：
      · **含副帅** —— 新规则下副帅同样有射杀能力，也可能被射杀；
      · **不过滤豁免** —— "在局方帅 ↔ 出局方帅"照见同样致命。

    用途：
      · `stalemate_draw` 第 ③ 条 —— 只要还存在射杀关系，棋就没下完，不判平；
      · 前端提示（哪些帅正互相瞄准）。
    """
    out = []
    board = s["board"]
    for pos, pc in board.items():
        if pc["kind"] != R.GENERAL:
            continue
        for q in R.snipe_targets(board, pos, pc["army"]):
            out.append((pos, q))
    return out


def protected_out_generals(s):
    """规则《一、9》第 3 条：「在局方 A 帅与出局方 B 帅相见时，C 不可吃 B 的帅」。

    返回 {出局方帅的点位: 允许吃它的在局方集合}（集合为空 = **谁都不得吃**）。

    【2026-09-25 老师定夺 · ★独占口径★】
      上一版（同日）用的是"列表口径"：**所有**与 B 的帅照见的在局方都放行。
      老师否掉了它，理由是——第 3 条的立法本意是「**C 不得趁机捡走别人家的副帅**」，
      而新规则（照见即可射杀）之下"能射杀" ⟺ "照见"，两者是**同一个条件**
      ⇒ 列表口径 = 白名单 == 全部能射杀的人 ⇒ 第 3 条在射杀面前形同虚设。

      老师给的例子（三点同列5，三方两两全照见）：
        · 若按列表口径 → 魏和蜀**都能**吃掉那枚出局方帅（等于没保护）
        · 老师要求 → **都不能吃**

      现口径：**只有【独占照见】的那一方有资格吃**
        · `len(partners) == 1` → 那一方放行（真正的 A，无人与它争）
        · `len(partners) >= 2` → **谁都不得吃**（多方争抢 → 谁也不准捡便宜）
        · `len(partners) == 0` → **第 3 条前提不成立**（无人与它照见 ⇒ 没有 A、也无从谈 C）
          ⇒ 不拦，按普通吃子处理

    与射杀的关系：射杀也是 `(frm, to)` 着法，`to` 就是这枚帅的点位，
      所以**同样受本表管辖** —— 独占不成立时，帅的射杀也会被拦掉 ✓
      （这正是老师要的"射杀也让路"。）

    为什么 `frozenset()` 能表达"谁都不得吃"：调用方 `legal_moves` 写的是
      `allowed = guard.get(to); if allowed is not None and army not in allowed: continue`
      —— 空集 ⇒ 任何 army 都不在其中 ⇒ 该着法一律剔除 ✓
    """
    if not s.get("out"):
        return {}
    guard = {}
    for pg, p in s["board"].items():
        if p["kind"] != R.GENERAL or p["home"] not in s["out"]:
            continue
        partners = set()
        for k in alive_armies(s):
            gp = general_pos(s, k)
            if gp and gp != pg and R.line_of_sight(s, gp, pg):
                partners.add(k)
        if not partners:
            continue                    # 前提不成立 → 第 3 条不适用
        if len(partners) == 1:
            guard[pg] = frozenset(partners)     # 独占照见 → 那一方放行
        else:
            guard[pg] = frozenset()             # 多方争抢 → 谁都不得吃
    return guard


def legal_moves(s, army=None, frozen=None, skip_repeat=False):
    """某方的全部合法着法 (from, to)。

    【2026-10-02 老师裁决 · 重复着法改「事前拦截」】
      带 `repeat_blocked` 过滤：**会构成超限重复的那一手根本不出现**。
      `skip_repeat=True` 只给两处用：① `repeat_stuck()` 判断"是不是除重复外无路可走"；
      ② 探针/门禁做"过滤前后对照"。**业务路径一律用默认值。**

    【2026-09-25 大改 · 随「射杀」规则废除照面禁令】
      删掉了两道**旧《一、9》/《一、10》的过滤**（它们现在不但无意义，还很贵）：
        · 「不可把己方帅放到与对手帅共线且无阻隔的线路上」→ 照面不再是违规；
        · 「处于被动见面待决时，只能走阻隔/移开己方帅的棋」→ 待决状态已退役。
      连带删掉的还有每次试走都要做的 `clone(state)` + `_move_piece` ——
      本函数在搜索热路径上被调用极频繁，这一删省掉的是"每生成一步就深拷贝一次整个局面"。

      ⚠️ 仍**保留**《一、9》第 3 条：第三方不得趁别方照面时白捡**出局方的帅**
        （见 `protected_out_generals`）。它限制的是"吃子"，不是"照面"，
        且与射杀不冲突 —— 能射杀出局方帅的前提就是自己与它照见，那时本就在白名单里。

      专利版一贯口径不变：三方对战**允许己方送将 / 不应将**，不做送将过滤。
    """
    army = army or s["turn"]
    # 已失去行棋资格的方（出局 / 认输 / 历史上被判负的）一步也不能走。
    #   `_advance` 本来就会跳过它们，但调用方（快照、前端、测试）单独问某一方时
    #   也应当得到一致答案。老师 2026-09-24 的「认输」验证正是踩在这一点上。
    if army in (s.get("out") or ()):
        return []
    frozen = frozen_now(s) if frozen is None else frozen
    if army in frozen:
        return []
    guard = protected_out_generals(s)
    out = []
    for frm, to in R.side_moves(s, army, frozen):
        allowed = guard.get(to)
        if allowed is not None and army not in allowed:
            continue                    # §9 第3条：第三方不得吃"照面中"的出局方帅
        if P.chain_blocks(s, army, to):
            continue                    # 《一.5》连吃上限（默认 None=不限，故通常不拦）
        if not skip_repeat and repeat_blocked(s, army, frm, to):
            continue                    # 反复走同一条路径（老师 2026-10-02：限制它不走）
        out.append((frm, to))
    return out


# ---------------------------------------------------------------- 残局判平
# 老师 2026-09-24 原文：
#   「还有一种情况，场上跑到最后大家的车马炮兵都没有了，谁也将不死谁，
#     留下的都是象、士，并且 9 次轮盘之后，多方帅都不照面，
#     此时自动判定场上剩下的各方平局。」
#
# 口径落地：
#   · 「车马炮兵」= 唯一有攻击力的子种（能过河/出军帐、够得到对方帅）；
#     象、士都出不了本方（象不过河、士只在军帐），帅更走不出去
#     ⇒ 只剩它们时**理论上无法将死**，与原文"谁也将不死谁"等价。
#   · 「9 次轮盘」按【三方各走 1 步算 1 轮】理解 ⇒ 9 轮 = 27 个半回合。
#   · 「多方帅都不照面」= 无违规见面、也不处于《一、10》待决。
DEAD_KINDS = (R.ROOK, R.HORSE, R.CANNON, R.PAWN)     # 有攻击力的子种
STALEMATE_ROUNDS = 9                                 # 「9 次轮盘」


def only_ele_adv(s):
    """**在局各方**是否只剩「无攻击力」的棋子（象 / 士 / 帅 / 副帅）

    只看"还能行动的那几方"名下的棋子：已出局/已认输方的残兵虽然留着，
    但它们**不能被控制**（《一、6》），自然也无法将死任何人，不计入。
    """
    alive = set(alive_armies(s))
    for p in s["board"].values():
        if p["army"] in alive and p["kind"] in DEAD_KINDS:
            return False
    return True


def mark_stale(s):
    """记下**首次**进入「只剩象/士」残局的着法数（单调，一旦进入不再复位）"""
    if s.get("stale_from_ply") is None and only_ele_adv(s):
        s["stale_from_ply"] = s["ply"]
    return s.get("stale_from_ply")


# ------------------------------------------------------------------ 重复着法
# 【老师 2026-10-01 报】「反复按照同一个路径将军超过三次，这是不行的，
#   游戏无法进行下去，进入死循环」。
#   现场（存档重放，ply 120~150）：魏 134↔124、吴 137↔127 各自来回走了 15+ 回合，
#   盘面零进展、**一次将军都没有**，而当时的兜底只剩 `max_ply=300`
#   （且触顶时 `drawn=False`，不算判和）⇒ 观感就是"棋下不完"。
#
# 【老师 2026-10-02 改口径 · 本条规则的**唯一权威表述**】
#   老师原话：
#     「长将判负：魏方反复走同一条路径（222-232）并且一直在将军，超过 3 次 →
#       依传统中国象棋「长将判负」，该方失去行棋资格（帅留盘、棋子不易主，≠ 出局）
#       **不对，为何魏方被判出局，你只要限制它不走重复路径就 ok 了**」
#
#   ⇒ 从事后判罚改为**事前拦截**：
#     · 会构成"超限重复"的那一手，**直接不进 `legal_moves`**（见 `repeat_blocked`）——
#       不是"走出去之后再判罚"；
#     · **绝不判负、绝不写 `out` / `declared_lose`**。
#       为什么这条非改不可：前端 `web/app.js` 把 `st.out` 渲染成「已出局」①，
#       而本项目「出局」的**唯一**触发条件是**主帅被吃**（见 `alive_armies` 的注）。
#       旧写法把"长将判负"塞进 `out` ⇒ 老师屏幕上出现"魏方被判出局"，
#       连旧战报文案里那句"≠ 出局"都救不了 —— 前端只认 `out` 这个数组。
#     · 唯一兜底（某方**除重复外无路可走**，例如长将是它唯一的活路）⇒
#       温和地判「不变作和」`repeat_draw`（三方棋判和已有先例：残局判平 / 三方无着判和）。
#       它要求"该方所有着法都只剩那条重复边"，实战极难触发。
#
#   ① `web/app.js` 两处：`al.push('出局：' + st.status.out.map(...))`
#      与 `` `${dead ? '　<span class="abt off">已出局</span>' : ''}` ``。
REPEAT_LIMIT = 3          # 「超过三次」⇒ 允许走 3 次，第 4 次**不可选**（0 = 关闭）


def _repeat_limit(s):
    """本局的重复杂数上限（`repeat_limit = 0` ⇒ 整条规则关闭，保留给"只想观棋"的场合）"""
    v = s.get("repeat_limit")
    return int(v if v is not None else REPEAT_LIMIT)


def edge_key(frm, to):
    """把一手着法化成本条规则用的**无向边** key（`124-134` ≡ `134-124`）

    ⚠️ 必须无向：老师现场看到的正是"同一个棋子来回走"，
       按有序 (from→to) 数就永远是两条不同的着法、永远凑不满。
    """
    return f"{frm}-{to}" if str(frm) <= str(to) else f"{to}-{frm}"


def note_repeat(s, army, frm, to, gave_check):
    """记一手，维护「同一方**连续**重复同一条边」的计数（返回该方的记录）"""
    ek = edge_key(frm, to)
    reps = s.setdefault("repeat", {})
    rec = reps.get(army)
    if rec and rec.get("edge") == ek:
        rec["n"] = int(rec.get("n") or 1) + 1
        rec["check"] = int(rec.get("check") or 0) + (1 if gave_check else 0)
    else:
        rec = {"edge": ek, "n": 1, "check": 1 if gave_check else 0}
    reps[army] = rec
    return rec


def repeat_state(s, army):
    """该方当前的重复计数（给前端展示用）；没有记录返回 None

    ⚠️ 键要兼容 **str**：`match._restore_int_keys()` 会把存档读回的
       `{"1": {...}}` 转成 `{1: {...}}`，但**任何绕过那一层的路径**
       （引擎单测、旧存档、手工构造 state）拿到的可能是字符串键。
       只认 int 会让"重复计数"在新进程里凭空归零 ⇒ 长将又走得出来了。
    """
    reps = s.get("repeat") or {}
    rec = reps.get(army)
    if rec is None:
        rec = reps.get(str(army))
    return rec


def repeat_blocked(s, army, frm, to):
    """这一手**是否被本条规则禁止**（True = 不该出现在合法着法里）

    判据三条，缺一不可：
      · **无向边**相同（`222-232` ≡ `232-222`）—— 老师现场就是来回走；
      · 是**该方连续**的（中间换了别的边 ⇒ 计数已重置，不误禁）；
      · 本手之后会**超过**上限（走满 3 次仍允许，第 4 次不行）。
    """
    lim = _repeat_limit(s)
    if lim <= 0:
        return False
    rec = repeat_state(s, army)
    if not rec or rec.get("edge") != edge_key(frm, to):
        return False
    return int(rec.get("n") or 0) + 1 > lim


def repeat_stuck(s, army):
    """该方是否「**除重复外无路可走**」（= 唯一兜底的触发条件）

    两个条件同时成立：
      · 过滤后 `legal_moves` 为空（该方现在没得走）；
      · **不过滤**时非空（说明它本来有棋，只是全被重复规则拦了）。

    ⇒ 只有这时才判「不变作和」。绝不判负 —— 见文件头 2026-10-02 的口径说明。
    """
    lim = _repeat_limit(s)
    if lim <= 0:
        return False
    rec = repeat_state(s, army)
    if not rec or int(rec.get("n") or 0) < lim:
        # ★ 廉价早退（`status()` 每次快照都会问一遍）：计数没走满上限的方，
        #   不可能"只剩重复" ⇒ O(1) 返回，不触发下面两次 `legal_moves`。
        return False
    fr = frozen_now(s)
    if army in (s.get("out") or ()) or army in fr:
        return False                       # 出局/冻结导致的"没得走"与本规则无关
    return (not legal_moves(s, army, fr)) and bool(
        legal_moves(s, army, fr, skip_repeat=True))


def repeat_draw(s):
    """是否已因"机械重复"判和"""
    return bool(s.get("repeat_draw"))



def stale_rounds(s):
    """已进入残局多少轮（三方各走 1 步 = 1 轮）；未进入返回 None"""
    f = s.get("stale_from_ply")
    if f is None:
        return None
    return (s["ply"] - f) // len(TURN_ORDER)


def stalemate_draw(s):
    """残局判平是否成立（老师 2026-09-24 定，2026-09-25 随「射杀」规则更新）

    三个条件缺一不可：
      ① 在局各方只剩象 / 士 / 帅（无车马炮兵）；
      ② 该局面已持续满 9 轮；
      ③ **盘上不存在任何「射杀」关系**（任一枚帅/副帅能沿见面线照见另一枚帅/副帅）。

    【第 ③ 条的含义在 2026-09-25 变了，必须说清】
      旧规则：照面是**违规**（会被判负）⇒ 判平要求"都不照面"。
      新规则：照面 = **下一手就能远程斩首** ⇒ **只要还存在射杀关系，棋就没下完**，
              仍可能决出胜负，此时判平是把胜负判没了。
      所以判据从 `facing_pairs`（只看在局主帅、且剔除豁免对）
      换成 `snipe_pairs`（含副帅、不过滤豁免）—— 与"照见即可射杀"同一口径。
    """
    if not only_ele_adv(s):
        return False
    f = s.get("stale_from_ply")
    if f is None or (s["ply"] - f) < STALEMATE_ROUNDS * len(TURN_ORDER):
        return False
    return not snipe_pairs(s)


def resign(s, army):
    """认输 —— 老师 2026-09-24 口径：「不存在求和，只允许认输」。

    语义上与《一、10》判负**同类**：该方**主动放弃行棋资格**，
      · 帅**留在盘上**（不被吃、不生成副帅）；
      · 棋子**不易主**（依《一、6》，另两方不能控制但可以吃）；
      · 不做战力转移。
    ⚠️ 与「出局」严格区分：老师口径——**出局的唯一触发条件仍是主帅被吃**，
      认输只进 `out`（失去资格）与 `resigned`，**不进 `eliminated`**。

    三方局里非当前回合方也允许认输（现实对局如此）。
    """
    if army in s["out"]:
        return None
    s["out"].append(army)
    if army not in s.setdefault("resigned", []):
        s["resigned"].append(army)
    s["combat"][army] = False          # 认输方不能再行动
    P.refresh_vitality(s)              # 没吃帅 → 生命力按盘面仍"有"
    P.refresh_combat(s)
    _advance(s, moved=False)           # 认输不是落子，不计入《一、3》的约定步数
    mark_stale(s)
    alive = alive_armies(s)
    if len(alive) == 1:
        s["winner"] = alive[0]
    return {"type": "resign", "army": army}


def judge_lose(s, target):
    """【已退役 · 2026-09-25】《一、10》方案①：A 直接把 B 判负。

    ⚠️ **引擎内部已无任何调用点**。原因：新规则（照见即可射杀）之下"照面"不再违规，
      `pending_judge()` 恒为 None ⇒ 判负失去全部触发条件。
      函数体保留，是为了：
        · 历史对局复盘 / 外部集成仍可显式调用；
        · `alive_armies` 的 `out` 语义（"失去行棋资格"）仍以它为参照之一。

    判负与吃帅的关键差别（决定盘面形态，别混）：
      · **B 的帅留在盘上**（没被吃）。依《一、6》：另两方不能控制出局方棋子，
        但可以吃；直到这枚帅被吃掉后，B 的棋子才归吃帅方控制（届时走《一、7》副帅流程）。
      · A **不获得** B 的任何棋子。
    """
    actor = s["turn"]
    if target not in s["out"]:
        s["out"].append(target)          # 失去行棋资格（不等于"出局"，见 alive_armies 注释）
    if target not in s.get("declared_lose", []):
        s["declared_lose"].append(target)
    s["combat"][target] = False          # 已判负 → 不能行动（主帅仍在盘上，生命力尚存）
    P.refresh_vitality(s)                # 判负不吃帅 → 生命力按盘面仍为"有"
    P.refresh_combat(s)
    _advance(s, moved=False)             # 判负不是落子：《一、10》「判负回合不再走棋」
    mark_stale(s)
    alive = alive_armies(s)
    if len(alive) == 1:
        s["winner"] = alive[0]
    return {"type": "judge", "by": actor, "lose": target}


def _move_piece(s, frm, to, frozen=frozenset()):
    piece = s["board"].pop(frm)
    victim = s["board"].get(to)
    s["board"][to] = piece
    s["history"].append(f"{frm}-{to}")
    s["ply"] += 1
    if victim and victim["kind"] == R.GENERAL:
        if victim.get("deputy"):
            _deputy_captured(s, victim, piece["army"])
        else:
            # killer_pos=to：《一、7》「吃 A 帅的棋子为 B 方副帅」——
            #   吃帅的那枚棋子**就地升格**（身份变更），原棋子（炮/车/兵…）从盘上消失；
            #   位置 = 被吃帅的原位置（= 落点）。
            #   老师 2026-09-25 绕了一圈后确认「退回原先的方式」＝本条原文口径。
            #   见 patent.spawn_deputy。
            P.on_general_captured(s, victim, piece["army"], killer_pos=to)
    return victim


def _deputy_captured(s, victim, capturer):
    """副帅被吃：该批残兵易主给吃副帅者；原控制方的战斗力相应变化
    （副帅自身不代表任何方的出局 —— 它代表的那个方早就出局了）"""
    side = victim["home"]
    prev = victim["army"]
    s["deputies"].pop(side, None)
    for _p, q in s["board"].items():
        if q.get("home") == side and q.get("army") == prev:
            q["army"] = capturer
    s["annexed"][side] = capturer
    P.refresh_combat(s)


def apply(s, frm, to, frozen=None):
    frozen = frozen_now(s) if frozen is None else frozen
    actor = s["turn"]
    # 《一、7》「吃 A 帅的棋子为 B 方副帅」⇒ 战报要说清"是哪枚棋子升格了"。
    #   必须**走子前**记：走完后 frm 已空、to 上已是副帅，事后再查就查不到凶手。
    #   老师 2026-09-25 明确要求前端显示「炮升格为副帥」，否则会以为棋子凭空消失。
    killer_kind = (s["board"].get(frm) or {}).get("kind")
    victim = _move_piece(s, frm, to, frozen)
    note = {"from": frm, "to": to, "army": actor,
            "captured": victim["kind"] if victim else None,
            "captured_army": victim["home"] if victim else None}
    # 《一.5》连吃记账（先记，下面判断出局等都不影响它）
    P.note_chain(s, actor, victim)
    if victim and victim["kind"] == R.GENERAL:
        # 【2026-09-24 修】副帅虽然也是 kind=general，但吃掉它**不代表任何方出局**
        #   （它代表的那个方早就出局了，`eliminated` 里已经有它）。
        #   旧实现无条件写 `note["eliminated"] = victim["home"]`，后果两条：
        #     ① match.step() → slain[army] += 1 → 综合分凭空 +1000（W_SLAIN）
        #     ② 前端 app.js 的 `e.eliminated ? 斩帥X方主帅 : (e.is_deputy ? 斩副帅)`
        #        三元链里 eliminated 优先 → 吃副帅被渲染成「斩帥 X方主帅」，
        #        屏幕还会提示该方「被杀出局」（其实人家早就出局了）。
        #   老师 2026-09-24 观察到的「帅被吃了 / 屏幕显示此方将被杀出局」即源于此。
        if victim.get("deputy"):
            note["is_deputy"] = True            # 只是斩了个副帅（不代表任何方出局）
        else:
            note["eliminated"] = victim["home"]  # 真·主帅被斩 → 该方出局
            note["is_deputy"] = False
            # 《一、7》：吃帅的那枚棋子**升格为副帅** —— 它从盘上"消失"了
            #   （身份变成副帅，驻守被吃方军帐）。前端据此显示「炮→副帥」，
            #   避免老师看到炮没了却不知道去哪了（2026-09-25 老师明确要求）。
            note["promoted_from"] = killer_kind
    # 【2026-10-01 记 / 2026-10-02 改】重复着法计数（见 `note_repeat` / `repeat_blocked`）。
    #   `gave_check` = 这一手走完后**是否有别的方正被本方将军** ——
    #   改造后它**只用于展示**（快照里 `repeat[方].check`），不再参与判罚分叉。
    #   放在 `_advance` 之前：计数属于"这一手"的属性，与轮转无关。
    _cm = check_map(s)
    _gave = any(actor in v for k, v in _cm.items() if int(k) != actor)
    note_repeat(s, actor, frm, to, _gave)
    _advance(s)
    mark_stale(s)                       # 残局判平计时：可能这一刻才进入「只剩象/士」
    # 【2026-10-02 老师裁决】重复着法**改为事前拦截**（老师：「你只要限制它
    #   不走重复路径就 ok 了」）—— 旧写法在这里判「长将判负」并把该方塞进 `out`，
    #   而前端把 `st.out` 渲染成「已出局」（「出局」只该由**主帅被吃**触发）。
    #   拦截本身已经在 `legal_moves` 里做完（第 4 次根本走不出来），这里只剩
    #   **唯一兜底**：某方"除重复外无路可走" ⇒ 温和判「不变作和」。
    #   放在 `_advance` 之后是对的：轮到谁，才谈得上"谁没得走"。
    #   ⚠️ 这段**绝不许**写 `out` / `declared_lose` —— 前端把它们渲染成「已出局」，
    #      而「出局」在本项目的唯一触发条件是**主帅被吃**（老师 2026-10-02 的裁决）。
    _lim = _repeat_limit(s)
    if _lim > 0:
        for _a in alive_armies(s):
            _rec = repeat_state(s, _a)
            if not _rec or int(_rec.get("n") or 0) < _lim:
                continue                     # 没走满上限的方，不可能"只剩重复"
            if repeat_stuck(s, _a):
                s["repeat_draw"] = True
                note["repeat_draw"] = True
                note["repeat_army"] = _a
                note["repeat_edge"] = _rec.get("edge")
                break
    alive = alive_armies(s)
    if len(alive) == 1:
        s["winner"] = alive[0]
    return note


def _advance(s, moved=True):
    """轮转到下一方

    【《一、3》回合与步数】老师 2026-09-24 引原文：
      「三方对战，一方走一步或走多步（按约定步数）为一回合，直到决出胜负；
        各方使完约定步数时轮转到下一方。」
    ⇒ `steps_per_turn`（**约定步数**，默认 **1** ＝ 传统口径）：
        1 = 走一步就轮转（现状）；
        N = 一方连续走满 N 步后才轮转（本回合内不换人）。
      `moved=False` 用于「不落子的动作」（《一、10》判负 / 认输）——
      它们消耗的是"这一回合"，不该被计入本回合已走步数。
    """
    n = max(1, int(s.get("steps_per_turn") or 1))
    if not moved:
        s["turn_steps"] = 0
    elif n > 1:
        used = int(s.get("turn_steps") or 0) + 1
        if used < n and (pending_judge(s) is not None
                         or legal_moves(s, s["turn"])):
            s["turn_steps"] = used
            return                       # 本回合还没走够 → 同一方继续走
        s["turn_steps"] = 0
    for _ in range(len(TURN_ORDER) * 2 + 3):
        i = TURN_ORDER.index(s["turn"])
        s["turn"] = TURN_ORDER[(i + 1) % len(TURN_ORDER)]
        if s["turn"] not in alive_armies(s):
            continue
        if s["winner"]:
            return
        # 《一、10》处于待决的一方**总有棋可走**（实在挡不住/挪不开，还能"判 B 负"），
        #   所以即便 legal_moves 为空也不能当成"停走"跳过 —— 那会把它该做的判定白扔。
        if pending_judge(s) is not None:
            return
        if legal_moves(s, s["turn"]):
            return
        s["passed"].append(s["turn"])


def status(s):
    cm = check_map(s)
    return {
        "turn": s["turn"], "ply": s["ply"],
        "alive": alive_armies(s), "eliminated": s["eliminated"],
        "annexed": s["annexed"], "winner": s["winner"],
        "checks": {str(k): sorted(v) for k, v in cm.items()},
        "frozen": sorted(frozen_now(s)),
        "generals_facing": [list(p) for p in R.generals_facing(s)],
        "last": s["history"][-6:],
        "passed": s["passed"][-4:],
        # ---- 专利版专属 ----
        "deputies": {str(k): v for k, v in s.get("deputies", {}).items()},
        "vitality": {str(k): v for k, v in s.get("vitality", {}).items()},
        "combat": {str(k): v for k, v in s.get("combat", {}).items()},
        "out": s.get("out", []),
        "declared_lose": s.get("declared_lose", []),   # 《一、10》判负出局
        "resigned": s.get("resigned", []),             # 认输方（老师：不存在求和）
        # ---- 残局判平（老师 2026-09-24：只剩象/士 + 9 轮 + 帅不照面）----
        "only_ele_adv": only_ele_adv(s),
        "stale_from_ply": s.get("stale_from_ply"),
        "stale_rounds": stale_rounds(s),
        "stale_total_rounds": STALEMATE_ROUNDS,
        "stalemate_draw": stalemate_draw(s),
        # ---- 重复着法（老师 2026-10-01「反复走同一路径…进入死循环」）----
        "repeat": {str(k): v for k, v in (s.get("repeat") or {}).items()},
        "repeat_limit": _repeat_limit(s),
        "repeat_draw": repeat_draw(s),
        # 谁"除重复外无路可走"（正常应恒为空；非空 ⇒ 下一手会判「不变作和」）
        "repeat_stuck": sorted(a for a in TURN_ORDER if repeat_stuck(s, a)),
        # ---- 《一、3》回合与步数（约定步数，默认 1）----
        "steps_per_turn": int(s.get("steps_per_turn") or 1),
        "turn_steps": int(s.get("turn_steps") or 0),
        "chain_limit": s.get("chain_limit"),           # 《一.5》连吃上限（None=不限）
        "chain": {str(k): v for k, v in (s.get("chain") or {}).items()},
        # 【2026-09-25】《一、10》被动见面判负已退役，`pending_judge` 恒为 None。
        #   字段保留只为兼容既有前端 / 测试的读取（它们拿到 None 即"无待决"）。
        "pending_judge": None,
        # 射杀关系（新规则 2026-09-25）：[[攻击者点位, 被瞄准的帅/副帅点位], ...]
        #   供前端把"正被对方瞄准的帅"标红，让玩家一眼看到致命关系。
        "snipe": [[a, b] for a, b in snipe_pairs(s)],
        "tent": {str(k): P.TENT[k] for k in (1, 2, 3)},
    }


def render_text(s, legal=None, show_legal=True, show_history=False):
    """给 LLM 看的纯文本局面

    【两个开关对应两种赛制】
    show_legal=True  → 「赛制 B：选择题」棋盘 + 全部合法着法，模型只做挑一个。
                       实测合法率能从 0% 拉到 100%（因为不必自己算规则），
                       测出来的是**纯决策质量**。这也是本项目的默认档。
    show_legal=False → 「赛制 A：裸生成」只给棋盘，模型要自己推合法着法。
                       这一档专门用来暴露"规则内化 / 指令遵循"的短板，
                       合法率本身就是最刺眼的指标。

    show_history：
        默认 False —— **每步只给当前局面，不给历史**。
        理由：历史会让不同模型的上下文长度不一致（不公平），
        也会让模型靠"复述上文"蒙混过关，测不出真正的状态理解。
        要研究"长程状态维持"时才打开。
    """
    rows = []
    for k in TURN_ORDER:
        items = []
        for pos in sorted(s["board"]):
            p = s["board"][pos]
            if p["army"] != k:
                continue
            ch = ARMY_CN[p["home"]] + KIND_CN[p["kind"]]
            tagn = "" if p["home"] == p["army"] else "(收编)"
            if p.get("deputy"):
                tagn = "(副帅)"
            items.append(f"{pos}{'/' + tagn if tagn else ''}={ch}")
        rows.append(f"  [{ARMY_CN[k]}方] " + " ".join(items) if items
                    else f"  [{ARMY_CN[k]}方] （已出局）")
    st = status(s)
    head = [f"当前轮到：{ARMY_CN.get(st['turn'], '-')}方",
            f"存活：{'、'.join(ARMY_CN[a] for a in st['alive'])}"]
    if st["checks"]:
        for k, v in st["checks"].items():
            head.append(f"⚠ {ARMY_CN[int(k)]}方被将军（{', '.join(ARMY_CN[a] for a in v)}方叫将）")
    if st["frozen"]:
        head.append(f"停走中（其子不可通过、不可被吃）：{'、'.join(ARMY_CN[a] for a in st['frozen'])}")
    if st["out"]:
        head.append("已出局：" + "、".join(f"{ARMY_CN[a]}（残兵归{ARMY_CN[st['annexed'][a]]}）"
                                          for a in st["out"]))
    body = ["局面棋子（点位 id：方-行-列，方 1魏 2蜀 3吴，行 1底线..5最内，列 1右..9左）", *rows]
    tail = []
    if show_history and s["history"]:
        tail.append("最近着法：" + "  ".join(s["history"][-8:]))
    if legal is not None and show_legal:
        tail.append(f"你方合法着法共 {len(legal)} 步：")
        tail.append("  " + " ".join(f"{a}-{b}" for a, b in legal))
    return "\n".join(head + [""] + body + ([""] + tail if tail else []))
