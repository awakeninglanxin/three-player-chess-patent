# -*- coding: utf-8 -*-
"""三人象棋 · 「每方主控 = 本地Bot / API 大模型」专项验证（老师 2026-10-02）

老师原话：
  ①「有没有可能选择让魏国给人类，另外两个接入 deepseek 和 hy4 api？」
  ②「做成可选的选项，用本地 bot 或者 api」

本文件验证 14 节：
  ① 目录：本地含 `__search__`；**API ≥2 项真能用**；id 唯一；`LOCAL_IDS` 与难度档一致
     ★ 可用/已停用/未配置三类 id **从真实目录动态取**，绝不写死模型名 ——
       老师随时会换模型，写死就变成"改测试而不是改代码"，门禁会废掉
  ② 就绪度：不能用的条目 `readiness=False` 且**带原因**；「已停用」与「未配置」**分得开**
  ③ 切到 API：agent 变 LLMAgent、meta.model 是**真正请求的模型名**（api_model）、`seats` 更新
  ④ **切席位不动棋局**：棋盘 / 手数 / 轮次 / 战绩 / 悔棋次数 / 人类接管 全程一致
  ⑤ 拒绝四条（未知 id / 未配置 / **已停用** / 非法军号）—— 且拒绝后**什么都没变**
  ⑥ 切回本地 Bot：**顺手套上当前难度档**（否则会掉回 agents.json 的兜底 depth）
  ⑦ 档 1 的语义：实际 model_id 变 `__local__`（贪心），但 `seats` 仍记**选项 id** `__search__`
  ⑧ 写回 roster：否则下一次切难度档会按**旧 cfg** 重建，把刚换的模型冲掉
  ⑨ API 席位**不被难度档冲掉**，且 `difficulty_skipped` 如实上报
  ⑩ 存档往返：`seats` 跨存档恢复（含 API 席位）
  ⑪ `--local` 降级后 restore 仍能恢复老师的 API 席位（显式选择 > 离线默认）
  ⑫ `/api/state` 字段齐备 + `seat_options` 是**缓存**（不在每帧快照里读磁盘）
  ⑬ ★ 回归：`catalog()` 不许把 `disabled` / `key_from` **静默剥掉**（本轮真踩过的坑）
  ⑭ ★ `key_from`：借别条密钥但**不落盘**；缺 `api_model` 必须被拦（防静默换模型）
"""
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "server"))

from agents import difficulty as D          # noqa: E402
from agents import seats as S               # noqa: E402
from match import Match                     # noqa: E402

PASS, FAIL = [], []


def chk(cond, name, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'✓' if cond else '✗'} {name}" + (f"   [{detail}]" if detail else ""))
    return bool(cond)


def sect(n, t):
    print(f"\n{'=' * 72}\n{n} {t}\n{'=' * 72}")


def fingerprint(m):
    """对局指纹：换主控前后必须**完全一致**（证明「只换脑子，不动棋局」）"""
    s = m.snapshot()
    q = s["status"]
    return {
        "board": json.dumps(s["pieces"], sort_keys=True),
        "ply": q["ply"], "turn": q["turn"],
        "out": sorted(q.get("out") or []),
        "eliminated": sorted(q.get("eliminated") or []),
        "kills": json.dumps(s.get("kills"), sort_keys=True),
        "slain": json.dumps(s.get("slain"), sort_keys=True),
        "wrong": json.dumps(s.get("wrong"), sort_keys=True),
        "undo_left": json.dumps(s.get("undo_left"), sort_keys=True),
        "human": sorted(s.get("human_armies") or []),
        "chain": s.get("chain_limit"), "steps": s.get("steps_per_turn"),
    }


def mk():
    """造一个**不落盘**的 Match（绝不碰 server/data/autosave.json）"""
    m = Match(auto=False)
    m.autosave_path = None
    return m


# ------------------------------------------------------------------ ①
# ---- 从**真实目录**里分三类取 id，测试**不写死模型名** ----
#   为什么不写死：老师随时会在 agents.json 里加减模型（2026-10-02 就整批换过一次）。
#   写死 ⇒ 换个模型门禁就红，那等于逼着人改测试而不是改代码，门禁就废了。
_real = S.catalog()


def _ready(o):
    return S.readiness(o)[0]


