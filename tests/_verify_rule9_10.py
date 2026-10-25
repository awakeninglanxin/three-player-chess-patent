# -*- coding: utf-8 -*-
"""验证《一、9 帅不见面》+《一、10 帅被动见面》的引擎实现 —— **含 2026-09-25 的规则变更**。

原文（`docs/三人中国象棋的游戏规则.jpeg` 第 2 列）：

  9. 帅不见面：
     对战时，不可把己方帅和对手的帅（主帅和副帅）放在没有棋子阻隔的线路上（如图）
     【E5-A5-F5-J5】【J5-F5-K5-O5】【O5-K5-A5-E5】
     【E6-A6-F4-J4】【J6-F6-K4-O4】【O6-K6-A4-E4】上。
     己方两帅（主帅和副帅）可见面。在局方的帅可与出局方的帅见面。
     在局方 A 帅与出局方 B 帅相见时，C 不可吃 B 的帅。

  10. 帅被动见面：
     A 帅和 B 帅同在上述任一条仅有 C 棋阻隔的线路上，C 棋抽离，致使 A 帅、B 帅见面。
     此时 A 必须二选一：直接把 B 判负，但不控制 B 方棋子（A 在判负回合不再走棋）；
     或用自己的棋阻隔在两帅之间、或移开己方的帅，不把 B 判负。（走棋顺序：C⇒A）

  6. 出局方的棋子：
     三方对战，一方出局，另两方不能控制出局方棋子，但可以根据棋理吃掉出局方棋子，
     直到出局方的帅被吃掉后，棋子归吃帅方控制。

═══ 2026-09-25 规则变更（老师定夺）═══
  · **「照见即可射杀」上线** —— 帅 / 副帅沿跨方贯通纵线（列4/5/6）扫描，
    遇见的第一个子若是对方帅 / 副帅，即可远程吃掉（吃子语义 = 该方出局 + 残兵易主）。
  · **第 10 条整体退役** —— 照面从"违规禁忌"变成"**互为人质**（轮到谁，谁能吃）"，
    不再存在"A 被迫二选一"的待决局面。
    ⇒ `pending_judge()` 恒 None；`judge_lose()` 失去触发途径（函数保留供历史复盘）。
  · **第 9 条第 3 条改为「独占口径」** —— 只有【独占照见】的那一方才有资格吃 B 的帅；
    多方同时照见（如三点共线）时**谁都不得吃**。射杀同样受此约束。
  · 第 6 条、第 7 条（吃帅/易主/副帅）**不变** —— 本文件的第 4 节继续覆盖。

标签口径：图中数字 = 10 − 引擎列；字母 魏 A-E / 吴 K-O / 蜀 F-J（row5→row1）。
"""
import os
import sys

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "server"))
from engine import game_dxf as GA      # noqa: E402
from engine import rules_dxf as R      # noqa: E402
from engine import patent as P         # noqa: E402

CN = {1: "魏", 2: "吴", 3: "蜀"}
OK = FAIL = 0


def chk(name, cond, extra=""):
    global OK, FAIL
    if cond:
        OK += 1
        print(f"  [OK]   {name}" + (f"  {extra}" if extra else ""))
    else:
        FAIL += 1
        print(f"  [FAIL] {name}  {extra}")


def pc(kind, home, army=None):
    return {"kind": kind, "army": army or home, "home": home}


def mk(board, turn=1, out=(), vitality=None):
    s = GA.new_game(first=turn)
    s["board"] = {k: dict(v) for k, v in board.items()}
    s["eliminated"] = list(out)
    s["out"] = list(out)
    s["annexed"] = {}
    s["history"] = []
    s["passed"] = []
    s["ply"] = 0
    if vitality:
        s["vitality"].update(vitality)
    P.refresh_combat(s)
    return s


los = lambda s, a, b: R.line_of_sight(s, a, b)
strict = lambda s: GA.facing_pairs(s, strict=True)

