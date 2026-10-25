# -*- coding: utf-8 -*-
"""专利版专属规则：军帐、副帅、生命力 / 战斗力

与标准鼎棋版（1 号版本）的差异集中在这里，不改动 rules.py 的走法生成，
只在对局状态机上做增量。

【已实现的机制】
  · 副帅：一方主帅被吃后，**吃帅的那枚棋子升格为副帅**（《一、7》原文：
          「**吃 A 帅的棋子为 B 方副帅**」）—— 棋子**身份变更**（不是新造单位），
          原棋子（炮/车/兵…）从盘上消失，在被吃帅的落点上以「吃帅方的副帅」继续存在。
          位置 = 被吃帅的原位，必在 A 方军帐内（主帅只能在军帐内活动）
          ⇒ 「副帅不能出军帐」自动成立；副帅被吃则该批残兵易主。
          📌 2026-09-25 老师绕了一圈后确定「退回原先的方式」＝**本条原文口径**：
            他曾先后试过「被吃帅易主留在盘上当副帥」「副帅不要了、帅直接移出棋盘」，
            最后看回《一、7》第 7 条原文，认定**原文就对**（吃帅的棋子当副帅）。
            所以引擎的行为 = 今天的初版行为，一直没变过的那些注释现在与代码一致了。
  · 生命力 vitality：该方主帅是否还在盘上（**从盘面派生**，见 refresh_vitality）。
  · 战斗力 combat：该方主帅还在，或该方手里还握着别人的副帅。
  · out：**失去行棋资格** = 出局（主帅被吃）∪ 判负（《一、10》）。
  · eliminated：**真·出局** —— 唯一触发条件就是主帅被吃（老师 2026-09-24）。
  · 判负 declared_lose：《一、10》帅被动见面时把对方判负（帅留盘、棋子不易主）。
  · 连吃上限 chain_limit：《一.5》可选约定，**默认 None = 不限制**，网页可输入整数。

【2026-09-24 已确认，不再是"待校准"】
  · 军帐 = **每方九宫 3×3 共 9 点**（不是 6 点、不是 2×2 田字格），中心 = 底线中点：
      魏 125(D5) / 吴 225(N5) / 蜀 325(I5)
    老师原话举例：魏国军帐 = C4,C5,C6,D4,D5,D6,E4,E5,E6。
  · 「判定」= 《一、10》的判负，见 game_dxf.judge_lose。
  · 兵营点位跨方、三角区马的回跳点位 均已实现（在 rules_dxf.py）。
"""

# 军帐（DXF 版：每方九宫 = 行 1-3 × 列 4-6，共 9 点）+ 军帐中心
TENT = {a: [f"{a}{r}{c}" for r in (1, 2, 3) for c in (4, 5, 6)] for a in (1, 2, 3)}
TENT_CENTER = {a: f"{a}25" for a in (1, 2, 3)}

# ⚠️【2026-09-24 修正】原为 {1:"魏", 2:"蜀", 3:"吴"} —— 蜀/吴对调，与权威表冲突。
#   权威 = `geometry_dxf.ARMY_CN = {1:"魏", 2:"吴", 3:"蜀"}`（已由棋盘原图证实：
#   吴的字母线是 K-O、蜀是 F-J；引擎里 army2 中点 x=−14.67 在左=吴，army3 在右=蜀）。
#   本常量当前无人引用（死常量），但留着反的迟早会咬人，故与权威对齐。
ARMY_CN = {1: "魏", 2: "吴", 3: "蜀"}