READY = [o["id"] for o in _real["api"] if _ready(o)]
DIS = [o["id"] for o in _real["api"] if o.get("disabled")]
UNREADY = [o["id"] for o in _real["api"] if not _ready(o) and not o.get("disabled")]
A1 = READY[0] if READY else ""
A2 = READY[1] if len(READY) > 1 else A1
print(f"  [目录实况] 可用  = {READY}")
print(f"             已停用= {DIS}")
print(f"             未配置= {UNREADY}")

sect(1, "① 目录：本地 1 项 + API ≥2 项真能用，id 唯一，且与难度档口径一致")
cat = _real
lids = [o["id"] for o in cat["local"]]
aids = [o["id"] for o in cat["api"]]
allids = lids + aids
chk("__search__" in lids, "本地项含 `__search__`（minimax 搜索）", f"{lids}")
chk(len(allids) == len(set(allids)), "目录 id 全局唯一（重复会让下拉选错模型）", f"{allids}")
chk(len(READY) >= 2,
    "★ API 项**至少两个真能用**（老师：「你找两个便宜的 api agent 先接上」）",
    f"{READY}")
chk(tuple(S.LOCAL_IDS) == tuple(D.LOCAL_IDS),
    "`seats.LOCAL_IDS` 与 `difficulty.LOCAL_IDS` 一致（不一致 ⇒ 难度档漏接管一席）",
    f"{S.LOCAL_IDS} vs {D.LOCAL_IDS}")
chk(all(S.is_local(o["id"]) == bool(o["local"]) for o in S.all_options()),
    "`is_local()` 与目录的 local 标记一致")
chk(all(not S.is_local(x) for x in aids),
    "API 条目**都不算**本地 Bot（⇒ 不受难度档接管）", f"{aids}")
if "hy4" in aids:
    chk(not _ready(S.find(cat, "hy4")),
        "老师最初点名的 HY4 仍未配置 ⇒ **不可选**（诚实反映现状，不假装能用）",
        _ready(S.find(cat, "hy4")))

# ------------------------------------------------------------------ ②
sect(2, "② 就绪度：不能用的条目必须**不可选且说明原因**（已停用 / 未配置分开说）")
for oid in ["__search__"] + aids:
    o = S.find(cat, oid)
    ok, why = S.readiness(o)
    print(f"     {oid:<38s} ready={str(ok):<5s} {why[:66]}")
chk(S.readiness(S.find(cat, "__search__"))[0] is True,
    "本地 Bot 恒可用（纯离线，不依赖网络/密钥）")
chk(all(bool(S.readiness(S.find(cat, x))[1]) for x in aids if not _ready(S.find(cat, x))),
    "每一个不能用的 API 条目都**带原因**（防「选了没反应」）")
chk(len(DIS) >= 1, "至少有一条 `disabled:true` 的停用条目（欠费/下线的如实标出来）", f"{DIS}")
for x in DIS:
    why = S.readiness(S.find(cat, x))[1]
    chk("停用" in why, f"停用条目「{x}」的原因写明是**停用**（不是「你没配」）", why[:60])
ui = S.describe_for_ui(cat, 2)
chk(all("ready" in o and "why" in o and "disabled" in o for o in ui["api"]),
    "给前端的目录带 ready/why/disabled（未就绪的置灰，且两种原因分得开）")
chk([o["id"] for o in ui["api"] if not o["ready"]] == [x for x in aids if not _ready(S.find(cat, x))],
    "未就绪集合与 readiness() 口径一致",
    f"{[o['id'] for o in ui['api'] if not o['ready']]}")

# ------------------------------------------------------------------ ③
sect(3, "③ 切到 API：agent 变 LLMAgent，label/model/seats 都对")
m = mk()
r = m.set_seat(3, A1)
chk(r.get("ok") is True, f"蜀方 → {A1} 成功", json.dumps(r, ensure_ascii=False)[:110])
chk(m.agents[3].__class__.__name__ == "LLMAgent", "蜀方 agent 变成 LLMAgent",
    m.agents[3].__class__.__name__)
_o1 = S.find(cat, A1)
_real_model = _o1.get("api_model") or A1
chk(m.meta[3]["model"] == _real_model,
    f"meta.model 是**真正请求的模型名**（api_model={_real_model}）", m.meta[3]["model"])
chk(bool(m.meta[3]["label"]), "meta.label 反映真实模型名", m.meta[3]["label"])
chk(m.snapshot()["seats"]["3"] == A1,
    "/api/state 的 seats 如实更新（前端据此回显下拉）")
