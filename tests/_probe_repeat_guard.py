# -*- coding: utf-8 -*-
"""_probe_repeat_guard.py —— 「反复走同一条路径」该怎样处理？**平行判据探针**

老师 2026-10-02 的裁决（原话）：
    「长将判负：魏方反复走同一条路径（222-232）并且一直在将军，超过 3 次 →
      依传统中国象棋「长将判负」，该方失去行棋资格（帅留盘、棋子不易主，≠ 出局）
      **不对，为何魏方被判出局，你只要限制它不走重复路径就 ok 了**」

⇒ 期望行为（本探针要证的）：
    ① 反复走同一条路径，到**第 4 次**时，那一手**根本不该出现在合法着法里**
       （= 事前拦截，而不是"走出去之后再判罚"）；
    ② 无论怎么走，都**绝不把该方写进 `out`** ——
       前端 `web/app.js` 把 `st.out` 直接渲染成「已出局」，
       而「出局」在本项目的唯一触发条件是**主帅被吃**，不是这条规则。

本探针**不 import 源码里的新函数**（它可能还不存在），自己独立实现一份判据
（`edge_key_ref` / `blocked_ref` / `count_ref`），再用**真实棋局**跑一遍
（走子全部经过 `game_dxf.apply`，与线上同一条链路），
最后对照"源码的 `legal_moves` 是否也遵守同一判据"。

⇒ 用法：**先跑本探针（改前应为红，证明断言有效），改完源码再跑（应为绿）**。
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "server"))
sys.path.insert(0, os.path.join(ROOT, "server", "engine"))

from engine import game_dxf as GA        # noqa: E402

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


# ============================================================ 独立判据（平行实现）
#   下面是**照老师口径重写**的一份，不引用源码的任何函数。
#   规则只有三条：无向边 / 同一方连续 / 超过上限即禁。


def edge_key_ref(frm, to):
    """无向边：`222-232` 与 `232-222` 必须算**同一条**路径

    为什么必须无向：老师现场看到的就是"同一个棋子来回走"，
    按有序 (from→to) 去数，来回一趟就是两条不同的着法，永远凑不满次数。
    """
    return f"{frm}-{to}" if str(frm) <= str(to) else f"{to}-{frm}"


def count_ref(rec, frm, to):
    """按"该方上一次走的是不是同一条边"算出**本手之后**的连续计数"""
    if rec and rec.get("edge") == edge_key_ref(frm, to):
        return int(rec.get("n") or 1) + 1
    return 1


def blocked_ref(rec, frm, to, lim):
    """这一手会不会超限（True = 应当**被禁**）"""
    if int(lim) <= 0:                       # 0 = 关闭本条规则
        return False
    if not rec or rec.get("edge") != edge_key_ref(frm, to):
        return False
    return int(rec.get("n") or 0) + 1 > int(lim)


# ============================================================ 场景构造
LIM_DEFAULT = int(getattr(GA, "REPEAT_LIMIT", 3))


def find_reversible_edge(s, army):
    """找一手 (a, b)：该方走完 a→b 之后，**再走 b→a 仍然是合法着法**

    条件越干净越好：优先选"无人可拦"的那种（不涉及吃子、不涉及射杀）。
    """
    legal = set(GA.legal_moves(s, army))
    for a, b in sorted(legal):
        t = GA.clone(s)
        t["turn"] = army                    # ⚠️ apply 的走子方取自 s["turn"]
        try:
            GA.apply(t, a, b)
        except Exception:                   # noqa: BLE001
            continue
        t["turn"] = army                    # apply 会轮转，拨回来再问"该方还有哪些着法"
        if (b, a) in set(GA.legal_moves(t, army)):
            return a, b
    return None


def run_real_game(a, b, max_hands=6):
    """真实对局：让 `army=1` 在无向边 (a,b) 上来回走，其余方各走一手陪跑

    返回 (序列, 终局 state)；序列元素 = (第几手, frm, to, 是否在合法着法里)
    """
    s = GA.new_game(first=1)
    seq = []
    for i in range(max_hands):
        if s["turn"] != 1:
            break
        frm, to = (a, b) if i % 2 == 0 else (b, a)
        legal = set(GA.legal_moves(s, 1))
        inside = (frm, to) in legal
        seq.append((i + 1, frm, to, inside))
        if not inside:                      # 被拦住了 —— 正是我们要测的
            break
        GA.apply(s, frm, to)
        # 陪跑：吴、蜀 各走一手（只求他们别干扰魏方的这条边）
        for _ in (2, 3):
            lg = GA.legal_moves(s, s["turn"])
            if not lg:
                break
            GA.apply(s, *lg[0])
    return seq, s


# ============================================================ ① 判据本身
sect(1, "① 独立判据：无向边 / 连续计数 / 上限边界（不碰源码）")
chk(edge_key_ref("222", "232") == edge_key_ref("232", "222") == "222-232",
    "无向边：`222-232` ≡ `232-222`（来回走算同一条路径）",
    f"{edge_key_ref('222', '232')} vs {edge_key_ref('232', '222')}")
chk(edge_key_ref("234", "224") == "224-234",
    "无向边：数字大小顺序不影响 key（`234-224` → `224-234`）")

_rec3 = {"edge": "222-232", "n": 3, "check": 3}
chk(blocked_ref(_rec3, "232", "222", 3) is True,
    "★ n=3（已走满 3 次）⇒ 第 4 手**必须被禁**（老师：「超过 3 次」的口径）")
_rec2 = {"edge": "222-232", "n": 2, "check": 2}
chk(blocked_ref(_rec2, "222", "232", 3) is False,
    "n=2 ⇒ 第 3 手**仍然允许**（上限是 3，不是 3 就禁）")
chk(blocked_ref(_rec3, "222", "232", 0) is False,
    "`repeat_limit = 0` ⇒ 整条规则关闭（保留给只想观棋的场合）")
chk(blocked_ref({"edge": "124-134", "n": 9}, "222", "232", 3) is False,
    "换了**另一条**边 ⇒ 连续被打断，计数从 1 起算（不误禁无关着法）")
chk(blocked_ref(None, "222", "232", 3) is False,
    "该方还没有任何重复记录 ⇒ 不禁（开局不受影响）")
chk(count_ref({"edge": "222-232", "n": 2}, "232", "222") == 3,
    "计数：同一无向边再走一次 ⇒ n+1（来回走也累加）")
chk(count_ref({"edge": "222-232", "n": 2}, "111", "112") == 1,
    "计数：换了一条边 ⇒ 重置为 1")

# ============================================================ ② 真实棋局
sect(2, "② 真实棋局（走子全程过 `game_dxf.apply`）：魏方来往同一条边 4 次")
s0 = GA.new_game(first=1)
pair = find_reversible_edge(s0, 1)
if not pair:
    chk(False, "能在魏方着法里找到一对可来回的边（场景构造前提）")
else:
    a, b = pair
    print(f"     选中的无向边：{a} ↔ {b}   （魏方连走 `{a}-{b}` / `{b}-{a}`）")
    seq, s1 = run_real_game(a, b, max_hands=6)
    for i, frm, to, inside in seq:
        print(f"     第 {i} 手 {frm}→{to}  在合法着法里 = {inside}")
    n_inside = sum(1 for _, _, _, ok in seq if ok)
    rec = GA.repeat_state(s1, 1) or {}
    print(f"     最终 repeat 记录：{rec}   repeat_limit={LIM_DEFAULT}")

    chk(n_inside == LIM_DEFAULT,
        f"★ 恰好只能走满 {LIM_DEFAULT} 次 —— 第 {LIM_DEFAULT + 1} 手被**事前拦住**",
        f"实际走成 {n_inside} 手")
    chk(len(seq) >= LIM_DEFAULT + 1 and seq[LIM_DEFAULT][3] is False,
        f"★ 第 {LIM_DEFAULT + 1} 手**不在** `legal_moves` 里（事前拦截，而不是走出去再判罚）",
        f"seq={seq}")
    chk(int(rec.get("n") or 0) == LIM_DEFAULT,
        f"重复计数停在 {LIM_DEFAULT}（不再增长到 {LIM_DEFAULT + 1}）", f"rec={rec}")

    # ---- ③ 绝不能写 out ----
    sect(3, "③ ★ 红线：任何情况下都**不许**把该方写进 `out`（前端把 out 渲染成「出局」）")
    out = list(s1.get("out") or [])
    chk(1 not in out,
        "魏方**不在** `out` 里 ⇒ 网页不会显示「魏方已出局」", f"out={out}")
    chk(1 not in (s1.get("declared_lose") or []),
        "魏方**不在** `declared_lose` 里（判负清单也要干净）",
        f"declared_lose={s1.get('declared_lose')}")
    chk(bool(GA.legal_moves(s1, 1)),
        "★ 魏方**仍有合法着法**（只是不能再走那条重复边）—— 棋局照常继续",
        f"legal={len(GA.legal_moves(s1, 1))} 着")

    # ---- ④ 源码必须与独立判据一致 ----
    sect(4, "④ 源码的 `legal_moves` 必须遵守同一判据（逐点对照）")
    t = GA.clone(s1)
    t["turn"] = 1
    src_legal = set(GA.legal_moves(t, 1))
    # ⚠️ 只在源码**已支持** `skip_repeat`（= 改造已落地）时才做这一步严格对照。
    #   否则 `ref_legal` 会退化成 `src_legal` 自己、断言恒真 —— 那是**假绿灯**，
    #   比不做还坏（会让人以为"判据和源码一致"）。
    if "skip_repeat" in GA.legal_moves.__code__.co_varnames:
        ref_legal = set(GA.legal_moves(t, 1, skip_repeat=True))
        rec1 = GA.repeat_state(t, 1)
        ref_blocked = {mv for mv in ref_legal if blocked_ref(rec1, mv[0], mv[1], LIM_DEFAULT)}
        chk(src_legal == (ref_legal - ref_blocked),
            "源码 `legal_moves` == （未过滤集合 − 独立判据判定的「应当被禁」集合）",
            f"源码 {len(src_legal)} / 参照 {len(ref_legal)} / 应禁 {len(ref_blocked)}")
    else:
        chk(False, "源码 `legal_moves` 已提供 `skip_repeat` 逃生门（改造尚未落地）",
            "当前 `legal_moves` 的签名里没有 skip_repeat")

# ============================================================ 收尾
print(f"\n{'=' * 74}")
print(f"探针结果：{OK} 项符合预期 / {len(BAD)} 项不符合")
if BAD:
    print("\n不符合的项（= 期望行为尚未落地）：")
    for x in BAD:
        print("   •", x)
print("=" * 74)
sys.exit(1 if BAD else 0)
