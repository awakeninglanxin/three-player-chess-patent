# -*- coding: utf-8 -*-
"""_verify_repeat_guard.py —— 「反复走同一条路径」专项验证（老师 2026-10-02 裁决）

老师原话：
    「长将判负：魏方反复走同一条路径（222-232）并且一直在将军，超过 3 次 →
      依传统中国象棋「长将判负」，该方失去行棋资格（帅留盘、棋子不易主，≠ 出局）
      **不对，为何魏方被判出局，你只要限制它不走重复路径就 ok 了**」

本门禁守三件事（缺一不可）：
  ① **事前拦截**：第 4 次重复**根本不在** `legal_moves` 里（不是走出去之后再判罚）；
  ② **绝不出局**：任何路径都不许写 `out` / `declared_lose` ——
     前端 `web/app.js` 把 `st.out` 渲染成「已出局」，
     而本项目「出局」的**唯一**触发条件是**主帅被吃**；
  ③ **不误伤**：没有重复记录 / 换了另一条边 / `repeat_limit=0` ⇒ 着法一个不少。

九节：① 判据表 ② 键兼容 ③ 真实棋局拦截 ④ 红线 ⑤ 逃生门
      ⑥ 源码级防复发 ⑦ 兜底判和 ⑧ 关规则 ⑨ 对局层文案
"""
import ast
import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "server"))
sys.path.insert(0, os.path.join(ROOT, "server", "engine"))

from engine import game_dxf as GA        # noqa: E402
from match import Match                  # noqa: E402

OK = 0
BAD = []


def chk(cond, msg, detail=""):
    global OK
    if cond:
        OK += 1
        print(f"  ✅ {msg}")
    else:
        BAD.append(msg)
        print(f"  ❌ {msg}" + (f"   ← {detail}" if detail else ""))


def sect(n, t):
    print(f"\n{'=' * 74}\n§{n}  {t}\n{'=' * 74}")


def code_only(src):
    """只留**可执行代码**：注释与 docstring 全部剔除

    ⚠️ 两样都必须去掉，少一样就会假失败：
      · `#` 注释里会写"以前叫 `repeat_lose`，为什么改掉"（说明沿革，必须留）；
      · **docstring 里直接引了老师的原话**，原话里就含「长将判负」「失去行棋资格」。
    只剥 `#` 注释是上一版写法，实测正是被 docstring 命中（见本轮失败记录）。
    """
    tree = ast.parse(src)
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if isinstance(body, list) and body:
            first = body[0]
            if (isinstance(first, ast.Expr)
                    and isinstance(first.value, ast.Constant)
                    and isinstance(first.value.value, str)):
                first.value.value = ""          # 只清 docstring（函数体第一条语句）
    return ast.unparse(tree)


def src_of(rel):
    return io.open(os.path.join(ROOT, rel), encoding="utf-8").read()


LIM = int(GA.REPEAT_LIMIT)
print(f"REPEAT_LIMIT = {LIM}（「超过三次」⇒ 允许走 {LIM} 次，第 {LIM + 1} 次不可选）")

# ========================================================================== ①
sect(1, "① 判据 `GA.repeat_blocked`：无向边 / 连续计数 / 上限边界（表驱动）")
CASES = [
    # (说明, rec, frm, to, lim, 期望被禁?)
    ("n=3 已走满 ⇒ 第 4 手必须被禁", {"edge": "222-232", "n": 3}, "232", "222", 3, True),
    ("n=3 已走满（同方向再来）⇒ 也禁", {"edge": "222-232", "n": 3}, "222", "232", 3, True),
    ("n=2 ⇒ 第 3 手仍然允许", {"edge": "222-232", "n": 2}, "222", "232", 3, False),
    ("n=1 ⇒ 允许", {"edge": "222-232", "n": 1}, "232", "222", 3, False),
    ("换了另一条边 ⇒ 连续被打断，不误禁",
     {"edge": "124-134", "n": 9}, "222", "232", 3, False),
    ("没有记录（开局）⇒ 不禁", None, "222", "232", 3, False),
    ("lim=0 ⇒ 整条规则关闭", {"edge": "222-232", "n": 9}, "222", "232", 0, False),
    ("lim=1 ⇒ 走满 1 次就禁第 2 次", {"edge": "222-232", "n": 1}, "232", "222", 1, True),
]
for desc, rec, frm, to, lim, want in CASES:
    s = {"repeat": {1: rec} if rec else {}, "repeat_limit": lim}
    got = GA.repeat_blocked(s, 1, frm, to)
    chk(got is want, desc, f"got={got} want={want}")