def new_fields():
    """新开局时要挂上的专利版状态字段"""
    return {
        "deputies": {},        # {原方: {"pos": 点位, "owner": 控制方}}  副帅
        "vitality": {1: True, 2: True, 3: True},   # 生命力：本方主帅是否在盘上
        "combat": {1: True, 2: True, 3: True},     # 战斗力：主帅在，或手握副帅
        "out": [],             # 失去行棋资格的方 = 出局 ∪ 判负 ∪ 认输（见 game_dxf.alive_armies）
        "eliminated": [],      # 真·出局方：**只有"主帅被吃"这一条途径**（老师 2026-09-24）
        "declared_lose": [],   # 《一、10》被判负出局（帅仍留在盘上、棋子未易主）
        # 认输方（老师 2026-09-24：「不存在求和，只允许认输」）。
        #   与判负同类：帅留盘、棋子不易主，只是不再行棋 ≠ 出局。
        "resigned": [],
        # 残局判平计时（老师 2026-09-24）：
        #   原文「场上跑到最后大家的车马炮兵都没有了，谁也将不死谁，留下的都是象、士，
        #         并且 9 次轮盘之后，多方帅都不照面，此时自动判定场上剩下的各方平局」
        #   stale_from_ply = **首次进入「只剩象/士」局面**时的着法数，用于倒计时。
        "stale_from_ply": None,
        # ---- 重复着法计数（老师 2026-10-01：「反复按照同一个路径…超过三次，
        #   这是不行的，游戏无法进行下去，进入死循环」）----
        #   `{方: {"edge": "124-134", "n": 连续次数, "check": 其中造成将军的次数}}`
        #   ★ 判据用**无向边**：`124-134` 与 `134-124` 是同一条路径的两个方向，
        #     只按 (from→to) 有序对去数，来回走永远凑不满次数（老师现场就是来回走）。
        #   【2026-10-02 老师改口径】它**不再用于判罚**，只用于**事前拦截**：
        #   `legal_moves` 会拦掉"再走一次就超限"的那一手（`game_dxf.repeat_blocked`）。
        #   详见 `game_dxf` 文件头「重复着法」段。
        "repeat": {},
        # 唯一兜底：某方"除重复外无路可走" ⇒ 判「不变作和」（绝不判负、绝不写 out）。
        "repeat_draw": False,
        # ---- 《一、3》回合与步数（老师 2026-09-24 引原文）----
        #   「三方对战，一方走一步或走多步（按约定步数）为一回合，直到决出胜负；
        #     各方使完约定步数时轮转到下一方。」
        #   默认 1 = 传统口径（走一步即轮转）；N = 一方连走 N 步后才换人。
        "steps_per_turn": 1,
        "turn_steps": 0,       # 当前方在本回合内已走的步数
        # ---- 《一.5》连吃上限（老师 2026-09-24：网页可输入整数；默认 NULL = 不限制）----
        #   原文：「为避免蓄意的"二打一"情况，玩家可提前约定，连吃一方棋子不能超 (*) 个。」
        #   chain_limit=None ⇒ 传统象棋口径，不限；=0 ⇒ 禁止连吃；=N ⇒ 最多连吃 N 个。
        "chain_limit": None,
        #   chain[army] = {"victim": 被连吃方, "n": 已连吃几个}
        #   只在"吃的是同一方的棋子"时累加；一旦走了不吃子的着法（或改吃另一方）即清零。
        "chain": {},
    }


def refresh_vitality(s):
    """按**盘面**重算生命力 —— 老师口径：「主要看帅是否存在」。

    老师 2026-09-24：
      · 生命力 / 战斗力**只有"有 / 无"**两种状态，不需要具体数值（没有血格）；
      · 判据就是本方主帅是否还在盘上；
      · 主帅被吃、该方变成副帅 → 即视为原先那方**已经失去生命力**。

    这里从盘面派生（而不是在各处手工赋值），避免漏调导致字段漂移：
    副帅（deputy=True）不算主帅，所以"主帅被吃 → 生成副帅"之后自然为 False。
    """
    for k in (1, 2, 3):
        s["vitality"][k] = any(
            p["kind"] == "general" and not p.get("deputy") and p["home"] == k
            for p in s["board"].values())
    return s["vitality"]