chk(m.meta[3]["has_key"] is True, "密钥解析到了（has_key）")
chk(m.snapshot()["agents"]["3"]["local"] is False, "快照里该席 local=False（前端据此加金边）")

# ------------------------------------------------------------------ ④
sect(4, "④ ★ 换主控**不动棋局**（逐字段比对对局指纹）")
m2 = mk()
f0 = fingerprint(m2)
seq = [(3, A1), (3, "__search__"), (2, A1),
       (2, "__search__"), (1, A2), (1, "__search__")]
diff = []
for k, mid in seq:
    m2.set_seat(k, mid)
    if fingerprint(m2) != f0:
        diff.append(f"{k}→{mid}")
chk(not diff, "连换 6 次主控后：棋盘/手数/轮次/战绩/悔棋次数/人类接管**逐字段未变**",
    f"差异点 {diff}" if diff else "6/6 一致")

# ------------------------------------------------------------------ ⑤
sect(5, "⑤ 拒绝三条：未知 id / 不能用的条目 / 非法军号 —— 拒绝后**什么都没变**")
#   用**真实目录里**那条没配好的条目来测这条路径；若目录全配齐了，
#   这个分支自动跳过（下面 DIS 分支仍会覆盖"选不进去"的主诉求）。
m3 = mk()
m3.set_seat(2, A1)
f1, s1 = fingerprint(m3), dict(m3.snapshot()["seats"])
_uncfg = UNREADY[0] if UNREADY else None
if _uncfg:
    r1 = m3.set_seat(2, _uncfg)
    chk(r1.get("ok") is False and bool(r1.get("error")),
        f"未配置的「{_uncfg}」被**明确拒绝**并说明原因（绝不静默换成别的模型）",
        (r1.get("error") or "")[:60])
    chk(r1.get("ready") is False, "拒绝时带 ready=False（前端可据此置灰）")
if DIS:
    r1d = m3.set_seat(2, DIS[0])
    chk(r1d.get("ok") is False and "停用" in (r1d.get("error") or ""),
        f"★ 已停用的「{DIS[0]}」也被**明确拒绝**（欠费条目绝不能选进去）",
        (r1d.get("error") or "")[:60])
r2 = m3.set_seat(2, "gpt-9")
chk(r2.get("ok") is False and "未知" in (r2.get("error") or ""), "未知 model_id 被拒绝",
    (r2.get("error") or "")[:60])
r3 = m3.set_seat(9, "__search__")
chk(r3.get("ok") is False and "军" in (r3.get("error") or ""), "非法军号被拒绝",
    (r3.get("error") or "")[:60])
r4 = m3.set_seat(None, "__search__")
chk(r4.get("ok") is False, "军号为 None 也被拒绝（不是 1/2/3 一律拒）")
chk(m3.agents[2].__class__.__name__ == "LLMAgent",
    f"★ 全部拒绝之后，吴方**仍是 {A1}**（没有被打回本地 Bot）")
chk(fingerprint(m3) == f1 and dict(m3.snapshot()["seats"]) == s1,
    "全部拒绝之后 seats 与对局指纹均未变")

# ------------------------------------------------------------------ ⑥
sect(6, "⑥ 切回本地 Bot：**顺手套上当前难度档**（否则会掉回 agents.json 兜底 depth）")
m4 = mk()
m4.set_difficulty(4)                      # 大师 9 plies → depth 3 / 45s
m4.set_seat(3, A1)
m4.set_seat(3, "__search__")
c3 = m4.roster["players"]["3"]
chk(c3.get("model_id") == "__search__" and c3.get("depth") == 3
    and abs(float(c3.get("time_limit", 0)) - 45.0) < 1e-6,
    "档 4 下切回本地 ⇒ depth=3 / time_limit=45s（= 该档定义，不是兜底值）",
    f"depth={c3.get('depth')} tl={c3.get('time_limit')}")
chk(m4.agents[3].__class__.__name__ == "SearchBot", "蜀方 agent 变回 SearchBot")
chk("大师" in m4.meta[3]["label"], "label 跟着难度档走", m4.meta[3]["label"])

# ------------------------------------------------------------------ ⑦
sect(7, "⑦ 档 1（新手）的语义：实际是贪心，但 seats 仍记**选项 id**")
m5 = mk()
m5.set_seat(3, A1)
m5.set_difficulty(1)
m5.set_seat(3, "__search__")
chk(m5.roster["players"]["3"].get("model_id") == "__local__",
    "档 1 下切回本地 ⇒ 实际 model_id = `__local__`（新手＝一步贪心，这就是档 1 的定义）",
    m5.roster["players"]["3"].get("model_id"))
