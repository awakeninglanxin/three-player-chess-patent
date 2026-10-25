# -*- coding: utf-8 -*-
"""
三方 LLM 主控：OpenAI 兼容协议客户端

密钥不落盘在本项目里 —— 默认从 ~/.workbuddy/models.json 按 model_id 取 url/apiKey，
也可以用 agents.json 里的 url / api_key / api_model 直接覆盖（例如换豆包）。

【本机网络注意（2026-09-22 实测）】
- 本机直连 HTTPS 不通，必须走系统代理（环境变量 HTTP_PROXY / HTTPS_PROXY）。
  删掉环境变量没用：Windows 上 urllib 还会从注册表读代理设置。
  所以这里用 build_opener(ProxyHandler(None)) 走系统代理；
  只有 cfg["no_proxy"]=True 时才显式禁用代理。
- 代理会间歇性返回 502 / 连接超时 → 网络层自带重试 + 指数退避。
- 连续网络失败会置 offline，本步直接降级到本地 Bot，
  避免每一步都干等 「重试×超时」 把整局拖死。
"""
import json
import os
import re
import time
import urllib.error
import urllib.request

MODELS_JSON = os.path.expanduser("~/.workbuddy/models.json")
HERE = os.path.dirname(os.path.abspath(__file__))

# 这些 HTTP 状态码值得重试（代理抖动 / 限流 / 网关错误）
RETRYABLE_HTTP = (408, 409, 425, 429, 500, 502, 503, 504)

SYSTEM_TMPL = """你是「三人中国象棋（鼎棋）」对局中的【{army}】方主控 AI。
目标：吃掉另外两方的"帅"；棋盘上只剩你一方的帅时你获胜。

【规则要点】
- 点位编号 3 位 = 方(1魏/2吴/3蜀) + 行(1底线..5河线) + 列(1右..9左)。例 111=魏方底线右端車。
- 行棋顺序 魏→吴→蜀→魏…，每回合一步。
- 車炮走直线；馬走"日"字（一个方向 1 格 + 另一方向 2 格，共 8 个落点）、马腿被占则不能走；象走两点不过河；
  士与帅每步一格限本方王宫；兵每步一格。
- 兵过河前只能沿两个前方方向前进；过河后可行可退，但不能退回本方河界。
- 被将军必须先解将；将军期间第三方停走（其子不可通过、不可被吃）。
- 不可自暴其帅，不可让两帅照面。
- 吃掉一方帅后该方出局，其残兵全部归你收编（仍按原坐标体系走子）。

【决策】在【合法着法】列表里挑一步，优先吃大子与斩帅，别暴露自己的帅。

【输出】只输出一行 JSON，前后不加任何文字、不用代码块、不写推理过程：
{{"move":"112-141","reason":"20字以内"}}
move 必须从【合法着法】里逐字复制。"""


# ---------------------------------------------------------------- 配置
def load_roster(path=None):
    with open(path or os.path.join(HERE, "agents.json"), encoding="utf-8") as f:
        return json.load(f)


def _load_models():
    if not os.path.exists(MODELS_JSON):
        return {}
    try:
        with open(MODELS_JSON, encoding="utf-8") as f:
            return {m["id"]: m for m in json.load(f) if isinstance(m, dict) and "id" in m}
    except Exception:
        return {}


def resolve(cfg):
    """把 agents.json 里的一方配置解析成 (url, api_key, api_model, label)"""
    models = _load_models()
    base = models.get(cfg.get("model_id", ""), {})
    url = cfg.get("url") or base.get("url") or ""
    key = cfg.get("api_key") or base.get("apiKey") or ""
    model = cfg.get("api_model") or cfg.get("model_id") or ""
    label = cfg.get("label") or base.get("name") or model
    if url and not url.rstrip("/").endswith("chat/completions"):
        url = url.rstrip("/") + "/chat/completions"
    return url, key, model, label


def describe(cfg):
    url, key, model, label = resolve(cfg)
    return {"label": label, "model": model, "url": url,
            "has_key": bool(key), "key_tail": key[-6:] if key else ""}


# ---------------------------------------------------------------- 解析
def _reason_of(text):
    m = re.search(r'"?reason"?\s*[:：]\s*"([^"]{0,80})"', text)
    if m:
        return m.group(1).strip()
    m = re.search(r"[（(]([^）)]{2,40})[）)]", text)
    return m.group(1).strip() if m else ""