print("=" * 76)
print("0. 前置：线的形状（确认测试用的点位真的在同一条线上）")
print("=" * 76)
_path = next((p for p in R.RAYS.get("115", ()) if "315" in p), None)
chk("E5↔J5（115→315）是同一条贯通线", bool(_path), f"路径 {_path}")
# 复核：155 与 355 都在该线上；245 不在该线上但 在 O5↔E5 线上
chk("155 在该线上", (not _path) or ("155" in _path))
chk("355 在该线上", (not _path) or ("355" in _path))
_p3 = next((p for p in R.RAYS.get("215", ()) if "115" in p), None)
chk("O5↔E5（215→115）也是贯通线", bool(_p3), f"路径 {_p3}")
chk("245 在 O5↔E5 线上（可作 line3 的阻隔）", (not _p3) or ("245" in _p3))

# ---------------------------------------------------------------------------
print()
print("=" * 76)
print("1. 【2026-09-25 新规则】抽离阻隔子后双方照见 ⇒ 互相能射杀（《一、10》已退役）")
print("=" * 76)
# 局面：三帅齐全；邻方之间三条线各由「吴」的子挡着
#   line1 115-…-355-…-315 ：吴車 355 挡（**仅有 C=吴 的子**，符合原文）
#   line2 315-…-245-…-215 ：吴兵 245 挡
#   line3 215-…-245-…-155-…-115 ：吴兵 245 挡
#   另给蜀一枚車 116，用于第 3 节验证「出局方帅被吃」
BOARD = {"115": pc(R.GENERAL, 1), "215": pc(R.GENERAL, 2), "315": pc(R.GENERAL, 3),
         "355": pc(R.ROOK, 2),        # C=吴 的車，趴在蜀 row5 中点挡着 line1
         "245": pc(R.PAWN, 2),        # 吴兵，挡 line2 / line3
         "116": pc(R.ROOK, 3)}        # 蜀車，紧贴魏帅（第 4 节用）
sA = mk(BOARD, turn=2)
chk("前提：三个帅当前互不照见（各有阻隔）", not strict(sA), f"{[sorted(p) for p in strict(sA)]}")
chk("前提：蜀帥315 与 魏帥115 确实同线、只是被吴車355 挡住",
    los(sA, "315", "115") is False and los(mk({k: v for k, v in BOARD.items() if k != "355"}, 2), "315", "115") is True)

lm_c = GA.legal_moves(sA, 2)
chk("C（吴）可以抽离阻隔子 355→354", ("355", "354") in lm_c,
    f"吴合法着法 {len(lm_c)} 步")
nxt = GA.clone(sA)
GA.apply(nxt, "355", "354")
chk("抽离后两帅照见（蜀315 ↔ 魏115）",
    frozenset(("315", "115")) in strict(nxt), f"{[sorted(p) for p in strict(nxt)]}")
chk("★ 抽离后轮到蜀方（A）", nxt["turn"] == 3, f"turn={CN[nxt['turn']]}")
chk("★《一、10》已退役：不再有「被动见面待决」状态", GA.pending_judge(nxt) is None,
    f"{GA.pending_judge(nxt)}")
chk("★ facing_pairs 的 strict 形参已中性化（两值等价）",
    [sorted(p) for p in GA.facing_pairs(nxt)] == [sorted(p) for p in GA.facing_pairs(nxt, strict=True)])
_sp = GA.snipe_pairs(nxt)
chk("★ 引擎识别出射杀关系（含 (315,115)）", ("315", "115") in _sp, f"{_sp}")
chk("★ 蜀帥315 的合法着法里出现射杀 315→115",
    ("315", "115") in GA.legal_moves(nxt, 3), f"蜀合法 {len(GA.legal_moves(nxt, 3))} 步")
chk("★ 互为人质：魏帥115 同样能射杀 315→ 即 (115,315) 在魏方着法表里",
    ("115", "315") in GA.legal_moves(nxt, 1), f"魏合法 {len(GA.legal_moves(nxt, 1))} 步")

