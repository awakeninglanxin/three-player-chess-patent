# -*- coding: utf-8 -*-
"""每方「用**本地 Bot** 还是用 **API 大模型**」的席位目录 —— 老师 2026-10-02 定案

> 老师原话：
>   「有没有可能选择让魏国给人类，另外两个接入 deepseek 和 hy4 api？」
>   「做成可选的选项，用本地 bot 或者 api」

⇒ 网页「每方主控」三个下拉：**魏 / 吴 / 蜀** 各选一个脑子。选项分两类：

    · 本地 Bot  —— `__search__`（minimax 搜索）
                   ★ **本地那一项只有它一个**，因为「一步贪心」已经由
                     **难度档 1「新手」**表达了（`difficulty.apply` 在档1 会把它
                     变成 `__local__`）。两个入口管同一件事 ⇒ 一定打架，故只留一个。
    · API 大模型 —— `deepseek-v4-flash` / `hy4` …（**不受难度档影响**）

【目录放哪】`agents.json` 的 `model_options` 段。
    配置归配置、逻辑归本模块 —— **想加一个模型只改 agents.json，不用改 Python**。
【密钥从哪来】沿用 `llm.resolve()` 的口径（**不另造一套**）：
    先看条目自己的 `url` / `api_key` / `api_model`，没有再回落到
    `~/.workbuddy/models.json` 里同 id 的那条。

    ★ **`key_from`：借另一条的 url + 密钥。** 为什么需要它（2026-10-02 实测）：
      NVIDIA NIM 上一个 key 能开很多模型，但 `models.json` 里只登记了少数几条
      ⇒ 想用没登记的模型，要么把密钥**明文抄进本项目**（密钥落盘，不可取），
      要么只写 `"key_from": "<models.json 里任一条 NIM 条目 id>"` +
      `"api_model": "<真正要请求的模型名>"`。后者不落密钥，改一行就能换模型。
【没配好的条目】网页上**置灰 + 写明原因**，后端 `set_seat` 也**明确拒绝**
    —— 绝不"悄悄换成别的模型"（那正是最难查的一类 bug）。

【与难度档的关系（必须记住）】
    难度档只接管 `__search__` / `__local__` 两席（`difficulty.is_local()`）。
    某一方切到 API 后：① 它**不再**被难度档覆盖；② `/api/state` 的
    `difficulty_skipped` 会如实把它列出来，网页提示「X方为大模型，不受难度档影响」；
    ③ 但从 API **切回本地 Bot** 时必须**顺手套上当前难度档**，否则会掉回
    `agents.json` 里那条兜底 depth（老师会看到"切回来变弱了"）。
"""
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_SRV = os.path.dirname(_HERE)
for _p in (_SRV, _HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

#: 本地 Bot 的两个 id（与 `difficulty.LOCAL_IDS` 必须一致 —— 有自检断言）
LOCAL_IDS = ("__search__", "__local__")

#: `agents.json` 里放目录的那一段
CONF_KEY = "model_options"


def _default_catalog():
    """`agents.json` 没写 `model_options` 时的兜底目录（保证网页永远有东西可选）"""
    return {
        "local": [
            {"id": "__search__", "label": "本地Bot · 搜索", "brief": "3~12 plies",
             "hint": "minimax + alpha-beta + numba 内核；**受「Bot 难度」档位接管**，0 token"},
        ],
        "api": [],
    }


def catalog(roster=None):
    """取目录（**不改原对象**）。本地项在前、API 项在后。"""
    if roster is None:
        try:
            with open(os.path.join(_HERE, "agents.json"), encoding="utf-8") as f:
                roster = json.load(f)
        except Exception:                              # noqa: BLE001
            roster = {}
    cat = {}
    if isinstance(roster, dict):
        if CONF_KEY in roster:
            cat = roster.get(CONF_KEY) or {}
        elif "local" in roster or "api" in roster:
            # 容错：有人把 **`model_options` 段本身**（或本函数上一次的返回值）
            #   直接传了进来。这里认出来，否则会**静默退化**成兜底目录 ——
            #   表现为"API 项明明配了却说找不到"，属于最难查的一类。
            cat = roster
    if not isinstance(cat, dict):
        cat = {}
    out = {}
    for kind in ("local", "api"):
        items = cat.get(kind)
        if not isinstance(items, list) or not items:
            items = _default_catalog().get(kind) or []
        clean = []
        for it in items:
            if not isinstance(it, dict) or not it.get("id"):
                continue
            o = {k: it[k] for k in ("id", "label", "brief", "hint", "url",
                                    "api_key", "api_model", "max_tokens",
                                    "army", "kind",
                                    # ⚠️ **必须一起拷**：
                                    #   · `disabled` —— 漏掉它 ⇒ `readiness()` 里的
                                    #     `opt.get("disabled")` 永远读不到 ⇒ **显式停用
                                    #     形同虚设**（实测踩过：欠费条目照样能选中）。
                                    #   · `key_from` —— 漏掉它 ⇒ 借不到密钥 ⇒ 未就绪。
                                    "disabled", "key_from") if k in it}
            o.setdefault("label", o["id"])
            o["kind"] = kind
            o["local"] = kind == "local"
            clean.append(o)
        out[kind] = clean
    return out


def all_options(roster=None):
    """本地 + API 拍平成一张清单（保持"本地在前"的顺序）"""
    cat = catalog(roster)
    return list(cat["local"]) + list(cat["api"])


def find(roster, model_id):
    """按 id 找条目；找不到返回 None（调用方必须**明确报错**，不许兜底换模型）"""
    mid = (model_id or "").strip()
    if not mid:
        return None
    for o in all_options(roster):
        if o["id"] == mid:
            return o
    return None


def is_local(model_id):
    """这个 id 是不是本地 Bot（= 能被难度档接管）"""
    return (model_id or "") in LOCAL_IDS


def cred_id(opt):
    """取 url/密钥 时该按 `models.json` 里的哪一条找 —— `key_from` 优先，否则就是自己

    为什么单独抽出来：`llm.resolve()` 是**按 cfg["model_id"] 去 models.json 查**的，
    所以"借密钥"这件事只能通过**把 cfg["model_id"] 改成被借那条的 id** 来实现。
    """
    return (opt.get("key_from") or opt.get("id") or "").strip()


def readiness(opt):
    """这个条目**现在**能不能真用 → (ok, why)

    本地 Bot 永远可用（纯离线）。API 条目要求：
      · `url` 能解析出来（条目自带 或 `~/.workbuddy/models.json` 里有同 id）
      · `api_key` 非空
    否则**不能选** —— 老师最讨厌的正是"选了却没反应 / 悄悄换成本地 Bot"。
    """
    if opt is None:
        return False, "未知的模型选项"
    if opt.get("local"):
        return True, ""
    # `disabled: true` = **已知不可用**（欠费 / 下线 / 限流），由目录显式停用。
    #   为什么要有这一条：`readiness` 只能查"配没配 url+密钥"，**查不出账号欠费**。
    #   实测（2026-10-02）：deepseek 官方三个模型的密钥都在，但全部 `HTTP 402
    #   Insufficient Balance` ⇒ 老师若能在下拉里选中，就是"选了却每步失败"，
    #   正是最该避免的那种体验。宁可灰掉 + 写明原因。
    if opt.get("disabled"):
        return False, (opt.get("hint") or "该条目已被停用（见 agents.json 的 model_options）")
    # 用了 `key_from` 却忘了写 `api_model` ⇒ `resolve()` 会把**被借那条的模型名**
    #   当成要请求的模型名 ⇒ **悄悄地换成另一个模型**。这是最难查的一类，必须挡住。
    if opt.get("key_from") and not opt.get("api_model"):
        return False, (f"条目「{opt['id']}」用了 key_from 就必须同时写明 api_model"
                       f"（真正要请求的模型名），否则会落到被借那条的模型上")
    from agents import llm as LLM                        # 只 import urllib，很轻
    probe = {"model_id": cred_id(opt)}
    for k in ("url", "api_key", "api_model"):
        if opt.get(k):
            probe[k] = opt[k]
    url, key, model, _label = LLM.resolve(probe)
    if not url:
        return False, (f"未配置接口地址：请在 agents.json 的 model_options.api 里给 "
                       f"「{opt['id']}」补 url（或写 key_from 借同厂商另一条的 url），"
                       f"或把同名模型加进 ~/.workbuddy/models.json")
    if not key:
        return False, (f"未配置密钥：请在 agents.json 的 model_options.api 里给 "
                       f"「{opt['id']}」补 api_key（或写 key_from 借同厂商另一条的密钥），"
                       f"或把同名模型加进 ~/.workbuddy/models.json")
    if not model:
        return False, f"未配置模型名（api_model）：{opt['id']}"
    return True, ""


def describe_for_ui(roster=None, difficulty=None):
    """给前端画下拉：每项补 `ready` / `why`（未就绪的置灰并写明原因）"""
    cat = catalog(roster)
    out = {}
    for kind in ("local", "api"):
        arr = []
        for o in cat[kind]:
            ok, why = readiness(o)
            d = {"id": o["id"], "label": o["label"], "brief": o.get("brief", ""),
                 # hint 要透传给前端当 <option title>（悬停说明这个模型是什么/多慢）
                 "hint": o.get("hint", ""),
                 "kind": kind, "local": bool(o.get("local")),
                 # `disabled` 要单独下发 —— 前端据此把后缀写成「已停用」而不是
                 #   「未配置」（两者原因完全不同，混为一谈老师会以为是他没配密钥）。
                 "disabled": bool(o.get("disabled")),
                 "ready": ok, "why": why}
            if kind == "local" and difficulty:
                try:
                    from agents import difficulty as DIFF
                    lv = DIFF.get(difficulty)
                    d["brief"] = f"{lv['plies']} plies"
                except Exception:                      # noqa: BLE001
                    pass
            arr.append(d)
        out[kind] = arr
    return out


def apply(base_cfg, opt, difficulty):
    """把某个条目套到某一方的席位配置上 → **新的** cfg（不改原对象）

    · 本地 Bot ⇒ **顺手套上当前难度档**（`difficulty.apply`），
      这样"从 API 切回本地"不会掉回 agents.json 里的兜底 depth。
      ⚠️ 档 1「新手」得到的 `model_id` 是 `__local__`（一步贪心）——这是**对的**，
         难度档 1 的定义就是贪心；调用方记的"席位选项"仍应是 `__search__`。
    · API ⇒ 只改 model_id + label，并把难度档留下的 depth/time_limit/qs_depth
      **清掉**（LLM 不看这些键，留着会在界面上误导"深度 4"）。
      ⚠️ `model_id` 写的是 **`cred_id()`**（可能是 `key_from` 指的那条），
         不是 `opt["id"]` —— 因为 `llm.resolve()` 就是拿 `cfg["model_id"]`
         去 `models.json` 查 url/密钥的。真的请求哪个模型由 `api_model` 决定。
    """
    from agents import difficulty as DIFF
    out = dict(base_cfg)
    if opt.get("local"):
        return DIFF.apply(out, difficulty)
    out["model_id"] = cred_id(opt)
    for k in ("depth", "time_limit", "qs_depth", "seed"):
        out.pop(k, None)
    for k in ("url", "api_key", "api_model", "max_tokens"):
        if opt.get(k):
            out[k] = opt[k]
    army = base_cfg.get("army") or ""
    lab = opt.get("label") or opt["id"]
    out["label"] = f"{army}方·{lab}" if army else lab
    return out


def selftest():
    ok, bad = 0, []
    # ① 本地 id 必须与 difficulty 一致（两处不一致 ⇒ 难度档会漏接管）
    from agents import difficulty as DIFF
    if tuple(DIFF.LOCAL_IDS) == tuple(LOCAL_IDS):
        ok += 1
    else:
        bad.append(f"LOCAL_IDS 与 difficulty 不一致：{LOCAL_IDS} vs {DIFF.LOCAL_IDS}")
    # ② 目录里本地项必须含 __search__，且 id 全局唯一
    cat = catalog()
    ids = [o["id"] for o in all_options()]
    if "__search__" in ids:
        ok += 1
    else:
        bad.append(f"目录缺本地 Bot `__search__`：{ids}")
    if len(ids) == len(set(ids)):
        ok += 1
    else:
        bad.append(f"目录 id 有重复：{ids}")
    # ③ 每一类至少一项
    if cat["local"] and cat["api"]:
        ok += 1
    else:
        bad.append(f"目录缺类：local={len(cat['local'])} api={len(cat['api'])}")
    # ④ is_local 与目录的 local 标记一致（含 __local__ 也算本地）
    if all(is_local(o["id"]) == bool(o["local"]) for o in all_options()):
        ok += 1
    else:
        bad.append("is_local 与目录 local 标记不一致")
    # ⑤ 未就绪的条目 readiness 必须为假，且**带原因**（防"点了没反应"）
    bad_why = [o["id"] for o in all_options()
               if not readiness(o)[0] and not readiness(o)[1]]
    if not bad_why:
        ok += 1
    else:
        bad.append(f"未就绪却没给原因：{bad_why}")
    # ⑥ 本地项走 apply 后必须仍被难度档认作"本地"（否则难度档会漏接管一席）
    try:
        c = apply({"army": "魏", "model_id": "__search__"} , cat["local"][0], 3)
        if DIFF.is_local(c):
            ok += 1
        else:
            bad.append(f"本地席位 apply 后不被认作本地：{c.get('model_id')}")
    except Exception as e:                             # noqa: BLE001
        bad.append(f"apply(本地) 抛异常：{type(e).__name__}: {e}")
    # ⑦ **`catalog()` 不许把 `disabled` / `key_from` 剥掉**（防复发）
    #    实测踩过（2026-10-02）：白名单漏了 `disabled` ⇒ `readiness()` 永远读不到
    #    ⇒ "显式停用"功能**从来没有生效过**，欠费条目照样能在下拉里选中。
    #    这类 bug 的共同特征：**功能看起来写好了，但被上一层静默过滤掉** ——
    #    只有"从目录取回来再看一眼"才能抓到，所以断言必须走 `catalog()` 出口。
    try:
        fake = {CONF_KEY: {"local": [{"id": "__search__", "label": "L"}],
                           "api": [{"id": "A", "label": "A", "disabled": True,
                                    "key_from": "B", "api_model": "real-model"}]}}
        got = catalog(fake)["api"][0]
        miss = [k for k in ("disabled", "key_from", "api_model") if k not in got]
        if not miss and got["disabled"] is True and got["key_from"] == "B":
            ok += 1
        else:
            bad.append(f"catalog() 把字段剥掉了（缺 {miss}）：{got}")
    except Exception as e:                             # noqa: BLE001
        bad.append(f"catalog() 字段保真检查抛异常：{type(e).__name__}: {e}")
    # ⑧ `key_from` 不写 `api_model` ⇒ 必须判"不就绪"（否则会静默换成别的模型）
    try:
        o = {"id": "X", "key_from": "google/diffusiongemma-26b-a4b-it", "local": False}
        r, why = readiness(o)
        if (not r) and why:
            ok += 1
        else:
            bad.append(f"key_from 缺 api_model 却没被拦下：{r} / {why!r}")
    except Exception as e:                             # noqa: BLE001
        bad.append(f"key_from 守卫抛异常：{type(e).__name__}: {e}")
    print(f"seats.py 自检：{ok} 通过 / {len(bad)} 失败")
    for b in bad:
        print("  ✗", b)
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(selftest())