chk(m5.snapshot()["seats"]["3"] == "__search__",
    "★ 但 seats 仍记**选项 id** `__search__` ⇒ 下拉不会自己跳到不存在的项",
    m5.snapshot()["seats"]["3"])
chk(m5.agents[3].__class__.__name__ == "LocalBot", "该席 agent 是 LocalBot",
    m5.agents[3].__class__.__name__)
chk(D.is_local(m5.roster["players"]["3"]), "难度档仍认它为「本地」（不会漏接管）")

# ------------------------------------------------------------------ ⑧
sect(8, "⑧ 必须**写回 roster**：否则下一次切难度档会按旧 cfg 重建，把新模型冲掉")
m6 = mk()
m6.set_seat(2, A1)
chk(m6.roster["players"]["2"].get("model_id") == S.cred_id(S.find(cat, A1)),
    "切到 API 后 roster 里的 model_id 同步更新（= cred_id，可能是借密钥那条）",
    m6.roster["players"]["2"].get("model_id"))
m6.set_difficulty(3)                       # 若没写回 roster，这里会把它打回 __search__
chk(m6.agents[2].__class__.__name__ == "LLMAgent",
    "★ 随后切难度档 3 ⇒ 吴方**仍是 LLMAgent**（没被难度档冲掉）",
    m6.agents[2].__class__.__name__)
chk(m6.snapshot()["seats"]["2"] == A1, "seats 也未变")
m6.set_difficulty(1)                       # 连切到档 1 再验一次
chk(m6.agents[2].__class__.__name__ == "LLMAgent", "连切到档 1 也没被冲掉",
    m6.agents[2].__class__.__name__)
chk(m6.agents[1].__class__.__name__ == "LocalBot" and m6.agents[3].__class__.__name__ == "LocalBot",
    "同一次切档里，另外两方正常被档 1 接管（= 新手贪心）",
    f"魏{m6.agents[1].__class__.__name__} 蜀{m6.agents[3].__class__.__name__}")

# ------------------------------------------------------------------ ⑨
sect(9, "⑨ API 席位在 difficulty_skipped 里**如实上报**（页面要提示「不受难度档影响」）")
st9 = m6.snapshot()
chk("吴" in st9["difficulty_skipped"], "difficulty_skipped 含「吴」",
    f"{st9['difficulty_skipped']}")
chk("魏" not in st9["difficulty_skipped"] and "蜀" not in st9["difficulty_skipped"],
    "被难度档接管的魏/蜀**不在** skipped 里")
m7 = mk()
m7.set_seat(1, A2)
m7.set_seat(3, A1)
chk(set(m7.snapshot()["difficulty_skipped"]) == {"魏", "蜀"},
    "两席为 API ⇒ skipped 如实列出两方", f"{m7.snapshot()['difficulty_skipped']}")
chk(m7.agents[2].__class__.__name__ == "SearchBot",
    "夹在中间的那一席（吴）仍被难度档接管 = SearchBot", m7.agents[2].__class__.__name__)

# ------------------------------------------------------------------ ⑩
sect(10, "⑩ 存档往返：seats 跨存档恢复（含 API 席位）")
tmp = tempfile.mkdtemp(prefix="seatchk_")
sp = os.path.join(tmp, "autosave.json")
mS = mk()
mS.set_seat(1, A2)
mS.set_seat(3, A1)
mS.set_difficulty(3)
mS.set_human([1])
mS.autosave_path = sp
ok_save = mS.save(sp)
chk(ok_save and os.path.exists(sp), "存档写入成功", sp)
before = mS.snapshot()
mR = mk()
info = mR.restore(sp, quiet=True)
chk(info.get("restored") is True, "恢复成功", json.dumps(info, ensure_ascii=False)[:100])
chk(mR.snapshot()["seats"] == before["seats"],
    f"★ seats 逐项复原（魏={A2} / 蜀={A1}）",
    json.dumps(mR.snapshot()["seats"], ensure_ascii=False))
chk(mR.agents[1].__class__.__name__ == "LLMAgent" and mR.agents[3].__class__.__name__ == "LLMAgent",
    "恢复后两席 agent 真的是 LLMAgent（不是只记了名字）",
    f"魏{mR.agents[1].__class__.__name__} 蜀{mR.agents[3].__class__.__name__}")