# ---------------------------------------------------------------------------
print()
print("=" * 76)
print("2. 【新规则】照面不再违规 ⇒ 着法表不再有「必须消解见面」的过滤义务")
print("=" * 76)
lm_a = GA.legal_moves(nxt, 3)
chk("蜀（A）仍有解：可移开己方帅 315→314", ("315", "314") in lm_a, f"合法 {len(lm_a)} 步")
# 旧规则（《一、10》方案②）会把这些"与见面无关"的着法全部排除；现在不该排除。
#   取蜀車 116 沿本方 col6 向心推进的三步（与 line1 的见面完全无关）。
_unrelated = [("116", "126"), ("116", "136"), ("116", "146")]
_kept = [m for m in _unrelated if m in lm_a]
chk("★ 与见面无关的蜀車着法**不再**被排除（照面已非违规）",
    len(_kept) == len(_unrelated), f"保留 {_kept} / 共 {len(_unrelated)} 条")
# 反过来确认：合法着法里存在大量"走完之后依然照面"的着法 —— 不再被要求消解
_still = []
for f, t in lm_a:
    probe = GA.clone(nxt)
    GA._move_piece(probe, f, t)
    if any("315" in p for p in GA.facing_pairs(probe, strict=True)):
        _still.append((f, t))
chk("★ 合法着法里仍有「走完照样照面」的着法（不再强制消解）",
    len(_still) > 0, f"仍照面的着法 {len(_still)}/{len(lm_a)} 条，示例 {_still[:3]}")

# ---------------------------------------------------------------------------
print()
print("=" * 76)
print("3. 【新规则】「被动见面待决」状态退役；判负函数保留但仅供历史复盘")
print("=" * 76)
# 局面（只用 §9 的 line1 一条线制造见面）：
#   魏帥115 ─ line1 ─ 蜀帥315       ← 照面（新规则下 = 互为人质，不再是"违规/待决"）
#   蜀帥315 的 3 个军帐邻点是 314(J6) / 316(J4) / 325(I5)：
#     · 314、316 用自家兵堵死（旧规则下这是"蜀方无解 → 只能判魏负"的构造）
#   两枚蜀兵在自家 r1，只能朝 r2 走（324 / 326），救不了主帅（旧口径）
BD3 = {"115": pc(R.GENERAL, 1), "215": pc(R.GENERAL, 2), "315": pc(R.GENERAL, 3),
       "314": pc(R.PAWN, 3), "316": pc(R.PAWN, 3), "255": pc(R.PAWN, 2)}
sB = mk(BD3, turn=3)
chk("前提：全盘只有「魏帥115 ↔ 蜀帥315」一对照面",
    [sorted(p) for p in strict(sB)] == [["115", "315"]],
    f"{[sorted(p) for p in strict(sB)]}")
chk("★《一、10》退役：pending_judge 恒 None（不再识别待决）",
    GA.pending_judge(sB) is None, f"{GA.pending_judge(sB)}")
chk("★ 照面 = 互为人质：蜀帥315 能射杀魏帥115", ("315", "115") in GA.snipe_pairs(sB))
chk("★ 蜀方的着法表**不为**「消解见面」而收缩（仍有 315→325 等常规着法）",
    ("315", "325") in GA.legal_moves(sB, 3), f"蜀合法 {len(GA.legal_moves(sB, 3))} 步")
chk("★ judge_lose 函数仍保留（供历史对局复盘 / 外部集成显式调用）",
    callable(GA.judge_lose) and GA.judge_lose.__doc__ and "已退役" in GA.judge_lose.__doc__)
# _advance 的轮转逻辑：蜀方有资格 ⇒ 正常轮到，不被跳过
_c = GA.clone(sB)
_c["turn"] = 2                               # 假装 C（吴）刚走完
GA._advance(_c)
chk("★ _advance 正常轮转（蜀方有行棋资格，不被跳过）",
    _c["turn"] == 3 and 3 not in _c["passed"],
    f"turn={CN[_c['turn']]}  passed={_c['passed']}")