def parse_move(text, legal):
    """从模型输出里抽出合法着法。兼容多种写法，返回 (move|None, reason)。

    容忍形态：
      {"move":"112-141","reason":"..."}
      112-141 / 112 → 141 / 112 到 141 / **132-135**（炮二平五）
      只给出唯一可达的目标点（如仅回复 141）
    """
    if not text:
        return None, ""
    legal_set = {f"{a}-{b}" for a, b in legal}

    # 1) JSON 字段优先
    pre = []
    for m in re.finditer(r'"?move"?\s*[:：]\s*"([^"]{2,24})"', text):
        mm = re.search(r"([0-9]{3})\s*[-—–→>]\s*([0-9]{3})", m.group(1))
        if mm:
            pre.append((mm.group(1), mm.group(2)))

    # 2) 正文里任意一段「点位 + 分隔符 + 点位」
    body = [(m.group(1), m.group(2)) for m in
            re.finditer(r"([0-9]{3})\s*[-—–→>]\s*([0-9]{3})", text)]
    # 3) 「112 到 141」这类中文连接词
    body += [(m.group(1), m.group(2)) for m in
             re.finditer(r"([0-9]{3})\s*(?:到|至|吃|走|至点)\s*([0-9]{3})", text)]

    for a, b in pre + body:
        if f"{a}-{b}" in legal_set:
            return f"{a}-{b}", _reason_of(text)

    # 4) 兜底：只给了目标点，且该目标点在本回合唯一可达
    tos = {}
    for a, b in legal:
        tos.setdefault(b, []).append(a)
    for n in reversed(re.findall(r"(?<![0-9])([0-9]{3})(?![0-9])", text)):
        if n in tos and len(tos[n]) == 1:
            return f"{tos[n][0]}-{n}", _reason_of(text)
    return None, ""