def prune_deputies(s):
    """注销「盘上已无对应副帅」的登记条目；返回删掉的条数。

    【2026-10-02 修 · 副帅登记表去残留】
      `deputies` 是**派生表**（`{代表方: {"pos": …, "owner": …}}`），唯一真相是**盘面**。
      当"副帅自己跑去斩帅、就地升格为代表新方的副帅"时（老师 2026-10-02 那局
      ply 64：驻吴帐的蜀方副帅 225 射杀魏帥 115），旧登记 `{2: …}` 无人注销 ⇒
      盘上只剩 1 枚副帅、登记表却有 2 条 ⇒ 前端状态条多出一条**幽灵副帅**
      （"吴方军帐（归蜀）"，可吴军帐里早已没有副帅）。

      判据：**盘上还有没有 `home == rep` 的 deputy 棋子**。
      ⚠️ 不许用 `pos` 判 —— 副帅在军帐内走动后 `pos` **从不更新**
         （全工程无任何一处维护它），拿它当判据会把**活着**的副帅误注销。

    为什么单独抽一个函数：`restore()` 载入存档时**只想修账本**，不想覆盖
      存档里已算好的 vitality / combat（那会破坏"忠实还原"语义，见
      `tests/_verify_resume.py` 的语义级往返断言）。引擎内部走 `refresh_combat`
      （它顺带调本函数）。
    """
    dep = s.get("deputies")
    if not dep:
        return 0
    on_board = {p["home"] for p in s["board"].values() if p.get("deputy")}
    gone = [k for k in dep if k not in on_board]
    for k in gone:
        dep.pop(k, None)
    return len(gone)


def refresh_combat(s):
    """重算战斗力：主帅还在，或手里还握着某方的副帅

    ⚠️ 已失去行棋资格的一方（`out`：主帅被吃 或 《一、10》判负）战斗力恒为 False。
      判负时主帅仍留在盘上（生命力尚存），但它已无战斗力。

    ★ 先把副帅登记表按盘面收敛（`prune_deputies`），再据**收敛后的** owners 算
      combat —— 否则幽灵条目的 owner 会虚撑某方战斗力。判据说明见 `prune_deputies`。
    """
    refresh_vitality(s)
    prune_deputies(s)
    out_of = set(s.get("out") or ())
    owners = {d["owner"] for d in (s.get("deputies") or {}).values()}
    for k in (1, 2, 3):
        if k in out_of:
            s["combat"][k] = False
        else:
            s["combat"][k] = bool(s["vitality"].get(k)) or (k in owners)


# ---------------------------------------------------------------- 《一.5》连吃上限
def chain_blocks(s, army, to):
    """《一.5》连吃上限：这步「吃 to 点上的子」是否超了约定？

    原文：「三方对战，为避免蓄意的"二打一"情况，玩家可提前约定，
           连吃一方棋子不能超 (*) 个。」

    口径（老师 2026-09-24）：
      · `chain_limit` 默认 **None = 不限制**（等同传统象棋，不额外加限制）；
      · 网页可输入整数：0 = 禁止连吃；N = 同一方棋子最多连吃 N 个；
      · "连吃"按【被吃棋子当前的归属方】计数（副帅易主后按新主人算）。

    只在**同一方、连续**吃子时累加：中间只要走了一步不吃子的棋，计数清零。
    """
    lim = s.get("chain_limit")
    if lim is None:
        return False                     # 默认不限制
    victim = s["board"].get(to)
    if not victim or victim["army"] == army:
        return False                     # 不是吃子 / 吃的是自家子
    cur = (s.get("chain") or {}).get(army) or {}
    # 换了个对手吃 → 这一口等于"新起一次连吃"，已吃数按 0 起算。
    #   这个 0 很关键：`(*)`=0（禁止连吃）时正是靠它把**第一口**也拦下。
    n = int(cur.get("n", 0)) if cur.get("victim") == victim["army"] else 0
    return n >= int(lim)


def note_chain(s, army, victim):
    """落子后记账：更新 army 的连吃计数（返回更新后的记录）"""
    chain = s.setdefault("chain", {})
    cur = chain.get(army) or {"victim": None, "n": 0}
    if victim and victim["army"] != army:
        same = (cur.get("victim") == victim["army"])
        cur = {"victim": victim["army"], "n": (cur.get("n", 0) + 1) if same else 1}
    else:
        cur = {"victim": None, "n": 0}   # 不吃子（或吃自家子）→ 连吃中断
    chain[army] = cur
    return cur