# 制造「魏方已失去资格但帥仍在盘上」的局面（供第 4 节）——显式调用保留的 judge_lose
n_before = sum(1 for q in sB["board"].values() if q["army"] == 1)
GA.judge_lose(sB, 1)
chk("判负后魏方失去行棋资格（out）", 1 in sB["out"], f"out={sB['out']}")
chk("★ 判负 ≠ 出局：`eliminated` 仍为空（出局的唯一途径是主帅被吃）",
    sB["eliminated"] == [], f"eliminated={sB['eliminated']}")
chk("判负记入 declared_lose", sB.get("declared_lose") == [1], f"{sB.get('declared_lose')}")
chk("★ 判负后不再轮到魏（alive_armies 已排除判负方）",
    1 not in GA.alive_armies(sB), f"alive={[CN[k] for k in GA.alive_armies(sB)]}")
chk("★ 判负不是吃帅：魏帥仍留在盘上", "115" in sB["board"]
    and sB["board"]["115"]["kind"] == R.GENERAL, f"{sB['board'].get('115')}")
n_after = sum(1 for q in sB["board"].values() if q["army"] == 1)
chk("★ 判负不转移棋子（A 不获得 B 的棋子）", n_after == n_before,
    f"判负前归魏 {n_before} 子 / 判负后 {n_after} 子")
chk("出局方战斗力为 False（不能行动），生命力尚存（帅还在）",
    sB["combat"][1] is False and sB["vitality"][1] is True,
    f"combat={sB['combat'][1]} vitality={sB['vitality'][1]}")
chk("判负消耗 A 的回合（轮到吴，不再轮到蜀）", sB["turn"] == 2, f"turn={CN[sB['turn']]}")

# ---------------------------------------------------------------------------
print()
print("=" * 76)
print("4. 《一、6》+《一、7》：出局方的帅被吃 → 残兵归吃帅方 + 生成副帅（语义未变）")
print("=" * 76)
sB["board"]["116"] = pc(R.ROOK, 3)                  # 蜀車，紧贴魏帥115（魏方 E4 点）
sB["board"]["145"] = pc(R.PAWN, 1)                  # 给魏留一枚残兵，验证易主
sB["turn"] = 3
lm_eat = GA.legal_moves(sB, 3)
chk("蜀車 116→115 可以吃掉出局方的帅", ("116", "115") in lm_eat,
    f"蜀合法 {len(lm_eat)} 步")
note = GA.apply(sB, "116", "115")
chk("记录为「斩主帅」（该方本就已失去资格）",
    note.get("captured") == R.GENERAL and note.get("eliminated") == 1, f"{note}")
chk("★ 帅被吃这一刻才真·出局（老师：出局的唯一途径是主帅被吃）",
    1 in sB["eliminated"] and sB["out"].count(1) == 1, f"out={sB['out']} eliminated={sB['eliminated']}")
_pawn = sB["board"].get("145")
chk("魏方残兵易主给蜀", bool(_pawn) and _pawn["army"] == 3, f"{_pawn}")
_dep = [(p, q) for p, q in sB["board"].items() if q.get("deputy")]
chk("魏方军帐内生成副帅、归蜀控制（吃帅的棋子就地升格）",
    len(_dep) == 1 and _dep[0][1]["army"] == 3 and _dep[0][1]["home"] == 1, f"{_dep}")
chk("副帅登记表 owner=蜀", sB["deputies"].get(1, {}).get("owner") == 3,
    f"{sB['deputies']}")
chk("棋子数守恒（吃帅的車离开原位、以副帅身份进驻）",
    "116" not in sB["board"], f"116 上还有 {sB['board'].get('116')}")

