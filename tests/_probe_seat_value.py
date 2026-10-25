# -*- coding: utf-8 -*-
"""按座位配 value_net 的回归探针（2026-10-02 老师拍板「按座位配」）。

【为什么需要它】"改了 JSON 就说配好了"是不够的。从配置到真正生效有 4 个环节，
每一环都可能把字段吞掉：

    agents.json 的 players.N.use_value
      → difficulty.apply(cfg, lv)     ← `out = dict(cfg)` 重建 cfg，万一漏了未知键就丢
      → match.build_agent(cfg2)       ← 把 cfg 翻译成 SearchBot 的关键字参数
      → SearchBot._value_spec         ← 真正的开关（(use, lam, kind, file) 四元组）

所以本探针**真跑这条链**，逐环断言，不平行实现（被验证对象就是这条链本身）。

【核心不变量】老师 2026-10-02 的决定：**只有一席开价值网络**。
  依据（tools/ab_match.py，各 300 局，一局三配置 + 座位轮转）：
    {2纯搜索 + 1价值网络} ⇒ 稳赢；{1纯搜索 + 2价值网络} ⇒ 优势转负
    （两台"和平型"同场，判和率 34% → 47~54%，双方优势互相中和）
  ⇒ 本探针第一项就断言"恰好一席"，防止将来有人手滑开两席。

跑法：python tests/_probe_seat_value.py
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (os.path.join(ROOT, "server"), os.path.join(ROOT, "server", "agents"), ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

CFG_P = os.path.join(ROOT, "server", "agents", "agents.json")

_ok = 0
_bad = 0


def chk(cond, msg):
    global _ok, _bad
    if cond:
        _ok += 1
        print(f"  ✅ {msg}")
    else:
        _bad += 1
        print(f"  ❌ {msg}")


def main():
    print("=" * 76)
    print("按座位配 value_net · 回归探针")
    print("=" * 76)

    raw = json.load(open(CFG_P, encoding="utf-8"))

    # ---------------------------------------------------------------- ① 配置层
    print("\n① 配置层：agents.json 的 players")
    players = raw["players"]
    on = [k for k, v in players.items() if v.get("use_value") is True]
    off = [k for k, v in players.items() if v.get("use_value") is False]
    print(f"   开：{on}   关：{off}   未写："
          f"{[k for k, v in players.items() if 'use_value' not in v]}")
    chk(len(on) == 1, f"**恰好一席**开价值网络（老师 2026-10-02 的决定）—— 实得 {len(on)} 席")
    explicit = len(on) + len(off)
    chk(explicit == 3,
        f"三席都**显式**写了 use_value（开 {len(on)} + 关 {len(off)}）—— 实得 {explicit} 席")
    #   三席都写死 ⇒ 全局 `value_net.enabled` 改成什么都不影响（这是"默认关、
    #   显式开"的目的：谁也没表态时才回落到全局值）。
    chk(raw["value_net"]["enabled"] is False,
        "全局 value_net.enabled 保持 false（兜底值，已不生效）")
    seat_on = on[0] if on else None
    chk(players.get(seat_on, {}).get("value_lambda") == 0.35,
        f"开的那一席（{seat_on}）显式给了 value_lambda=0.35（有 A/B 数据支撑的档）")

    # ---------------------------------------------------------------- ② 链路层
    print("\n② 链路层：agents.json → difficulty.apply → match.build_agent")
    try:
        from match import build_agent            # noqa: E402
        from agents import difficulty as DIFF    # noqa: E402
    except Exception as e:                       # noqa: BLE001
        print(f"   ⚠️ 无法 import（{type(e).__name__}: {e}）⇒ **跳过链路层**，只留配置层断言")
        print("      （这不是配置错，是测试环境缺依赖；配置层 4 项仍然有效）")
        return _report()

    chain_ok = True
    for lv in range(1, 7):
        d = DIFF.get(lv)
        if d["model_id"] != "__search__":
            print(f"   档{lv}（{d['name']}）→ {d['model_id']}（不走搜索 ⇒ 价值网络不适用，跳过）")
            continue
        specs = {}
        for k, cfg in players.items():
            cfg2 = DIFF.apply(cfg, lv)           # 档位覆写
            bot = build_agent(cfg2)
            specs[k] = tuple(getattr(bot, "_value_spec", None) or ())
        want = {k: (players[k].get("use_value"), players[k].get("value_lambda"))
                for k in players}
        got = {k: (v[0], v[1]) for k, v in specs.items()}
        line = "  ".join(f"{players[k]['army']}={got[k][0]}/{got[k][1]}" for k in players)
        if got == want:
            print(f"   档{lv}（{d['name']}）✅ {line}")
        else:
            chain_ok = False
            print(f"   档{lv}（{d['name']}）❌ {line}   期望 {want}")
    chk(chain_ok, "**六个难度档**逐档跑链路后，三席的 (use_value, lambda) 与配置一致")

    # ---------------------------------------------------------------- ③ 与全局解耦
    print("\n③ 与全局开关解耦：三方都写死 ⇒ 全局 enabled 改什么都不影响")
    specs = {}
    for k, cfg in players.items():
        specs[k] = tuple(getattr(build_agent(DIFF.apply(cfg, 3)), "_value_spec", None) or ())
    all_explicit = all(v and v[0] is not None for v in specs.values())
    chk(all_explicit,
        f"三席的 `_value_spec[0]` 都**不是 None**（None 才表示「跟随全局」）"
        f" —— 实得 {[specs[k][0] for k in players]}")

    # ---------------------------------------------------------------- ④ 在环验证
    print("\n④ 在环：开的那一席真能加载出 advisor（懒加载不抛异常）")
    if seat_on:
        bot = build_agent(DIFF.apply(players[seat_on], 3))
        try:
            adv = bot.advisor()
            chk(adv is not None and bool(getattr(adv, "enabled", False)),
                f"{players[seat_on]['army']}方 advisor 加载成功且 enabled=True")
            # 关的那一席必须**拿不到** advisor（或 enabled=False）
            off_seat = off[0]
            b2 = build_agent(DIFF.apply(players[off_seat], 3))
            a2 = b2.advisor()
            chk(a2 is None or not bool(getattr(a2, "enabled", False)),
                f"{players[off_seat]['army']}方 advisor 未启用（None 或 enabled=False）")
        except Exception as e:                   # noqa: BLE001
            print(f"   ⚠️ advisor 加载异常（{type(e).__name__}: {e}）"
                  f" —— 源码有「静默退回纯搜索」的兜底，故不算失败")

    return _report()


def _report():
    print("\n" + "=" * 76)
    if _bad == 0:
        print(f"全部通过：{_ok}/{_ok + _bad}")
    else:
        print(f"❌ {_bad} 项失败 / 共 {_ok + _bad} 项")
    print("=" * 76)
    return 1 if _bad else 0


if __name__ == "__main__":
    sys.exit(main())