def free_in_tent(s, side):
    """军帐里第一个空位，优先用中心

    ⚠️ 副帅走「吃帅的棋子**就地升格**」（见 spawn_deputy），本函数退为**兜底**：
      只有当吃帅的落点不在 A 军帐内（正常不可能，主帅只能在军帐内走）才会用到。
    """
    order = [TENT_CENTER[side]] + [p for p in TENT[side] if p != TENT_CENTER[side]]
    for p in order:
        if p not in s["board"]:
            return p
    return None                     # 军帐满了（几乎不可能）


def spawn_deputy(s, side, owner, killer_pos=None):
    """在 side 方军帐内生成副帅（**吃帅的棋子升格**），归 owner 控制

    【权威口径 · 《一、7》原文（老师 2026-09-25 最终「退回原先的方式」）】
      原文：「A 帅被 B 的棋子吃掉，A 方剩余棋子归 B 控制，**吃 A 帅的棋子为 B 方副帅**，
            在 A 方"军帐"内行使帅的运行方式和职责……」

    ⇒ 副帅 = **吃帅的那枚棋子本身**，棋子**身份变更**（不是新造单位）。
      它吃掉 A 帅后落点就是 A 帅原位置，于是在该点就地"变身"为 B 方副帅；
      **原棋子（炮/车/兵…）从盘上消失** —— 这是规则本意、不是 bug：
      棋子数**净减 1**（被吃的帅消失；吃帅的子换了身份、不增不减）。
      📌 老师 2026-09-25 一度以为是 bug（「我的炮怎么没了」），中间试过两种改法，
        最后看回《一、7》第 7 条原文，确认**原文就对**，故「退回原先的方式」。

    ⚠️ **前端必须把这件事讲出来**：战报用 `note.promoted_from`（升格前的棋子种类）
      显示「炮→副帥」，否则老师会再以为是"棋子凭空消失"（本轮就是这么发现的）。

    为什么副帅一定在军帐内：主帅的走法由 `GEN_T` 限定在**本方军帐**内
      （实测 魏帥 115 → E6/E4/D5 三点），所以被吃的帅必在 A 军帐 ⇒ 副帅必在军帐
      ⇒ 「副帅不能出军帐」自动成立，且与《一、9》「副帅不可能阻隔帅见面」自洽
      （六条见面线路的中段全在 row5，不在任何军帐内）。

    兜底路径：若 killer_pos 不在 A 军帐内（帅跑出军帐，正常不可能），
      才退到 `free_in_tent()` 放回军帐，并把 killer_pos 上的子摘掉（保持净减 1）。

    killer_pos：吃帅棋子**落子后**所在的点（= 被吃帅的位置）。
    """
    tent = TENT.get(side) or ()
    if killer_pos and killer_pos in tent and killer_pos in s["board"]:
        pos = killer_pos                      # 正常路径：吃帅的棋子就地升格
    else:
        pos = free_in_tent(s, side)           # 兜底：放回军帐
        if pos is not None and killer_pos:
            s["board"].pop(killer_pos, None)  # 避免"吃帅子留在原地 + 军帐里又冒一个"
    if pos is None:
        return None                           # 军帐满了（几乎不可能）
    s["board"][pos] = {"kind": "general", "army": owner, "home": side,
                       "deputy": True}
    s["deputies"][side] = {"pos": pos, "owner": owner}
    refresh_combat(s)
    return pos