chk(GA.edge_key("222", "232") == GA.edge_key("232", "222") == "222-232",
    "★ `edge_key` 无向（`222-232` ≡ `232-222`）—— 老师现场就是**来回走**",
    f"{GA.edge_key('222', '232')} vs {GA.edge_key('232', '222')}")

# ========================================================================== ②
sect(2, "② `repeat_state` 键兼容：int 与 str 都要认（存档往返会变 str）")
_both = {"repeat": {1: {"edge": "a-b", "n": 2}}}
chk(GA.repeat_state(_both, 1) is not None, "int 键正常取到")
chk(GA.repeat_state({"repeat": {"1": {"edge": "a-b", "n": 2}}}, 1) is not None,
    "★ **str 键**也取得到（旧存档 / 引擎单测 / 手工构造 state 都可能是字符串键）")
chk(GA.repeat_blocked({"repeat": {"1": {"edge": "222-232", "n": 3}}, "repeat_limit": 3},
                      1, "222", "232") is True,
    "★ str 键时**拦截照样生效**（只认 int 会让计数凭空归零 ⇒ 长将又走得出来）")
chk(GA.repeat_state({}, 1) is None, "没有记录 ⇒ None（不抛错）")

# ========================================================================== ③
sect(3, "③ 真实棋局（走子全程过 `apply`）：魏方来往同一条边，第 4 手被拦")


def find_reversible_edge(s, army):
    """找一手 (a,b)：走完 a→b 后，(b,a) 仍是该方的合法着法"""
    for a, b in sorted(GA.legal_moves(s, army)):
        t = GA.clone(s)
        t["turn"] = army
        try:
            GA.apply(t, a, b)
        except Exception:                # noqa: BLE001
            continue
        t["turn"] = army
        if (b, a) in set(GA.legal_moves(t, army)):
            return a, b
    return None


s = GA.new_game(first=1)
pair = find_reversible_edge(s, 1)
chk(pair is not None, "能在魏方着法里找到一对可来回的边（场景前提）")
if pair:
    a, b = pair
    print(f"     选中：{a} ↔ {b}")
    hands = 0
    blocked_at = None
    for i in range(LIM + 3):
        if s["turn"] != 1:
            break
        frm, to = (a, b) if i % 2 == 0 else (b, a)
        if (frm, to) not in set(GA.legal_moves(s, 1)):
            blocked_at = i + 1
            break
        GA.apply(s, frm, to)
        hands += 1
        for _ in (2, 3):                 # 陪跑：另两方各走一手
            lg = GA.legal_moves(s, s["turn"])
            if not lg:
                break
            GA.apply(s, *lg[0])
    chk(hands == LIM, f"★ 恰好走满 {LIM} 次（不多走一手）", f"实际 {hands} 手")
    chk(blocked_at == LIM + 1,
        f"★ 第 {LIM + 1} 手被**事前拦住**（`legal_moves` 里没有它）", f"blocked_at={blocked_at}")
    rec = GA.repeat_state(s, 1) or {}
    chk(int(rec.get("n") or 0) == LIM,
        f"重复计数停在 {LIM}（不再涨到 {LIM + 1}）", f"rec={rec}")

    # ====================================================================== ④
    sect(4, "④ ★★ 红线：任何路径都不许写 `out` / `declared_lose`")
    chk(1 not in (s.get("out") or []),
        "魏方**不在** `out` 里 ⇒ 网页不会显示「魏方已出局」", f"out={s.get('out')}")
    chk(1 not in (s.get("declared_lose") or []),
        "魏方**不在** `declared_lose` 里", f"declared_lose={s.get('declared_lose')}")
    chk(not GA.repeat_draw(s),
        "对局**照常继续**（没有因重复判和/判负而结束）", f"repeat_draw={GA.repeat_draw(s)}")
    chk(bool(GA.legal_moves(s, 1)),
        "★ 魏方仍有其它合法着法（只是不能再走那条重复边）",
        f"{len(GA.legal_moves(s, 1))} 着")
    chk(s["turn"] in (1, 2, 3) and 1 not in (s.get("passed") or []),
        "魏方没有被记成「停走」", f"passed={s.get('passed')}")

    # ====================================================================== ⑤
    sect(5, "⑤ 逃生门 `skip_repeat=True`：只给内部判定与测试用，能拿到未过滤集合")
    _all = set(GA.legal_moves(s, 1, skip_repeat=True))
    _flt = set(GA.legal_moves(s, 1))
    chk(_flt <= _all,
        "过滤后集合是未过滤集合的**子集**（没有凭空多出来的着法）")
    chk(len(_all) >= len(_flt) + 1,
        "★ 未过滤集合**严格更大**（少掉的那几手正是被重复规则拦下的）",
        f"未过滤 {len(_all)} / 过滤后 {len(_flt)}")