# ---------------------------------------------------------------- Agent
class LLMAgent:
    """一次 forward 出一个着法；解析失败由调用方按 fallback 处理"""

    NET_RETRY = 3          # 网络层重试次数（代理抖动）
    RECHECK_SEC = 25.0     # 离线后多久再试一次网络
    OFFLINE_AFTER = 2      # 连续网络失败多少次判定离线

    def __init__(self, cfg, timeout=120):
        self.cfg = cfg
        self.url, self.key, self.model, self.label = resolve(cfg)
        # 推理模型（DeepSeek-V4 / Agnes 等）会先吐 reasoning 再吐正文，
        # 实测 reasoning 可达 2800~3000 字。max_tokens 给 1200/2000 时
        # 正文必然为空 —— 这是最初「9 手全部回退」的真正原因。
        # 所以默认给 8000，给用户留足压缩空间。
        self.max_tokens = cfg.get("max_tokens", 8000)
        self.timeout = cfg.get("think_timeout", timeout)
        self.temperature = cfg.get("temperature", 0.25)
        # 透传额外参数（如 reasoning_effort / top_p），未配置则不带
        self.extra = cfg.get("extra") or {}

        # 显式控制代理：默认跟随系统代理（本机必须走代理才能出网）
        if cfg.get("no_proxy"):
            self.opener = urllib.request.build_opener(
                urllib.request.ProxyHandler({}))
        else:
            self.opener = urllib.request.build_opener()

        self.offline = False
        self.offline_at = 0.0
        self.consec_fail = 0
        self.stats = {"calls": 0, "retries": 0, "fallbacks": 0,
                      "ptokens": 0, "ctokens": 0, "latency": [], "netfail": 0}
        self.last_error = ""

        # ---- 每步明细（供 Arena 的「预算-表现曲线」用）----
        # stats["ptokens"] 是**累计值**，而曲线要的是"这一步花了多少"。
        # 不给明细就画不出「token 花在哪、值不值」，只能看到一个总数。
        self.step_log = []
        self._prev_tok = (0, 0)

    def _log_step(self, ok, dt, note=""):
        """记一步的 token 增量与耗时（成功/失败都记，失败率本身是重要指标）"""
        p, c = self.stats["ptokens"], self.stats["ctokens"]
        dp, dc = p - self._prev_tok[0], c - self._prev_tok[1]
        self._prev_tok = (p, c)
        self.step_log.append({"ok": bool(ok), "latency": round(dt, 2),
                              "ptokens": dp, "ctokens": dc,
                              "total_tokens": dp + dc, "note": str(note)[:80]})

    # ------------------------------------------------------------ 调用
    def _build_req(self, messages):
        body = {"model": self.model, "messages": messages,
                "temperature": self.temperature, "max_tokens": self.max_tokens,
                "stream": False}
        body.update(self.extra)
        return urllib.request.Request(
            self.url, data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {self.key}",
                     "User-Agent": "sanchixiangqi/1.0"})

    def _post(self, messages):
        """发一次请求（含网络层重试）。返回 (正文, 耗时秒)。"""
        req = self._build_req(messages)
        last = "网络重试耗尽"
        for att in range(self.NET_RETRY):
            t0 = time.time()
            try:
                with self.opener.open(req, timeout=self.timeout) as r:
                    data = json.loads(r.read().decode("utf-8", "replace"))
                break
            except urllib.error.HTTPError as e:
                detail = ""
                try:
                    detail = e.read()[:180].decode("utf-8", "replace")
                except Exception:
                    pass
                last = f"HTTP {e.code}: {detail}"
                if e.code in RETRYABLE_HTTP and att < self.NET_RETRY - 1:
                    time.sleep(1.5 * (att + 1))
                    continue
                self.last_error = last
                raise RuntimeError(last)
            except Exception as e:                      # URLError / 超时 / socket
                last = f"{type(e).__name__}: {str(e)[:140]}"
                self.net_fail_inc()
                if att < self.NET_RETRY - 1:
                    time.sleep(1.5 * (att + 1))
                    continue
                self.last_error = last
                raise RuntimeError(last)
        else:                                           # pragma: no cover
            raise RuntimeError(last)

        dt = time.time() - t0
        self.stats["latency"].append(round(dt, 2))
        usage = data.get("usage") or {}
        self.stats["ptokens"] += usage.get("prompt_tokens", 0) or 0
        self.stats["ctokens"] += usage.get("completion_tokens", 0) or 0
        msg = data["choices"][0]["message"]
        content = (msg.get("content") or "").strip()
        reason = (msg.get("reasoning_content") or msg.get("reasoning") or "")
        if not content:
            raise RuntimeError(
                f"模型只回了推理内容({len(reason)}字)没有正文 —— "
                f"max_tokens={self.max_tokens} 偏小，推理把额度吃光了（调大即可）")
        return content, dt

    def net_fail_inc(self):
        self.consec_fail += 1
        self.stats["netfail"] = self.consec_fail
        if self.consec_fail >= self.OFFLINE_AFTER:
            self.offline = True
            self.offline_at = time.time()

    def net_ok(self):
        self.consec_fail = 0
        if self.offline:
            self.offline = False

    def probe(self):
        """轻量连通性自检（供 Web 端 / 一键脚本用）"""
        try:
            txt, dt = self._post([{"role": "user", "content": "只回复两个字：可以"}])
            self.net_ok()
            return {"ok": True, "latency": round(dt, 2), "reply": txt[:40]}
        except Exception as e:
            return {"ok": False, "error": str(e)[:200]}

    # ------------------------------------------------------------ 决策
    def choose(self, state, legal, text, army_name=""):
        """统一接口：choose(state, legal, text, army_name)"""
        # 离线快速降级：网络故障时不让整局干等
        if self.offline and time.time() - self.offline_at < self.RECHECK_SEC:
            self._log_step(False, 0.0, "离线降级")
            return {"move": None, "reason": "模型离线（网络故障，快速降级）",
                    "raw": "", "ok": False, "latency": 0.0, "usage": {}}

        base = [{"role": "system", "content": SYSTEM_TMPL.format(army=army_name)},
                {"role": "user", "content": text}]
        msgs, last_err = base, ""
        tries = self.cfg.get("max_retry", 2) + 1
        for attempt in range(tries):
            reply, dt = "", 0.0
            try:
                reply, dt = self._post(msgs)
                self.net_ok()
                self.stats["calls"] += 1
                mv, reason = parse_move(reply, legal)
                if mv:
                    self._log_step(True, dt)
                    return {"move": mv, "reason": reason, "raw": reply, "ok": True,
                            "latency": round(dt, 2),
                            "usage": {"prompt": self.stats["ptokens"],
                                      "completion": self.stats["ctokens"]}}
                last_err = f"输出里没有合法着法：{reply[:120]!r}"
            except Exception as e:
                last_err = str(e)[:200]
                # 网络类故障：已离线则不必再耗重试
                if self.offline:
                    break
            if attempt < tries - 1:
                self.stats["retries"] += 1
                msgs = base + ([{"role": "assistant", "content": reply}] if reply else []) + \
                    [{"role": "user",
                      "content": "上一次回复不合规：" + last_err +
                                 "\n请重新判断，只输出一行 JSON，move 必须严格取自合法着法列表。"}]
        self.stats["fallbacks"] += 1
        self._log_step(False, 0.0, last_err)
        return {"move": None, "reason": last_err, "raw": "", "ok": False,
                "latency": 0.0, "usage": {}}


# ---------------------------------------------------------------- 自检
def test_all(roster=None, army_names=None):
    """连通性自检：逐方发一次最小请求"""
    roster = roster or load_roster()
    out = []
    for key in ("1", "2", "3"):
        cfg = roster["players"][key]
        info = describe(cfg)
        info["army"] = cfg.get("army")
        try:
            agent = LLMAgent(cfg, timeout=45)
            r = agent.probe()
            if r["ok"]:
                info.update({"ok": True, "latency": r["latency"], "reply": r["reply"]})
            else:
                info.update({"ok": False, "error": r["error"]})
        except Exception as e:
            info.update({"ok": False, "error": f"{type(e).__name__}: {str(e)[:160]}"})
        out.append(info)
    return out


if __name__ == "__main__":
    for r in test_all():
        flag = "OK  " if r["ok"] else "FAIL"
        print(f"[{flag}] {r['army']}方 {r['label']:<30s} model={r['model']:<28s} "
              f"{r.get('latency', '')}s {r.get('reply', r.get('error', ''))}")