chk(mR.agents[2].__class__.__name__ == "SearchBot", "未改的那一席仍是本地 SearchBot")
chk(mR.snapshot()["difficulty"] == 3 and mR.human_armies == {1},
    "难度档 3 与人类接管 [1] 也一并复原",
    f"diff={mR.snapshot()['difficulty']} human={sorted(mR.human_armies)}")
chk(fingerprint(mR)["board"] == fingerprint(mS)["board"],
    "棋盘也逐点复原（换主控没有把存档写坏）")

# ------------------------------------------------------------------ ⑪
sect(11, "⑪ `--local` 降级后 restore 仍能恢复老师的 API 席位（显式选择 > 离线默认）")
from agents.llm import load_roster        # noqa: E402
ros = load_roster()
ros = json.loads(json.dumps(ros))         # 深拷贝：绝不改真 agents.json 的内容
#   模拟 app.py main() 里 `--local` 做的事：把「需要联网」的模型换成本地档位 Bot
lv = D.get(ros.get("options", {}).get("difficulty"))
for _k, cfg in ros["players"].items():
    if (cfg.get("model_id") or "") not in ("__search__", "__local__"):
        cfg.update(D.apply(cfg, lv["level"]))
m8 = Match(roster=ros, auto=False)
m8.autosave_path = None
info8 = m8.restore(sp, quiet=True)        # 用第 ⑩ 节那份含 API 席位的存档
chk(info8.get("restored") is True, "在「被 --local 降级过」的 roster 上仍能恢复存档")
chk(m8.agents[1].__class__.__name__ == "LLMAgent",
    "★ 魏方席位**仍按存档恢复成 API 大模型**（老师的显式选择优先于 --local 默认）",
    m8.agents[1].__class__.__name__)
chk(m8.snapshot()["seats"]["1"] == A2, "seats 也恢复成存档里的值",
    json.dumps(m8.snapshot()["seats"], ensure_ascii=False))

# ------------------------------------------------------------------ ⑫
sect(12, "⑫ /api/state 字段齐备 + seat_options 是**缓存**（不在每帧快照里读磁盘）")
st12 = mk().snapshot()
chk("seats" in st12 and "seat_options" in st12, "快照含 seats / seat_options 两个新字段")
chk(isinstance(st12["seats"], dict) and set(st12["seats"]) == {"1", "2", "3"},
    "seats 是 {1,2,3} → 选项 id 的字符串键字典", json.dumps(st12["seats"], ensure_ascii=False))
chk(isinstance(st12["seat_options"], dict)
    and isinstance(st12["seat_options"].get("local"), list)
    and isinstance(st12["seat_options"].get("api"), list),
    "seat_options = {local:[...], api:[...]}（前端据此画下拉）")
mA, mB = mk(), mk()
ids_a = [id(mA.snapshot()["seat_options"]), id(mA.snapshot()["seat_options"])]
chk(ids_a[0] == ids_a[1],
    "★ 连续两帧快照返回**同一个对象** ⇒ 目录是缓存的（否则每 800ms 读一次 models.json）",
    f"{ids_a}")
chk([o["brief"] for o in mB.snapshot()["seat_options"]["local"]] == ["3 plies"],
    "本地项的 brief 跟着当前难度档（档2 = 3 plies）",
    f"{[o['brief'] for o in mB.snapshot()['seat_options']['local']]}")
mB.set_difficulty(4)
chk([o["brief"] for o in mB.snapshot()["seat_options"]["local"]] == ["9 plies"],
    "★ 切档后目录缓存**已刷新**（档4 = 9 plies）",
    f"{[o['brief'] for o in mB.snapshot()['seat_options']['local']]}")

# ------------------------------------------------------------------ ⑬
sect(13, "⑬ ★ 回归：`catalog()` **不许把 `disabled` / `key_from` 剥掉**")
#   实测踩过（2026-10-02）：`catalog()` 的白名单漏了 `disabled` ⇒ `readiness()`
#   里的 `opt.get('disabled')` 永远读不到 ⇒ **"显式停用"功能从来没生效过**。
#   这类 bug 的特征是「功能看着写好了，但被上一层静默过滤」⇒ 断言必须**走
#   catalog() 出口**再读一遍，光看 readiness 的源码是抓不到的。
_fake = {S.CONF_KEY: {
    "local": [{"id": "__search__", "label": "本地Bot"}],
    "api": [{"id": "FAKE", "label": "假模型", "disabled": True,
             "key_from": "SRC", "api_model": "real/upstream-name"}]}}