# ========================================================================== ⑥
sect(6, "⑥ 源码级防复发：重复规则的判负路径必须**整段消失**")
_g = code_only(src_of("server/engine/game_dxf.py"))
_m = code_only(src_of("server/match.py"))
chk("repeat_lose" not in _g, "`game_dxf.py` 代码里已无 `repeat_lose`（判负标记）")
chk("repeat_lose" not in _m, "`match.py` 代码里已无 `repeat_lose`")
chk("def repeat_strike" not in _g,
    "`repeat_strike`（会写 `out` 的那个函数）已整体删除")
# ★ 只盯**重复规则那一段**：`declared_lose` / `out` 在本文件里还有合法来源
#   （`judge_lose`《一.10》判负，已退役但函数体保留给复盘/外部集成），
#   全局断言会误伤 —— 上一版就是这么假失败的。
_i0 = _g.index("def repeat_blocked")
_i1 = _g.index("def repeat_draw")
_seg = _g[_i0:_i1]
chk("append" not in _seg,
    "★ 重复规则那一段（`repeat_blocked` / `repeat_stuck`）里**没有任何 `append`**"
    " ⇒ 结构上就不可能往 `out` / `declared_lose` 里塞人",
    f"片段长度 {len(_seg)}")
chk("out" in _seg and "s.get('out')" in _seg,
    "（该段确实提到过 `out` —— 但只用于「已出局方不算 stuck」的**读**，不写）")
chk("allowed = guard.get(to)" in _g,
    "§9 第 3 条（第三方不得吃照面中的出局方帅）**仍然在**（本次没有误删）")
chk("def judge_lose" in _g,
    "《一.10》的 `judge_lose` 仍在（本次只动重复规则，没有连带删除别的规则）")

# ========================================================================== ⑦
sect(7, "⑦ 兜底：某方「除重复外无路可走」⇒ 判「不变作和」（**绝不判负**）")
#   ⚠️ 这种局面在真实棋局里极难自然构造（要求"该方所有着法都只剩那条重复边"），
#      所以这里用**桩**把条件摆出来，专测这段逻辑本身。
_real_lm = GA.legal_moves
s7 = GA.new_game(first=1)
#   ★ 必须用**别人**（吴方）的一手来触发检查，不能让魏方自己走 ——
#     魏方一走，`note_repeat` 就会把它的连续计数重置（换了边 ⇒ 从 1 起算），
#     `repeat_stuck` 立刻变 False。这正是"走不动的那方自己开不了口"的写照，
#     也是 `apply` 里那段兜底必须**遍历所有在局方**而不能只查 `s["turn"]` 的原因。
mv7 = _real_lm(s7, 2)[0]
s7["repeat"] = {1: {"edge": "111-121", "n": LIM, "check": LIM}}
s7["turn"] = 2                                        # 轮到吴方 ⇒ 走完由 apply 兜底检查


def _fake_lm(s, army=None, frozen=None, skip_repeat=False):
    return [("111", "121")] if skip_repeat else []


GA.legal_moves = _fake_lm
try:
    chk(GA.repeat_stuck(s7, 1) is True,
        "★ `repeat_stuck(魏)` = True（过滤后空、不过滤非空 ⇒ 除重复外无路可走）")
    chk(GA.repeat_stuck(s7, 2) is False,
        "吴方没有到上限的重复记录 ⇒ **不**算 stuck（不连坐）")
    s7["repeat"] = {1: {"edge": "111-121", "n": 1, "check": 0}}
    chk(GA.repeat_stuck(s7, 1) is False,
        "计数没到上限 ⇒ 早退 False（不触发昂贵的 legal 计算）")
    s7["repeat"] = {1: {"edge": "111-121", "n": LIM, "check": 0}}
    s7["out"] = [1]
    chk(GA.repeat_stuck(s7, 1) is False,
        "已出局/失去资格的方不算 stuck（那是出局的事，与重复无关）")
    s7["out"] = []
    note7 = GA.apply(s7, *mv7)
    chk(s7.get("repeat_draw") is True,
        "★ 走完这一手后对局被置 `repeat_draw`（不变作和）", f"{s7.get('repeat_draw')}")
    chk(note7.get("repeat_draw") is True and note7.get("repeat_army") == 1,
        "战报标记写明是**哪一方**无路可走", f"{note7.get('repeat_army')}")
    chk(1 not in (s7.get("out") or []),
        "★★ 兜底路径也**绝不**把该方写进 `out`（这是老师这次的核心诉求）",
        f"out={s7.get('out')}")
    chk(not (s7.get("declared_lose") or []),
        "兜底路径也不写 `declared_lose`", f"{s7.get('declared_lose')}")
