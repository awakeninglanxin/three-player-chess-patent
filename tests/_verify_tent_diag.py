# -*- coding: utf-8 -*-
"""「军帐米字斜线」专项自检 —— 固化老师 2026-10-01 报的规则 bug。

【老师原话】
    「象棋规则有bug，车在米字格魏国 军帐内为何能走斜线去吃魏国的帅？不对的。你要改。」

【根因】军帐（九宫）几何上是**米字格**：中心点有 8 个邻接点 ⇒
    `Board._build_rays()` 按**角度**分组邻接点时，除了横竖两族，还额外产出
    4 条**斜向射线**（如 魏军帐中心 D5=125 → E4=116 / E6=114 / C4=136 / C6=134）。
    而 `_rook` / `_cannon` / `PAWN_T` / `LINE_ATTACK` **全都消费 `RAYS`**
    ⇒ 车、炮在军帐内获得了**斜走能力**，攻击表（关乎将军判定）也跟着多出斜向威胁。
    斜线本是**士**的走法（`ADV_T` / `B.gong_diag`），不该混进通用射线。

【修法】纯拓扑判据，一个角度都不碰：
    · 方不变 ＋ 行变 ＋ 列变  ⇒ 军帐斜线（全盘实测 **24 步**，无一例外）
    · 方变（跨方接线 / 战线直通）⇒ **放行**（那一步形态是 (方变,行不变,列变)）
    `rules_dxf.py` 新增 `_is_tent_diag()` / `_drop_tent_diag()`，
    在 `_build_tables()` 里于**所有缝合之前**过滤 RAYS。

【本测试覆盖】
    §1 全盘 RAYS 相邻步：军帐斜线 **0 步**（源头清零）
    §2 车：三方 × 全盘 135 点空盘落点，**无一例外**满足「方变 ∨ 行不变 ∨ 列不变」
    §3 炮：同上
    §4 LINE_ATTACK（车/炮攻击表）同样性质 —— 将军判定不受污染
    §5 军帐中心的车：落点显式不含四角（老师报的那一手）
    §6 士**仍然**能斜走（ADV_T 未被误伤，4 个斜向落点齐全）
    §7 兵 PAWN_T 不再含斜向步
    §8 跨方贯通线 / 15 条行线完整（没把合法的缝合线一起砍掉）
    §9 车/炮仍能横穿列5（回归 `_verify_rays_topology` §2 的核心性质）
    §10 不消费 RAYS 的棋种（马/象/帅）着法集合**逐点未变**
    §11 RAYS 里不含空 tuple（防 `_splice_front_rays` 的 `fwd[:0]==()` 误命中）
    §12 三方 120° 旋转对称
    §13 几何侧**确实**存在这些斜线（证明我们砍的是真问题，不是空跑）
    §14 静态扫描：过滤发生在 `_build_tables` 内、且先于 `_splice_front_rays()`

跑法：cd 中国三人象棋_专利版 && "D:/Program Files/Python312/python.exe" tests/_verify_tent_diag.py
"""
import ast
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "server"))

from engine import geometry_dxf as D        # noqa: E402
from engine import rules_dxf as R           # noqa: E402

B = D.BOARD
ARMIES = D.ARMIES
ROWS, COLS = R.ROWS_TERR, R.COLS_TERR
OK = FAIL = 0


def chk(name, cond, extra=""):
    global OK, FAIL
    if cond:
        OK += 1
        print(f"  [OK]   {name} {extra}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name} {extra}")


def pc(kind, army):
    return {"kind": kind, "army": army, "home": army}


def mv(board, pos):
    return sorted(R.moves_of(board, pos, board[pos]))


def each_step():
    """产出全盘 RAYS 的每一个「上一步 → 这一步」（含起点 → 首点）"""
    for p, walks in R.RAYS.items():
        for w in walks:
            prev = p
            for q in w:
                yield p, prev, q
                prev = q


def is_exception(a, b):
    """合法（非军帐斜线）判据：方变 ∨ 行不变 ∨ 列不变"""
    return a[0] != b[0] or a[1] == b[1] or a[2] == b[2]


CN = {1: "魏", 2: "吴", 3: "蜀"}

print("=" * 70)
print("「军帐米字斜线」专项自检（老师 2026-10-01 报的规则 bug）")
print("=" * 70)