_g = S.catalog(_fake)["api"][0]
chk(_g.get("disabled") is True, "`disabled` 穿过 catalog() 没被剥掉", json.dumps(_g, ensure_ascii=False))
chk(_g.get("key_from") == "SRC", "`key_from` 穿过 catalog() 没被剥掉", json.dumps(_g, ensure_ascii=False))
chk(_g.get("api_model") == "real/upstream-name", "`api_model` 穿过 catalog() 没被剥掉")
chk(S.readiness(_g)[0] is False and "停用" in S.readiness(_g)[1],
    "★ 路径闭环：被静默剥掉的话这里会回到 True（正是本轮踩的坑）", S.readiness(_g)[1][:50])

# ------------------------------------------------------------------ ⑭
sect(14, "⑭ ★ `key_from`：借别条密钥但**不落盘**，且缺 api_model 必须被拦")
_src = S.cred_id(S.find(cat, A1))          # 真实存在的凭据来源（models.json 里那条）
_o = {"id": "borrow-probe", "label": "借密钥探针", "key_from": _src,
      "api_model": "vendor/real-model-name", "max_tokens": 700}
_cfg = S.apply({"army": "吴", "model_id": "__search__", "depth": 3}, _o, 2)
chk(_cfg.get("model_id") == _src,
    "★ apply 后 cfg.model_id 指向**凭据来源**（llm.resolve 是按 model_id 查 models.json 的）",
    f"{_cfg.get('model_id')} vs {_src}")
chk(_cfg.get("api_model") == "vendor/real-model-name",
    "★ 而**真正请求的模型名**由 api_model 决定（不是被借那条的名字）", _cfg.get("api_model"))
import agents.llm as _LLM                  # noqa: E402
_u, _k, _m, _l = _LLM.resolve(_cfg)
chk(bool(_u) and bool(_k) and _m == "vendor/real-model-name",
    "resolve() 真的借到了 url+密钥，且 model 是我们要的那个",
    f"url={'有' if _u else '空'} key={'有' if _k else '空'} model={_m}")
chk("api_key" not in _o and "url" not in _o,
    "★ 探针条目**没有** url/api_key 字段 ⇒ 密钥不需要写进本项目（不落盘）",
    json.dumps(_o, ensure_ascii=False))
#   ⚠️ 缺 api_model ⇒ resolve() 会把**被借那条的模型名**当成要请求的模型名
#      （悄悄地换成另一个模型 —— 最难查的一类）。readiness 必须提前拦住。
_bad = {"id": "borrow-nomodel", "label": "缺 api_model", "key_from": _src}
_ok, _why = S.readiness(_bad)
chk(_ok is False and "api_model" in _why,
    "★ 用了 key_from 却没写 api_model ⇒ **判不就绪**并说明原因（防静默换模型）", _why[:66])
#   端到端再走一遍：真把它挂进 roster，set_seat 必须**拒绝**（而不是选进去后每步失败）
_ros9 = json.loads(json.dumps(load_roster()))
_ros9[S.CONF_KEY]["api"].append(dict(_bad))
_m9 = Match(roster=_ros9, auto=False)
_m9.autosave_path = None
_r9 = _m9.set_seat(2, "borrow-nomodel")
chk(_r9.get("ok") is False and bool(_r9.get("error")),
    "★ 端到端：set_seat 对「缺 api_model 的 key_from 条目」**明确拒绝**",
    (_r9.get("error") or "")[:60])
chk(_m9.snapshot()["seats"]["2"] != "borrow-nomodel", "拒绝后 seats 没有被写脏")
try:
    _m9.pause()
except Exception:                          # noqa: BLE001
    pass

# 收尾：别留下跑着的线程
for _m in (m, m2, m3, m4, m5, m6, m7, mS, mR, m8, mA, mB):
    try:
        _m.pause()
    except Exception:                      # noqa: BLE001
        pass

print("\n" + "=" * 72)
print(f"每方主控（本地Bot / API）专项验证：{len(PASS)} 通过 / {len(FAIL)} 失败")
for f in FAIL:
    print("  ✗", f)
print("=" * 72)
sys.exit(0 if not FAIL else 1)