finally:
    GA.legal_moves = _real_lm

# ========================================================================== ⑧
sect(8, "⑧ `repeat_limit = 0` ⇒ 整条规则关闭（回到「想怎么走就怎么走」）")
s8 = GA.new_game(first=1)
s8["repeat_limit"] = 0
pair8 = find_reversible_edge(s8, 1)
if pair8:
    a8, b8 = pair8
    n8 = 0
    for i in range(LIM + 2):
        frm, to = (a8, b8) if i % 2 == 0 else (b8, a8)
        if (frm, to) not in set(GA.legal_moves(s8, 1)):
            break
        GA.apply(s8, frm, to)
        n8 += 1
        for _ in (2, 3):
            lg = GA.legal_moves(s8, s8["turn"])
            if not lg:
                break
            GA.apply(s8, *lg[0])
    chk(n8 == LIM + 2,
        f"关闭后可以走超过 {LIM} 次（未被拦）", f"实际 {n8} 手")
    chk(1 not in (s8.get("out") or []),
        "★ 关闭状态下**更不会**判负/写 out（旧写法这里会判和，现在什么都不做）",
        f"out={s8.get('out')} repeat_draw={GA.repeat_draw(s8)}")
    chk(not GA.repeat_draw(s8),
        "关闭状态下也不判和（对局继续）", f"repeat_draw={GA.repeat_draw(s8)}")

# ========================================================================== ⑨
sect(9, "⑨ 对局层文案：`_note_repeat_verdict` 只产出「判和」，不再产出「判负」")
chk("repeat_army" in _m, "`match.py` 用 `repeat_army` 说清是哪一方无路可走")
chk("长将判负" not in _m, "★ 代码里已无「长将判负」的落判文案")
#   注意不能全局断言「失去行棋资格」——认输/接管那两处错误提示里用的正是这个词，
#   那是**正确用法**（真的失去资格了）。只盯这个函数体：
_r0 = _m.index("def _note_repeat_verdict")
_r1 = _m.index("def replay_at")
_rbody = _m[_r0:_r1]
chk("'judge'" not in _rbody,
    "★ `_note_repeat_verdict` 函数体内不再产出 `judge`（判负）战报", f"长度 {len(_rbody)}")
chk("'draw'" in _rbody, "该函数体只产出 `draw`（判和）战报")
chk("out" not in _rbody and "declared_lose" not in _rbody,
    "★ 该函数体里连 `out` / `declared_lose` 这两个词都不出现（结构上不可能写）")

m = Match.__new__(Match)                 # 只借方法，不跑 __init__（省掉整套依赖）
m.drawn = False
m.log = []
s9 = GA.new_game(first=1)
chk(Match._note_repeat_verdict(m, s9, {}) is False,
    "没有 `repeat_draw` 标记 ⇒ 返回 False，不改对局状态")
chk(m.drawn is False and m.log == [],
    "★ 空 note 不产生任何战报（普通的一手棋不会被误记成「重复判和」）")
r = Match._note_repeat_verdict(m, s9, {"repeat_draw": True, "repeat_army": 1,
                                       "repeat_edge": "222-232"})
chk(r is True and m.drawn is True, "有标记 ⇒ 置 `drawn` 并返回 True（对局结束）")
chk(len(m.log) == 1 and m.log[0]["type"] == "draw",
    "战报类型是 `draw`（判和），**不是** `judge`（判负）", f"{m.log}")
txt = (m.log[0].get("text") or "")
chk("222-232" in txt and "魏方" in txt,
    "战报写明是哪一方、哪条路径", txt)
chk("不变作和" in txt and "无着可走" in txt,
    "战报解释依据是「不变作和」，并说清触发前提", txt)

# ==========================================================================
print(f"\n{'=' * 74}")
print(f"「反复走同一条路径」专项验证：{OK} 通过 / {len(BAD)} 失败")
if BAD:
    for x in BAD:
        print("   •", x)
print("=" * 74)
sys.exit(1 if BAD else 0)