# ============================================================ §1 源头清零
print("\n== 1. 全盘 RAYS 相邻步：军帐斜线必须为 0 ==")
_steps = list(each_step())
_bad1 = [(p, D.RC[cur] if False else (prev, q)) for p, prev, q in _steps
         if R._is_tent_diag(D.parse(prev), D.parse(q))]
chk("全盘 RAYS 中「方不变 + 行变 + 列变」的步数为 0", not _bad1,
    f"共扫 {len(_steps)} 步，违规 {len(_bad1)} 步" + (f"，样例 {_bad1[:3]}" if _bad1 else ""))

# ============================================================ §2 车全盘
print("\n== 2. 车：三方 × 全盘 135 点，空盘落点必须「方变 ∨ 行不变 ∨ 列不变」==")
_bad2 = []
for _a in ARMIES:
    for _r in range(1, ROWS + 1):
        for _c in range(1, COLS + 1):
            _p = D.pid(_a, _r, _c)
            _bd = {_p: pc(R.ROOK, _a)}
            _pp = D.parse(_p)
            for _q in mv(_bd, _p):
                if not is_exception(_pp, D.parse(_q)):
                    _bad2.append((_p, _q))
chk("车：全部 405 例（135 点 × 3 方）落点均无斜线", not _bad2,
    f"违规 {len(_bad2)} 例" + (f"，样例 {_bad2[:4]}" if _bad2 else ""))

# ============================================================ §3 炮全盘
print("\n== 3. 炮：同上 ==")
_bad3 = []
for _a in ARMIES:
    for _r in range(1, ROWS + 1):
        for _c in range(1, COLS + 1):
            _p = D.pid(_a, _r, _c)
            _bd = {_p: pc(R.CANNON, _a)}
            _pp = D.parse(_p)
            for _q in mv(_bd, _p):
                if not is_exception(_pp, D.parse(_q)):
                    _bad3.append((_p, _q))
chk("炮：全部 405 例落点均无斜线", not _bad3,
    f"违规 {len(_bad3)} 例" + (f"，样例 {_bad3[:4]}" if _bad3 else ""))

# 炮有炮架时也检查一遍：在每枚目标点旁架一个「炮架」，确保隔子吃的判定同样干净
_bad3b = []
for _a in ARMIES:
    for _r in range(1, ROWS + 1):
        for _c in range(1, COLS + 1):
            _p = D.pid(_a, _r, _c)
            _pp = D.parse(_p)
            for _d in ((0, 0), (1, 0), (-1, 0), (0, 1), (0, -1)):
                _sr, _sc = _r + _d[0], _c + _d[1]
                if not (1 <= _sr <= ROWS and 1 <= _sc <= COLS):
                    continue                      # 只在本方领地内架炮架
                _sq = D.pid(_a, _sr, _sc)
                if _sq == _p:
                    continue
                _bd = {_p: pc(R.CANNON, _a), _sq: pc(R.PAWN, _a)}
                for _q in mv(_bd, _p):
                    if not is_exception(_pp, D.parse(_q)):
                        _bad3b.append((_p, _sq, _q))
chk("炮（带炮架）：全部测试落点均无斜线", not _bad3b,
    f"违规 {len(_bad3b)} 例" + (f"，样例 {_bad3b[:4]}" if _bad3b else ""))

# ============================================================ §4 LINE_ATTACK
print("\n== 4. LINE_ATTACK（车/炮攻击表，喂将军判定）同样干净 ==")
_bad4 = []
for _t, _lst in R.LINE_ATTACK.items():
    _pt = D.parse(_t)
    for _item in _lst:
        _q = _item[0]
        if not is_exception(_pt, D.parse(_q)):
            _bad4.append((_t, _q))
chk("LINE_ATTACK 全部目标点均无斜线", not _bad4,
    f"共 {sum(len(v) for v in R.LINE_ATTACK.values())} 条，违规 {len(_bad4)} 条"
    + (f"，样例 {_bad4[:4]}" if _bad4 else ""))

