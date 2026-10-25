# -*- coding: utf-8 -*-
"""
⚠️【本文件已废弃】活代码 = `server/engine/rules_dxf.py`（基于老师给的 DXF 工程图）。
   本文件按"60° 三角网格 + 6 邻域"建模（马步写成 12 步），与 DXF 实测不符：
   DXF 里每个内部点只有 4 个邻居 → 4 连通四边形网格 → 马步 = **传统「日」8 步**。
   保留仅供历史参照，请勿引用。

三人象棋 · 走子规则（鼎棋 / 三人中国象棋）

子力走法（依鼎棋原文 + 象棋屋口径）
    車  沿三条直线（A 0° / B 60° / C 120°）任意距离，遇子停
    炮  同車但不动子时不能吃；吃子须隔且仅隔一子（炮架）
    馬  走"双菱日"，共 12 步： (Δr,Δc) 满足 dr²+dc²+dr·dc = 7
        蹩马腿 = 该步"倍向"前进一步被占（实测 112→141、112→133 马腿都是 122）
    象  沿直线走两点（塞象眼 = 中间点被占），不过河（限本方领地），不进王宫
    士  每步一格，限王宫内
    帥  步法同士（帅/將/王）
    兵  每步一格；过河前只能沿两个前方方向前进；过河后可横行/后退，
        但不能退回本方河界；过河点仅限三处角落（151/251/351，中央三角区三顶点）

约定：所有生成函数签名统一为 (s, pos, home, army, frozen)
      s      = 局面 {"board": {pos: {"kind","army","home"}}, ...}
      pos    = 该子当前点位
      home   = 该子的"本籍"（决定走法坐标系与王宫/领地）
      army   = 当前操控方（收编后可能与 home 不同）
      frozen = 停走方集合：其子不可被通过、不可被吃
"""

from . import geometry as G

B = G.BOARD

ROOK, HORSE, ELEPHANT, ADVISOR, GENERAL, CANNON, PAWN = (
    "rook", "horse", "elephant", "advisor", "general", "cannon", "pawn")

KIND_ORDER = [ROOK, HORSE, ELEPHANT, ADVISOR, GENERAL, CANNON, PAWN]


def _rot120(a, b):
    return (-a - b, a)


def forward_deltas(army):
    """某方"前方"在格坐标下的两个方向（过河前兵只能走这两个）"""
    ds = [(0, 1), (-1, 1)]
    for _ in range(army - 1):
        ds = [_rot120(*d) for d in ds]
    return ds


def step(pos, delta):
    return B.movenb.get((pos, delta))


def _can_land(s, army, frozen, q):
    """空点可落；敌子可吃；停走方棋子不可吃"""
    p = s["board"].get(q)
    if p is None:
        return True
    if p["army"] == army:
        return False
    return p["army"] not in frozen


# ---------------------------------------------------------------- 单子走法

def _rook(s, pos, home, army, frozen):
    out = []
    for seg in B.lines_through(pos).values():
        i = seg.index(pos)
        for rng in (range(i + 1, len(seg)), range(i - 1, -1, -1)):
            for k in rng:
                q = seg[k]
                if s["board"].get(q) is None:
                    out.append(q)
                    continue
                if _can_land(s, army, frozen, q):
                    out.append(q)
                break
    return out


def _cannon(s, pos, home, army, frozen):
    out = []
    for seg in B.lines_through(pos).values():
        i = seg.index(pos)
        for rng in (range(i + 1, len(seg)), range(i - 1, -1, -1)):
            jumped = False
            for k in rng:
                q = seg[k]
                occ = s["board"].get(q)
                if not jumped:
                    if occ is None:
                        out.append(q)
                        continue
                    jumped = True            # 此子即炮架
                    continue
                if occ is None:
                    continue
                if _can_land(s, army, frozen, q):
                    out.append(q)
                break
    return out


def _horse(s, pos, home, army, frozen):
    """12 步双菱日；蹩马腿点位 = 倍向前进一步"""
    out = []
    rc = _rc_of(pos, home)
    if rc is None:
        return out
    for mv in G.HORSE_MOVES:
        leg = G.HORSE_LEGS[mv]
        leg_pos = _pos_of(home, (rc[0] + leg[0], rc[1] + leg[1]))
        if leg_pos is not None and s["board"].get(leg_pos) is not None:
            continue                                  # 蹩马腿
        tgt = _pos_of(home, (rc[0] + mv[0], rc[1] + mv[1]))
        if tgt is not None and _can_land(s, army, frozen, tgt):
            out.append(tgt)
    return out