# ---------------------------------------------------------------------------
print()
print("=" * 76)
print("5. 《一、9》第 3 条：「独占照见」才准吃出局方的帅（★2026-09-25 独占口径★）")
print("=" * 76)
print("5a. 独占照见（只有一个在局方与出局方帥照见）⇒ 那一方放行、其余方禁吃")
# 局面：魏已出局、魏帥115 留盘；蜀帥315 与它照见（line1 无阻隔，**合法**，属豁免 2）
#   吴帥215 与 魏帥115 之间由吴兵245 挡着（否则吴也在见面，判定会混进来）
#   给吴一枚車在 116（与115相邻），给蜀一枚車在 114（也与115相邻）
BD = {"115": pc(R.GENERAL, 1), "215": pc(R.GENERAL, 2), "315": pc(R.GENERAL, 3),
      "245": pc(R.PAWN, 2), "116": pc(R.ROOK, 2), "114": pc(R.ROOK, 3)}
sC = mk(BD, turn=2, out=(1,), vitality={1: True})
chk("前提：魏已出局但帅仍在盘上", 1 in sC["out"] and "115" in sC["board"])
chk("前提：蜀帥315 与出局方魏帥115 照见", los(sC, "315", "115") is True)
chk("前提：此时不触发《一、10》（已退役，恒 None）", GA.pending_judge(sC) is None,
    f"{GA.pending_judge(sC)}")
guard = GA.protected_out_generals(sC)
chk("★ 独占照见：引擎标出「115 只许蜀吃」", guard.get("115") == frozenset({3}), f"{guard}")
lm_w = GA.legal_moves(sC, 2)
chk("★ C（吴）的車 116→115 被禁止", ("116", "115") not in lm_w,
    f"吴合法 {len(lm_w)} 步（含 116 的着法 "
    f"{[t for f, t in lm_w if f == '116']}）")
lm_s = GA.legal_moves(sC, 3)
chk("★ A（蜀）的車 114→115 允许", ("114", "115") in lm_s,
    f"蜀合法 {len(lm_s)} 步")
inp = GA.clone(sC)
GA.apply(inp, "114", "115")
chk("A 吃下后：吴同样不受益（残兵归蜀）",
    all(q["army"] != 2 or q.get("home") == 2 for q in inp["board"].values()),
    f"deputies={inp['deputies']}")

print()
print("5b. ★多方同时照见（三点共线）⇒ 谁都不得吃（独占口径的核心效果）")
# 三个帅同在列5、彼此无阻隔 ⇒ 魏帥115 被 吴帥215 与 蜀帥315 **同时**照见
BD2 = {"115": pc(R.GENERAL, 1), "215": pc(R.GENERAL, 2), "315": pc(R.GENERAL, 3)}
sD = mk(BD2, turn=2, out=(1,), vitality={1: True})
chk("前提：魏吳蜀三帥同在列5、两两照见",
    los(sD, "215", "115") and los(sD, "315", "115") and los(sD, "215", "315"))
chk("前提：115 的照见方有 2 家（吴 + 蜀）", len(GA.alive_armies(sD)) == 2)
guard2 = GA.protected_out_generals(sD)
chk("★ 多方争抢 ⇒ guard['115'] 为空集（谁都不得吃）",
    guard2.get("115") == frozenset(), f"{guard2}")
chk("★ 吴帥 215→115（射杀）被禁止", ("215", "115") not in GA.legal_moves(sD, 2),
    f"吴合法 {[m for m in GA.legal_moves(sD, 2) if m[1] == '115']}")
chk("★ 蜀帥 315→115（射杀）被禁止", ("315", "115") not in GA.legal_moves(sD, 3),
    f"蜀合法 {[m for m in GA.legal_moves(sD, 3) if m[1] == '115']}")
# 反向确认：不是"着法表被冻结" —— 两方都还有别的合法着法
chk("★ 并非整体冻结：吴方仍有其它合法着法（如 215→225）",
    len(GA.legal_moves(sD, 2)) > 1, f"{GA.legal_moves(sD, 2)[:4]}")

print()
print("=" * 52)
print(f"规则 9/10 专项验证: {OK} 通过 / {FAIL} 失败")
print("=" * 52)
sys.exit(1 if FAIL else 0)