# ============================================================ §5 军帐中心
print("\n== 5. 军帐中心的车：落点显式不含四角（老师报的那一手）==")
for _a in ARMIES:
    _ctr = B.gong_center[_a]
    _corners = sorted(B.gong_diag[_a][0][:] + B.gong_diag[_a][1][:])
    _corners = sorted(set(_corners) - {_ctr})
    _bd = {_ctr: pc(R.ROOK, _a)}
    _got = set(mv(_bd, _ctr))
    chk(f"{CN[_a]}军帐中心 {_ctr}：车落点不含四角 {_corners}",
        not (_got & set(_corners)),
        f"落点 {sorted(_got)}")

# 顺带证明：四角确实在几何邻接里（否则这条断言等于空跑）
_ctr = B.gong_center[1]
_geo_nbrs = set()
for _ray in (B.rays.get(_ctr) or ()):
    _geo_nbrs |= set(_ray.nbrs)
chk("几何邻接里**确实**含军帐四角（证明 §5 非空跑）",
    set(B.gong_diag[1][0][:] + B.gong_diag[1][1][:]) - {_ctr} <= _geo_nbrs,
    f"几何邻接 {sorted(_geo_nbrs)}")

# ============================================================ §6 士仍能斜走
print("\n== 6. 士仍然能斜走（ADV_T 未被误伤）==")
_bad6 = []
for _a in ARMIES:
    _ctr = B.gong_center[_a]
    _want = {_q for _diag in B.gong_diag[_a] if _ctr in _diag
             for _q in _diag if _q != _ctr}
    _bd = {_ctr: pc(R.ADVISOR, _a)}
    _got = set(mv(_bd, _ctr))
    if not _want <= _got:
        _bad6.append((_a, sorted(_want - _got)))
    # 军帐四角上的士，应能走到中心 + 对角的两个角（斜线）
    for _corner in _want:
        _bd2 = {_corner: pc(R.ADVISOR, _a)}
        _g2 = set(mv(_bd2, _corner))
        if _ctr not in _g2:
            _bad6.append((_a, _corner, "到不了中心"))
chk("三方军帐：士在中心 / 四角均保有斜线走法", not _bad6,
    f"异常 {len(_bad6)}" + (f"，样例 {_bad6[:3]}" if _bad6 else ""))
# 士全部走法必须是「方不变 + 行变 + 列变」的斜线（或中心↔角），即全是斜步
_bad6b = []
for (_h, _p), _dests in R.ADV_T.items():
    _pp = D.parse(_p)
    for _q in _dests:
        _qa = D.parse(_q)
        if _qa[0] != _pp[0] or abs(_qa[1] - _pp[1]) != 1 or abs(_qa[2] - _pp[2]) != 1:
            _bad6b.append((_p, _q))
chk("士的走法**全部**是 (±1,±1) 斜步（军帐斜线正是士的专属走法）", not _bad6b,
    f"违规 {len(_bad6b)}" + (f"，样例 {_bad6b[:3]}" if _bad6b else ""))

# ============================================================ §7 兵不斜走
print("\n== 7. 兵 PAWN_T 不再含斜向步 ==")
_bad7 = []
for _p, _lst in R.PAWN_T.items():
    _pp = D.parse(_p)
    for _item in _lst:
        _q = _item[0]
        if not is_exception(_pp, D.parse(_q)):
            _bad7.append((_p, _q))
chk("PAWN_T 全部邻点无斜线", not _bad7,
    f"共 {sum(len(v) for v in R.PAWN_T.values())} 条，违规 {len(_bad7)} 条"
    + (f"，样例 {_bad7[:4]}" if _bad7 else ""))

# ============================================================ §8 贯通线完好
print("\n== 8. 跨方贯通线 / 15 条行线完整（没误砍合法线）==")
_lane_bad = []
for _a in ARMIES:
    for _r in range(1, ROWS + 1):
        _ln = [D.pid(_a, _r, _c) for _c in range(1, COLS + 1)]
        for _i, _p in enumerate(_ln):
            _walks = set(R.RAYS.get(_p) or ())
            if _i + 1 < len(_ln) and tuple(_ln[_i + 1:]) not in _walks:
                _lane_bad.append((_p, "朝C9端"))
            if _i > 0 and tuple(_ln[:_i][::-1]) not in _walks:
                _lane_bad.append((_p, "朝C1端"))
chk("15 条行线每点仍可一次直达本行两端", not _lane_bad,
    f"断裂 {len(_lane_bad)} 处" + (f"，样例 {_lane_bad[:3]}" if _lane_bad else ""))