def on_general_captured(s, victim, capturer_army, killer_pos=None):
    """主帅被吃的全部后果（替代标准版的「立即收编」）

    专利版原文（《一、7》，老师 2026-09-25 确认这就是最终口径）：
      · 主帅被吃 -> 主副帅均失去战斗力和生命力
      · A 的帅被 B 吃掉后，A 剩余棋子归 B 控制，成为 B 的副帅；
        副帅在 A 方军帐内行使帅的职责，直至被吃掉（易主）或战局结束。
    killer_pos：见 spawn_deputy —— 吃帅的那枚棋子**就地升格**为副帅，
      **原棋子（炮/车/兵…）从盘上消失**（棋子数净减 1）。

    【2026-09-24 补 · 已被判负/认输的帅被吃】
    判负 / 认输时**帅留在盘上**（见 game_dxf.judge_lose）。依《一、6》，此时它的棋子
    另两方**不能控制但可以吃**；等这枚帅真被吃掉，才走本条流程（残兵归吃帅方）。
    所以本函数遇到"已失去资格、但帅还在盘上"的方，**不能提前 return**：
      · `out` 里已有它（幂等跳过）；
      · **但这时才把它记进 `eliminated`** —— 老师口径：出局的唯一触发条件就是
        主帅被吃。判负/认输只剥夺行棋资格，帅被吃的这一刻它才真·出局。
      · 并且照样要把残兵易主给吃帅方。
    """
    side = victim["home"]
    if side not in s["out"]:
        s["out"].append(side)
    # 老师 2026-09-24 口径：**「出局」的唯一触发条件就是主帅被吃**。
    #   所以"先判负 → 帅留盘 → 后来被吃"这条路，走到这一刻才把它记进 `eliminated`。
    if side not in s["eliminated"]:
        s["eliminated"].append(side)
    s["annexed"][side] = capturer_army

    # 【出局方的"一切"都易主】—— 老师 2026-09-24 指出必须如此
    # 出局方不再有资格动任何棋子，所以它名下的棋子必须**全部**换新控制者，
    # 否则会变成「谁都不能动」的死子。要转移的有三类：
    #   ① 它自己的残兵          （home == side）
    #   ② 它此前收编来的别方残兵 （home != side，但 army == side）
    #   ③ 它手里握着的别方副帅   （deputy，连带副帅登记表的 owner 一起改）
    # 旧写法只转 ①（条件 home==side and army==side），②③ 会留成孤儿：
    # 实测「魏吃吴帅拿到吴副帅 → 蜀再吃魏帅」时，吴的 15 个残兵全部卡死，
    # 存活方一步也碰不到它们（因为它们还挂着已出局方魏的 army）。
    for _pos, p in s["board"].items():
        if p["army"] != side:
            continue
        p["army"] = capturer_army
        if p.get("deputy"):                       # 副帅：登记表里的 owner 也要跟着换
            _rep_side = p["home"]                 # 该副帅代表哪个原方
            if _rep_side in s["deputies"]:
                s["deputies"][_rep_side]["owner"] = capturer_army

    # 《一、7》原文：**吃帅的那枚棋子就地升格为副帅**（原棋子从盘上消失）。
    #   老师 2026-09-25 绕了一圈（"炮不能变"→"副帅不要了"）后看回第 7 条原文，
    #   确认「退回原先的方式」＝本条。
    pos = spawn_deputy(s, side, capturer_army, killer_pos=killer_pos)
    refresh_combat(s)
    return pos


def on_deputy_captured(s, victim, capturer_army):
    """副帅被吃：该批残兵易主给吃副帅者；原控制方的战斗力相应变化

    专利版原文：副帅被吃，主帅和生命力不受影响，但失去副帅的战斗力。
    """
    side = victim["home"]                 # 副帅代表的原方
    prev_owner = victim["army"]           # 原控制方
    if side in s["deputies"]:
        s["deputies"].pop(side, None)
    for _pos, p in s["board"].items():
        if p.get("home") == side and p.get("army") == prev_owner:
            p["army"] = capturer_army
    s["annexed"][side] = capturer_army
    s["board"].pop(victim.get("_pos", ""), None)
    refresh_combat(s)
    return side


# ---------------------------------------------------------------- 行棋限制
# 兵的规则（只能前进不能后退、过界后可横走、只过一次界）
# 直接实现在 rules.py 的 _pawn() 里 —— 那里有领地判定与方向常量，放在一起更清楚。
