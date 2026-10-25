# -*- coding: utf-8 -*-
"""三人象棋 · 对局状态机"""

import copy
from . import geometry as G
from . import patent as P
from . import rules as R

B = G.BOARD
TURN_ORDER = [1, 2, 3]


def new_game():
    s = {"board": {}, "turn": 1, "eliminated": [], "annexed": {},
         "history": [], "passed": [], "winner": None, "ply": 0}
    s.update(P.new_fields())          # 专利版：副帅 / 生命力 / 战斗力 / 出局
    for it in G.initial_position():
        s["board"][B.canon(it["pos"])] = {
            "kind": it["kind"], "army": it["army"], "home": it["army"]}
    return s


def clone(s):
    return copy.deepcopy(s)


def general_pos(s, army):
    """本方【主帅】位置。副帅 kind 也是 general 但其属于原方军帐，必须排除，
    否则主帅被吃后会误把副帅当成主帅，导致该方永远不出局。"""
    for pos, p in s["board"].items():
        if p["kind"] == R.GENERAL and p["home"] == army and not p.get("deputy"):
            return pos
    return None


def deputy_pos(s, side):
    """side 方军帐内的副帅点位（若有）"""
    d = s.get("deputies", {}).get(side)
    return d["pos"] if d else None


def alive_armies(s):
    return [k for k in TURN_ORDER if k not in s["eliminated"]]


def check_map(s, frozen=frozenset()):
    """谁是将军方、谁被将军"""
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
    """将军期间第三方停走"""
    cm = check_map(s)
    if not cm:
        return set()
    involved = set(cm) | {a for v in cm.values() for a in v}
    return set(alive_armies(s)) - involved


def legal_moves(s, army=None, frozen=None):
    army = army or s["turn"]
    frozen = frozen_now(s) if frozen is None else frozen
    if army in frozen:
        return []
    before = set(frozenset(p) for p in R.generals_facing(s))
    out = []
    for frm, to in R.side_moves(s, army, frozen):
        nxt = clone(s)
        _move_piece(nxt, frm, to, frozen)
        if set(frozenset(p) for p in R.generals_facing(nxt)) - before:
            continue                                   # 不可主动让帅见面（专利版同样禁止）
        if general_pos(nxt, army) is None:
            continue                                   # 本方主帅已失，轮不到它走
        # 专利版：三方对战【允许己方送将 / 不应将】，故此处不做"不许送将"过滤。
        # （双方对战仍不允许送将，留作二人模式的开关）
        out.append((frm, to))
    return out


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
            # 专利版：主帅被吃 -> 残兵归吃帅方并生成副帅（不是标准版的立即收编）
            P.on_general_captured(s, victim, piece["army"])
    return victim


def _deputy_captured(s, victim, capturer):
    """副帅被吃：残兵易主给吃副帅者，原控制方失去副帅的战斗力。
    专利版原文：副帅被吃，主帅和生命力不受影响，但失去副帅的战斗力。"""
    side = victim["home"]                 # 副帅代表的原方
    prev = victim["army"]                 # 原控制方
    s["deputies"].pop(side, None)
    for _p, q in s["board"].items():
        if q.get("home") == side and q.get("army") == prev:
            q["army"] = capturer
    s["annexed"][side] = capturer
    P.refresh_combat(s)


def apply(s, frm, to, frozen=None):
    """执行一步并推进回合；返回本步说明"""
    frozen = frozen_now(s) if frozen is None else frozen
    actor = s["turn"]
    victim = _move_piece(s, frm, to, frozen)
    note = {"from": frm, "to": to, "army": actor,
            "captured": victim["kind"] if victim else None,
            "captured_army": victim["home"] if victim else None}
    if victim and victim["kind"] == R.GENERAL:
        note["eliminated"] = victim["home"]
    _advance(s)
    alive = alive_armies(s)
    if len(alive) == 1:
        s["winner"] = alive[0]
    return note


def _advance(s):
    """推进到下一个有子可走的方；不要则记为停走"""
    alive = alive_armies(s)
    for _ in range(len(TURN_ORDER) * 2 + 3):
        i = TURN_ORDER.index(s["turn"])
        s["turn"] = TURN_ORDER[(i + 1) % len(TURN_ORDER)]
        if s["turn"] not in alive:
            continue
        if s["winner"]:
            return
        if legal_moves(s, s["turn"]):
            return
        s["passed"].append(s["turn"])                  # 停走一次


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
        "tent": {str(k): P.TENT[k] for k in (1, 2, 3)},
    }


KIND_CN = {R.ROOK: "車", R.HORSE: "馬", R.ELEPHANT: "象", R.ADVISOR: "士",
           R.GENERAL: "帥", R.CANNON: "炮", R.PAWN: "兵"}
ARMY_CN = {1: "魏", 2: "蜀", 3: "吴"}


def render_text(s, legal=None):
    """给 LLM 看的纯文本局面（坐标使用名义点位，角落给出别名）"""
    rows = []
    for k in TURN_ORDER:
        items = []
        for pos in sorted(s["board"]):
            p = s["board"][pos]
            if p["army"] != k:
                continue
            ch = ARMY_CN[p["home"]] + KIND_CN[p["kind"]]
            tagn = "" if p["home"] == p["army"] else "(收编)"
            alias = B.aliases.get(pos)
            items.append(f"{pos}{'/' + alias if alias else ''}={ch}{tagn}")
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
    if st["eliminated"]:
        head.append("已出局：" + "、".join(f"{ARMY_CN[a]}（残兵归{ARMY_CN[st['annexed'][a]]}）"
                                          for a in st["eliminated"]))
    body = ["局面棋子（点位 id：首位=所属方 1魏 2蜀 3吴，次位=行 1底线..5河线，末位=列 1右..9左）", *rows]
    tail = []
    if s["history"]:
        tail.append("最近着法：" + "  ".join(s["history"][-8:]))
    if legal is not None:
        tail.append(f"你方合法着法共 {len(legal)} 步，下面给出全部合法着法：")
        tail.append("  " + " ".join(f"{a}-{b}" for a, b in legal))
    return "\n".join(head + [""] + body + ([""] + tail if tail else []))