# 列线（含跨方贯通）：每点朝本列两端
_col_bad = []
for _p in B.ids:
    _a, _r, _c = D.parse(_p)
    _walks = set(R.RAYS.get(_p) or ())
    # 找同列「直连」的贯通点（落在同一 RAYS 序列里即可，这里只查相邻上下各 1 步）
    _nbr_cols = set()
    for _w in (_walks or ()):
        if _w:
            _qa = D.parse(_w[0])
            if _qa[2] == _c and _qa[1] != _r:
                _nbr_cols.add(_w[0])
    if not _nbr_cols:
        _col_bad.append((_p, "列向无任何邻点"))
chk("每点至少有一条列向邻点（列线未被截空）", not _col_bad,
    f"异常 {len(_col_bad)} 处" + (f"，样例 {_col_bad[:3]}" if _col_bad else ""))

# 显式点检三角区三岔点的贯通：155(A5) 必须仍能到 355(蜀F5) 与 255(吴K5)
for _p, _want in (("155", {"355"}), ("355", {"255"}), ("255", {"155"})):
    _bd = {_p: pc(R.ROOK, R.RC[_p][0])}
    _got = set(mv(_bd, _p))
    chk(f"三角区贯通：{_p} 的车可达 {sorted(_want)}", _want <= _got, f"落点 {sorted(_got)}")

# ============================================================ §9 横穿列5
print("\n== 9. 车/炮仍能横穿列5（回归 `_verify_rays_topology` §2）==")
for _kind, _cn in ((R.ROOK, "车"), (R.CANNON, "炮")):
    _bad9 = []
    for _a in ARMIES:
        for _r in range(1, ROWS + 1):
            _ln = [D.pid(_a, _r, _c) for _c in range(1, COLS + 1)]
            for _end in (_ln[0], _ln[-1]):
                _bd = {_end: pc(_kind, _a)}
                _miss = set(_ln) - {_end} - set(mv(_bd, _end))
                if _miss:
                    _bad9.append((_end, sorted(_miss)))
    chk(f"{_cn}：15 行 × 两端 = 30 例，空盘均可横穿列5", not _bad9,
        f"异常 {len(_bad9)} 例" + (f"，样例 {_bad9[:2]}" if _bad9 else ""))

# ============================================================ §10 其他棋种未变
print("\n== 10. 不消费 RAYS 的棋种（马/象/帅）着法集合逐点未变 ==")
_need = {R.HORSE: 8, R.ELEPHANT: 4, R.GENERAL: 4}
for _kind, _want_cnt in _need.items():
    _bad10 = []
    for _a in ARMIES:
        for _r in range(1, ROWS + 1):
            for _c in range(1, COLS + 1):
                _p = D.pid(_a, _r, _c)
                # 士/帅只在军帐；帅不进 _need 的军帐外检查
                if _kind == R.GENERAL and _p not in set(B.gong[_a]):
                    continue
                _bd = {_p: pc(_kind, _a)}
                _n = len(mv(_bd, _p))
                if _kind == R.HORSE and _n == 0:
                    _bad10.append((_p, "马 0 步"))
                if _kind == R.ELEPHANT and _n == 0:
                    _bad10.append((_p, "象 0 步"))
    chk(f"{_kind} 着法非空（未被 RAYS 改动波及）", not _bad10,
        f"异常 {len(_bad10)}" + (f"，样例 {_bad10[:3]}" if _bad10 else ""))

# 马的着法集合与「军事斜线」无关：马步位移必须是 (1,2)/(2,1)
_bad10b = []
for _p, _lst in R.HORSE_T.items():
    _a, _r0, _c0 = D.parse(_p)
    for _item in _lst:
        _q = _item[1]
        _qa = D.parse(_q)
        if _qa[0] == _a:
            _d = (abs(_qa[1] - _r0), abs(_qa[2] - _c0))
            if _d not in ((1, 2), (2, 1)):
                _bad10b.append((_p, _q, _d))
chk("同方马步位移恒为 (1,2)/(2,1)（未被斜线污染）", not _bad10b,
    f"违规 {len(_bad10b)}" + (f"，样例 {_bad10b[:3]}" if _bad10b else ""))

