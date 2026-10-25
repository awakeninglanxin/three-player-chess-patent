# -*- coding: utf-8 -*-
"""《一、3》回合与步数 + 人类接管 —— 老师 2026-09-24 两条口径。

《一、3》原文：
  「三方对战，一方走一步或走多步（按约定步数）为一回合，直到决出胜负；
    各方使完约定步数时轮转到下一方。」
  ⇒ `steps_per_turn` 默认 **1**（传统）；N = 一方连走 N 步后才轮转。

人类接管：
  「人类接管可任选一方，剩下两方或一方就是 bot 自动接管。」
  ⇒ `human_armies` = 由人走的方；其余方 Bot 自动走。
"""
import sys

sys.path.insert(0, "server")
from engine import game_dxf as GA      # noqa: E402
from engine import patent as P         # noqa: E402

OK = FAIL = 0


def chk(name, cond, extra=""):
    global OK, FAIL
    if cond:
        OK += 1
        print(f"  [OK]   {name}" + (f"  {extra}" if extra else ""))
    else:
        FAIL += 1
        print(f"  [FAIL] {name}  {extra}")


print("=" * 78)
print("1. 默认 = 1 步（传统口径：走一步即轮转）")
print("=" * 78)
s = GA.new_game(first=1)
chk("新开局 steps_per_turn = 1", s["steps_per_turn"] == 1, f"{s['steps_per_turn']}")
chk("新开局 turn_steps = 0", s["turn_steps"] == 0)
mv = GA.legal_moves(s, 1)[0]
GA.apply(s, *mv)
chk("走 1 步后立刻轮到吴（2）", s["turn"] == 2, f"turn={s['turn']}")
chk("turn_steps 复位为 0", s["turn_steps"] == 0, f"{s['turn_steps']}")

print()
print("=" * 78)
print("2. 约定步数 N=3：一方连走 3 步后才轮转")
print("=" * 78)
s2 = GA.new_game(first=1)
s2["steps_per_turn"] = 3
for i in (1, 2):
    m = GA.legal_moves(s2, 1)[0]
    GA.apply(s2, *m)
    chk(f"走完第 {i} 步后仍是魏方回合（turn=1）", s2["turn"] == 1,
        f"turn={s2['turn']} turn_steps={s2['turn_steps']}")
chk("回合内已走步数 = 2", s2["turn_steps"] == 2, f"{s2['turn_steps']}")
m = GA.legal_moves(s2, 1)[0]
GA.apply(s2, *m)
chk("走满第 3 步后轮转到吴（2）", s2["turn"] == 2,
    f"turn={s2['turn']} turn_steps={s2['turn_steps']}")
chk("轮转后 turn_steps 归零", s2["turn_steps"] == 0, f"{s2['turn_steps']}")
chk("ply 累计为 3（着法数照常计）", s2["ply"] == 3, f"{s2['ply']}")

print()
print("=" * 78)
print("3. 不落子的动作（判负 / 认输）不计入约定步数")
print("=" * 78)
s3 = GA.new_game(first=1)
s3["steps_per_turn"] = 3
m = GA.legal_moves(s3, 1)[0]
GA.apply(s3, *m)                       # turn_steps = 1
chk("前提：本回合已走 1 步", s3["turn_steps"] == 1, f"{s3['turn_steps']}")
GA.resign(s3, 1)
chk("认输后置 turn_steps = 0（认输不落子）", s3["turn_steps"] == 0,
    f"{s3['turn_steps']}")
chk("认输后轮转到下一在局方（吴 2）", s3["turn"] == 2, f"turn={s3['turn']}")

print()
print("=" * 78)
print("4. Match 接口：约定步数 + 人类接管哪几方")
print("=" * 78)
from match import Match                        # noqa: E402
from agents import llm as LLM                  # noqa: E402
m = Match(LLM.load_roster())
m.auto = False
chk("默认 steps_per_turn = 1", m.steps_per_turn == 1)
r = m.set_steps_per_turn(3)
chk("set_steps_per_turn(3) 生效",
    r.get("ok") and m.state["steps_per_turn"] == 3, f"{r}")
chk("战报有 info 提示", any(e.get("type") == "info" and "每回合步数" in (e.get("text") or "")
                          for e in m.log))
r = m.set_steps_per_turn("")
chk("空串 → 回落为 1（传统）", m.steps_per_turn == 1, f"{r}")
r = m.set_steps_per_turn(999)
chk("超上限被夹到 20", m.steps_per_turn == 20, f"{r}")
m.set_steps_per_turn(1)

print()
print("  人类接管：")
r = m.set_human([1, 2])
chk("set_human([1,2]) → human_armies = {1,2}",
    r.get("ok") and m.human_armies == {1, 2}, f"{r}")
r = m.set_human("1,2")
chk("字符串 '1,2' 也能解析", m.human_armies == {1, 2}, f"{r}")
r = m.set_human([1, 9, "x"])
chk("非法值被忽略（只留 1）", m.human_armies == {1}, f"{r}")
r = m.set_human([])
chk("空 → 三方全 Bot", m.human_armies == set(), f"{r}")
r = m.set_human(2)
chk("单个整数 2 也能用", m.human_armies == {2}, f"{r}")
m.state["out"] = [2]                    # 吴已失去资格
r = m.set_human([2, 3])
chk("已失去资格的方不纳入接管", m.human_armies == {3}, f"{r}")
m.set_human([])
chk("快照带 human_armies 字段",
    "human_armies" in m.snapshot(), f"{sorted(m.snapshot().keys())[:6]}...")

print()
print("  接管方由人走、其余方 Bot 自动（引擎行为）：")
m2 = Match(LLM.load_roster())
m2.auto = False
m2.set_human([1, 2, 3])
chk("三方全接管 → 快照 human_armies = [1,2,3]",
    m2.snapshot()["human_armies"] == [1, 2, 3], f"{m2.snapshot()['human_armies']}")

print()
print("=" * 78)
print(f"合计 {OK} 通过 / {FAIL} 失败")
print("=" * 78)
sys.exit(1 if FAIL else 0)