def _elephant(s, pos, home, army, frozen):
    """走两点，塞象眼；限本方领地，不进王宫"""
    out = []
    for seg in B.lines_through(pos).values():
        i = seg.index(pos)
        for d in (2, -2):
            j = i + d
            if not (0 <= j < len(seg)):
                continue
            if s["board"].get(seg[i + d // 2]) is not None:
                continue                              # 塞象眼
            tgt = seg[j]
            if tgt not in B.territory[home] or tgt in B.palace[home]:
                continue
            if _can_land(s, army, frozen, tgt):
                out.append(tgt)
    return out


def _one_step(s, pos, home, army, frozen, allowed):
    out = []
    for d in G.UNIT_DIRS:
        q = step(pos, d)
        if q is None or q not in allowed:
            continue
        if _can_land(s, army, frozen, q):
            out.append(q)
    return out


def _advisor(s, pos, home, army, frozen):
    return _one_step(s, pos, home, army, frozen, B.palace[home])


def _general(s, pos, home, army, frozen):
    return _one_step(s, pos, home, army, frozen, B.palace[home])


def _pawn(s, pos, home, army, frozen):
    """专利版兵：每回合直线移一格，【只能前进不能后退】；
    过界前不能横走，过界后可横走；且不得退回本方河界（即只能过一次界）。"""
    out = []
    fwd = forward_deltas(home)
    crossed = pos not in B.territory[home]
    if crossed:
        back = [(-d[0], -d[1]) for d in fwd]      # 两个"后退"方向
        dirs = [d for d in G.UNIT_DIRS if d not in back]   # 前方 + 横向
    else:
        dirs = list(fwd)                          # 过界前：只许两个前方方向
    for d in dirs:
        q = step(pos, d)
        if q is None:
            continue
        if crossed and q in B.territory[home]:
            continue                              # 不得退回本方河界
        if _can_land(s, army, frozen, q):
            out.append(q)
    return out


_GEN = {ROOK: _rook, HORSE: _horse, ELEPHANT: _elephant,
        ADVISOR: _advisor, GENERAL: _general, CANNON: _cannon, PAWN: _pawn}

_RC_MAP = {}


def _rc_map(home):
    if home not in _RC_MAP:
        m = {}
        for pid, per in B.nominal.items():
            if home in per:
                m[per[home]] = pid
        _RC_MAP[home] = m
    return _RC_MAP[home]


def _rc_of(pos, home):
    """点位在本方坐标系下的 (行, 列)；角落点两方都能索引"""
    per = B.nominal.get(pos, {})
    return per.get(home)


def _pos_of(home, rc):
    return _rc_map(home).get(rc)


# ---------------------------------------------------------------- 汇总

def pseudo_moves(s, pos, frozen=frozenset()):
    p = s["board"][pos]
    return _GEN[p["kind"]](s, pos, p["home"], p["army"], frozen)


def side_moves(s, army, frozen=frozenset()):
    out = []
    for pos, p in s["board"].items():
        if p["army"] != army:
            continue
        for t in pseudo_moves(s, pos, frozen):
            out.append((pos, t))
    return out


def attacked(s, target, by_armies, frozen=frozenset()):
    """target 是否被 by_armies 中任一方攻击"""
    for pos, p in s["board"].items():
        if p["army"] not in by_armies:
            continue
        if target in pseudo_moves(s, pos, frozen):
            return True
    return False


def generals_facing(s):
    """互相"见面"的帅对（同一直线上、中间无子）

    专利版：副帅不参与"见面"判定 —— 「己方两帅（主帅和副帅）可见面」，
    且「在局方的帅可与出局方的帅见面」，所以这里只算主帅。
    """
    gens = [(pos, p) for pos, p in s["board"].items()
            if p["kind"] == GENERAL and not p.get("deputy")]
    out = []
    for i, (pa, a) in enumerate(gens):
        for pb, b in gens[i + 1:]:
            if a["army"] == b["army"]:
                continue
            for seg in B.lines_through(pa).values():
                if pb not in seg:
                    continue
                lo, hi = sorted((seg.index(pa), seg.index(pb)))
                if all(seg[k] not in s["board"] for k in range(lo + 1, hi)):
                    out.append((pa, pb))
    return out