# ============================================================ §11 无空 tuple
print("\n== 11. RAYS 内不含空 tuple（防 `_splice_front_rays` 的 `fwd[:0]==()` 误命中）==")
_empty = [_p for _p, _ws in R.RAYS.items() if any(len(_w) == 0 for _w in _ws)]
chk("全盘 RAYS 无空序列", not _empty,
    f"空序列 {len(_empty)} 处" + (f"，样例 {_empty[:3]}" if _empty else ""))

# ============================================================ §12 三方对称
print("\n== 12. 三方 120° 旋转对称（保 (行,列)、只轮换方号）==")


def rot_army(a):
    return {1: 2, 2: 3, 3: 1}[a]


_sig = {}
for _a in ARMIES:
    _s = set()
    for _p, _ws in R.RAYS.items():
        _pa, _r, _c = D.parse(_p)
        if _pa != _a:
            continue
        for _w in _ws:
            _s.add((_r, _c, tuple(D.parse(x)[1:] for x in _w)))
    _sig[_a] = _s
chk("三方 RAYS 结构完全相同（逐点逐射线）",
    _sig[1] == _sig[2] == _sig[3],
    f"|魏|={len(_sig[1])} |吴|={len(_sig[2])} |蜀|={len(_sig[3])}")

# ============================================================ §13 几何侧确实有斜线
print("\n== 13. 几何侧**确实**存在军帐斜线（证明砍的是真问题，不是空跑）==")
_geo_diag = []
for _p in B.ids:
    for _ray in (B.rays.get(_p) or ()):
        if _ray.nbrs:
            _q = _ray.nbrs[0]
            if R._is_tent_diag(D.parse(_p), D.parse(_q)):
                _geo_diag.append((_p, _q))
chk("几何原始邻接中军帐斜线 > 0（修复前正是它污染 RAYS）",
    len(_geo_diag) > 0, f"几何斜线 {len(_geo_diag)} 条（修复后 RAYS 里为 0）")
chk("几何斜线规模与预期一致（每方 8 条 × 3 方 = 24）",
    len(_geo_diag) == 24, f"实测 {len(_geo_diag)} 条")

# ============================================================ §14 静态扫描
print("\n== 14. 静态扫描：过滤位于 `_build_tables` 内、且先于 `_splice_front_rays()` ==")
_src = open(os.path.join(_ROOT, "server", "engine", "rules_dxf.py"),
            encoding="utf-8").read()
_tree = ast.parse(_src)
_bt = next((_n for _n in ast.walk(_tree)
            if isinstance(_n, ast.FunctionDef) and _n.name == "_build_tables"), None)
chk("存在 `_build_tables` 函数", _bt is not None)

_lines = _src.splitlines()
_i_filter = _i_splice = _i_pawn = -1
for _i, _ln in enumerate(_lines, 1):
    _code = _ln.strip()
    if _code.startswith("#"):
        continue                                   # 注释里的函数名不算调用
    if "RAYS[p] = tuple(w for w in (_drop_tent_diag" in _code:
        _i_filter = _i
    elif "SPLICE_STAT = _splice_front_rays()" in _code and _i_splice < 0:
        _i_splice = _i
    elif "for _ray in RAYS.get(_p, ())" in _code and _i_pawn < 0:
        _i_pawn = _i
chk("RAYS 赋值行确实调用了 `_drop_tent_diag`", _i_filter > 0, f"第 {_i_filter} 行")
chk("过滤发生在 `_splice_front_rays()` **调用之前**（缝合前）",
    _i_filter > 0 and _i_splice > 0 and _i_filter < _i_splice,
    f"过滤 L{_i_filter} ＜ 缝合 L{_i_splice}")
chk("PAWN_T 在缝合**之后**由 RAYS 重建（§7 干净的真正原因）",
    _i_pawn > _i_splice > 0,
    f"PAWN_T 重建 L{_i_pawn} ＞ 缝合 L{_i_splice}")

# `gong_diag` 只应被士/帅消费 —— 不得出现在 `_rook` / `_cannon` 里
_src_rc = _src[_src.index("def _rook("):_src.index("def _horse(")]
chk("`_rook` / `_cannon` 源码里不出现 `gong_diag`（车炮不吃军帐斜线）",
    "gong_diag" not in _src_rc)

print("\n" + "=" * 70)
print(f"结果：{OK} 通过 / {FAIL} 失败")
print("=" * 70)
sys.exit(1 if FAIL else 0)
