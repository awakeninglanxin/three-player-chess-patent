# -*- coding: utf-8 -*-
"""三人象棋 · 本地 HTTP 服务（标准库实现，无第三方依赖）

GET  /               -> 观战界面
GET  /api/board      -> 棋盘几何（点位 / 直线 / 王宫 / 领地）
GET  /api/state      -> 对局快照
POST /api/new        -> 重开一局
POST /api/auto       -> {"on": true|false} 自动/暂停
POST /api/step       -> 单步
POST /api/replay     -> {"i": 第几手} 回看那一刻的局面（**只读**）
POST /api/hint       -> {"army":1|2|3, "plies":9, "budget":60} 一键推荐下一步
                        （**只读**：默认 9 plies 秒回；12/15 为可选慢档，
                          只在棋盘上示意，不落子）
POST /api/undo_config-> {"on": true|false, "per_side": 3} 悔棋开关
POST /api/undo       -> {"army": 1|2|3} 手动悔棋（可省 army）
POST /api/difficulty -> {"level": 1..5} Bot 难度档（1 新手 / 2 入门 3 plies /
                        3 进阶 6 plies / 4 大师 9 plies / 5 宗师 12 plies；
                        默认第二档。★ 2026-10-02 撤除原第 6 档「传奇 15 plies」，
                        越界值（如老前端发的 6）会被夹到最高档 5，不报错）
POST /api/options    -> {"max_ply": 120} 调手数上限（网页下拉框用，24–300）
GET  /api/agents     -> 三方配置与连通性
GET  /healthz        -> 平台探活（只回 {"ok":true}，不碰对局）
"""
import json
import os
import sys
import threading
import time
import webbrowser
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

# 静态资源版本号：每次启动服务都不同，用于强制浏览器丢弃缓存里的旧 app.js/style.css。
#   老师 2026-09-24 报的「勾了魏但 Bot 还是替魏走」就是旧 app.js 被缓存导致的
#   —— 页面（index.html）是新版、脚本却是旧版，勾选框根本没绑事件。
_STAMP = str(int(time.time()))

from match import Match                                    # noqa: E402
from engine import geometry_dxf as G                           # noqa: E402
from agents import llm as LLM                              # noqa: E402
from agents import difficulty as DIFF                      # noqa: E402

WEB = os.path.join(os.path.dirname(HERE), "web")
MIME = {".html": "text/html; charset=utf-8", ".js": "application/javascript; charset=utf-8",
        ".css": "text/css; charset=utf-8", ".json": "application/json; charset=utf-8",
        ".svg": "image/svg+xml", ".png": "image/png", ".ico": "image/x-icon"}

MATCH = None
BOARD_JSON = None


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *a):                       # 静音，避免刷屏
        pass

    # ---------------------------------------------------------- 工具
    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False)
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        try:
            return json.loads(self.rfile.read(n).decode("utf-8", "replace") or "{}")
        except Exception:
            return {}

    def _static(self, rel):
        path = os.path.normpath(os.path.join(WEB, rel.lstrip("/")))
        if not path.startswith(WEB) or not os.path.isfile(path):
            return self._send(404, {"error": "not found"})
        ext = os.path.splitext(path)[1].lower()
        if ext in (".html", ".htm"):
            # 把 index.html 里的 __STAMP__ 换成启动时间戳（防旧 JS/CSS 缓存）
            with open(path, "r", encoding="utf-8") as f:
                body = f.read().replace("__STAMP__", _STAMP)
            return self._send(200, body.encode("utf-8"),
                              MIME.get(ext, "text/html; charset=utf-8"))
        with open(path, "rb") as f:
            self._send(200, f.read(), MIME.get(ext, "application/octet-stream"))

    # ---------------------------------------------------------- 路由
    def do_GET(self):
        p = self.path.split("?")[0]
        if p in ("/", "/index.html"):
            return self._static("index.html")
        if p == "/healthz":
            return self._send(200, {"ok": True})
        if p == "/api/board":
            return self._send(200, BOARD_JSON)
        if p == "/api/state":
            snap = MATCH.snapshot()
            # 带上构建戳：前端发现服务器的戳与自己页面里的不一致 → 说明服务重启过
            #（代码已更新），自动 reload，永远不用老师手动清缓存/Ctrl+F5。
            snap["build"] = _STAMP
            return self._send(200, snap)
        if p == "/api/agents":
            return self._send(200, {
                "roster": MATCH.roster["players"],
                "resolved": {k: v for k, v in MATCH.meta.items()},
                "options": MATCH.opts,
            })
        return self._static(p)

    def do_POST(self):
        global MATCH
        p = self.path.split("?")[0]
        body = self._body()
        if p == "/api/options":
            # 手数上限可调（老师 2026-10-25：「把 max_ply 作为可调的选项，默认网页调到 120」）。
            #   只改内存里的 opts，不写回 agents.json；重启仍是文件里的默认值。
            #   目前只认 max_ply 一个字段，别的字段一律忽略并回报错误，前端好照实刷新。
            if "max_ply" not in body:
                return self._send(400, {"ok": False, "error": "没有可设置的字段（只支持 max_ply）"})
            return self._send(200, MATCH.set_max_ply(body["max_ply"]))
        if p == "/api/new":
            MATCH.pause()
            MATCH.reset()
            return self._send(200, {"ok": True, "state": MATCH.snapshot()})
        if p == "/api/discard_save":
            # 丢弃续局存档（老师 2026-10-01）：清盘 + 删存档文件，下次启动不再续
            return self._send(200, MATCH.discard_save())
        if p == "/api/auto":
            on = bool(body.get("on"))
            MATCH.play() if on else MATCH.pause()
            return self._send(200, {"ok": True, "auto": MATCH.auto})
        if p == "/api/step":
            MATCH.single_step()
            return self._send(200, {"ok": True})
        if p == "/api/move":
            return self._send(200, MATCH.manual_move(body.get("from", ""), body.get("to", "")))
        if p == "/api/replay":
            # 回看（**只读**，绝不改对局）：{i: 第几手} → 那一手走完时的局面。
            #   老师 2026-09-24 夜：「点击一次回退一个，可以一直往前回退，
            #   弄个按钮继续下，这样我就知道 bot 走哪里了」。
            #   i 省略 / 负数 / 越界 → 最新一手。与 /api/move 不同，这里**不做**
            #   任何人类接管校验（看棋永远允许）。
            return self._send(200, MATCH.replay_at(body.get("i")))
        if p == "/api/hint":
            # 一键推荐下一步（**只读**，老师 2026-10-01）：
            #   「可以一键推荐人类玩家走一下一步在棋盘上示意，但不帮他落子。
            #     用蓝色虚线箭头加文字示意，推荐下一步必须专业，
            #     用上你最高档的 12 plies 的下棋智商」
            #   body 全可省：{army: 1|2|3, plies: 9, budget: 60}
            #   ★【2026-10-02 老师定】默认档 12 → **9**：「12 用的时间太长了」。
            #     依据见 `Match.HINT_BUDGET` 上方的两批实测定档注。
            #   ⚠️ 与 /api/move 的**本质区别**：这里绝不落子、绝不改状态。
            #      返回的只是一条"建议"，由前端画成蓝虚线；老师自己点不点、走不走
            #      完全由他决定。为可验证起见 Match.hint() 内部用深拷贝局面搜索。
            #   ⚠️ 12 plies 要 40+ 秒（长考），前端必须异步等、不能当同步接口用。
            return self._send(200, MATCH.hint(army=body.get("army"),
                                              plies=body.get("plies"),
                                              budget=body.get("budget")))
        if p == "/api/undo_config":
            # 网页勾选框：{on: true|false, per_side: 3}
            return self._send(200, MATCH.set_undo(body.get("on"), body.get("per_side")))
        if p == "/api/rule_config":
            # 《一.5》连吃上限：{chain_limit: 3}；传空串或 null = 不限制
            # 《一、3》约定步数：{steps_per_turn: 2}；空 / 1 = 传统（走一步即轮转）
            if "steps_per_turn" in body:
                return self._send(200,
                                  MATCH.set_steps_per_turn(body.get("steps_per_turn")))
            return self._send(200, MATCH.set_chain_limit(body.get("chain_limit")))
        if p == "/api/undo":
            # 手动悔棋：{army: 1|2|3}，不传则悔最后走棋那一方
            return self._send(200, MATCH.undo_last(body.get("army")))
        if p == "/api/resign":
            # 认输：{army: 1|2|3}，不传则当前回合方。
            # 老师 2026-09-24 口径：「不存在求和，只允许认输」
            return self._send(200, MATCH.resign(body.get("army")))
        if p == "/api/takeover":
            # 人类接管：{army: 1|2|3} —— 把行棋权交给指定一方
            # 老师 2026-09-24：「人类接管当前回合」按下后可选三方任一方接着下
            return self._send(200, MATCH.takeover(body.get("army")))
        if p == "/api/human_config":
            # 人类接管哪些方：{armies: [1,2]} —— 其余方由 Bot 自动接管
            # 老师 2026-09-24：「人类接管可任选一方，剩下两方或一方就是 bot 自动接管。」
            return self._send(200, MATCH.set_human(body.get("armies")))
        if p == "/api/seat":
            # 每方主控：本地Bot / API 大模型（老师 2026-10-02）
            #   {"army": 1|2|3, "model_id": "__search__" | "deepseek-v4-flash" | "hy4" | ...}
            #   · 目录与逻辑在 agents/seats.py + agents.json 的 model_options
            #   · 未就绪的 API 条目**明确拒绝**（绝不静默换成本地 Bot）
            #   · 只换这一方的"脑子"，不动棋盘 / 轮次 / 战绩 / 规则约定
            #   · GET /api/state 的 seats / seat_options 供前端渲染下拉
            # 老师原话：「有没有可能选择让魏国给人类，另外两个接入 deepseek 和 hy4 api？」
            #          「做成可选的选项，用本地 bot 或者 api」
            return self._send(200, MATCH.set_seat(body.get("army"),
                                                  body.get("model_id")))
        if p == "/api/difficulty":
            # Bot 难度档（老师 2026-09-25）：
            #   {"level": 1|2|3|4}
            #     1 新手（不预判）/ 2 入门（3 plies）/ 3 进阶（6 plies）/
            #     4 大师（9 plies）/ 5 宗师（12 plies，最高档）
            #   GET /api/state 的 difficulty / difficulty_levels 供前端高亮与画按钮。
            return self._send(200, MATCH.set_difficulty(body.get("level")))
        if p == "/api/reload_agents":
            MATCH.pause()
            MATCH = Match(LLM.load_roster())
            return self._send(200, {"ok": True})
        return self._send(404, {"error": "not found"})


def main():
    global MATCH, BOARD_JSON
    # 上线托管时平台会注入 PORT，并要求绑定 0.0.0.0；
    # 本地双击「启动对弈台.bat」不走这两个分支，仍是 127.0.0.1:8771，行为不变。
    env_port = os.environ.get("PORT")
    port = int(env_port) if (env_port or "").isdigit() else 8771   # 专利版固定用 8771，避开标准鼎棋版的 8770
    host = os.environ.get("HOST") or ("0.0.0.0" if env_port else "127.0.0.1")
    force_local = "--local" in sys.argv
    for i, a in enumerate(sys.argv):
        if a == "--port" and i + 1 < len(sys.argv):
            port = int(sys.argv[i + 1])
    BOARD_JSON = G.BOARD.summary()
    roster = LLM.load_roster()
    # ---- 公开演示模式（老师 2026-10-25 投稿用）----
    #   `--demo`（或 SANCHI_DEMO=1）：三方**全归 Bot**，且不改本机的 agents.json。
    #   为什么需要：agents.json 里 `human_armies: [1]` 是老师自己下棋时的设置，
    #   轮到魏方就等人走 —— 访客点「自动对弈」会一动不动（实测 ply 恒 0）。
    #   演示站要的是「打开、点自动对弈、立刻能看」。
    demo = ("--demo" in sys.argv) or os.environ.get("SANCHI_DEMO") == "1"
    if demo:
        roster.setdefault("options", {})["human_armies"] = []
        print("  [演示模式] 三方全 Bot（忽略 agents.json 的 human_armies）")
    if force_local:
        # 演示模式：不调用任何大模型，完全不依赖外网
        # （断网、或代理挂了的时候照样能看界面和完整对局）
        #
        # ★【2026-09-25 改】旧版把三方**一律**打回 `__local__`（一步贪心），
        #   等于「离线模式 = 最弱档」——老师要「提高 bot 智商」时，
        #   配置里写好的 `__search__`（树状多层预判）被这里悄悄覆盖，
        #   现象就是「改了 agents.json 却不生效，日志里还是『估值 +0.8』」。
        # ★【2026-09-25 二次改 · 接入难度档】现在这里只做**降级标记**：
        #   把「需要联网」的模型换成档位对应的本地 Bot；至于**用哪一档**
        #   （新手/入门/进阶/大师），统一交给 `Match.apply_difficulty` 按
        #   agents.json 的 options.difficulty（默认第二档）或网页按钮决定 ——
        #   离线也能享受四档难度，且与网页「难度」按钮永远一致。
        lv = DIFF.get(roster.get("options", {}).get("difficulty"))
        for _k, cfg in roster["players"].items():
            if (cfg.get("model_id") or "") not in ("__search__", "__local__"):
                cfg.update(DIFF.apply(cfg, lv["level"]))
                cfg["label"] = f"{cfg['label']}·离线"
    MATCH = Match(roster)
    # ---- 续局：启动时自动接上上一局（老师 2026-10-01）----
    #   老师：「如何设计能否重启网页后继续之前的棋局继续下？」
    #   ⇒ 每手落盘（Match._autosave）+ 启动恢复（restore）。
    #   `--fresh` 强制开新局（旧存档另存备份，不删）。
    #   `--nosave` **完全禁用自动存盘**（给"另起一个端口做隔离自查"用：
    #     例 `--port 8772 --fresh --nosave` —— 无头浏览器自查时要有一个
    #     没有别的标签页抢搜索锁的干净实例，但**绝不能**让它把老师真实那一局冲掉）。
    #   ⚠️ **只有这里**开启自动存盘：tests 里成百上千个 `Match()` 一律不落盘，
    #      否则跑一次回归就把老师正在下的一局冲掉了。
    _resume = ({"restored": False}
               if "--nosave" in sys.argv
               else MATCH.enable_autosave(restore=("--fresh" not in sys.argv)))
    # ---- numba 内核预热（方案 ①）----
    #   首次调用要现场编译（本机实测 ~20s），若等到老师走第一手棋时才编译，
    #   那一手会"卡 20 秒"（看起来像死机）。这里放**后台线程**预热：
    #   服务照常秒起，编译与老师的看棋盘/点按钮同时进行。
    #   预热后 nps 从 ~3 万升到 ~43 万（同层数提速 12~22 倍）。
    def _warm_jit():
        try:
            from agents import search_bot as _SB
            _SB._jit_warmup()
            print("  [numba] 内核预热完成")
        except Exception as e:                       # numba 缺失等 → 静默降级
            print(f"  [numba] 预热跳过：{e}")
    threading.Thread(target=_warm_jit, daemon=True).start()

    srv = ThreadingHTTPServer((host, port), Handler)
    show = "127.0.0.1" if host in ("0.0.0.0", "::") else host
    url = f"http://{show}:{port}/"
    print("=" * 62)
    print("  三人中国象棋 · 专利版对弈台")
    print("  规则特征：副帅 / 军帐 / 生命力与战斗力 / 允许送将 / 只过一次界")
    print(f"  点位 {len(G.BOARD.xy)} 个（名义 135 / 实际落子 132），中央赤壁三角区边长 8")
    for k, v in MATCH.meta.items():
        print(f"  {k}号位  {v['label']:<34s} {v['model']}  key={'有' if v['has_key'] else '缺'}")
    _lv = DIFF.describe(MATCH.difficulty)
    print(f"\n  Bot 难度档： [{_lv['level']}] {_lv['name']}（{_lv['brief']}）"
          f"  ← 网页「难度」按钮可切换 1/2/3/4 档")
    if force_local:
        print("\n  [演示模式] 三方均为本地 Bot，不调用任何大模型。")
    if _resume.get("restored"):
        _sa = _resume.get("saved_at") or 0
        print(f"\n  ↻ 已续上上一局：第 {_resume.get('ply')} 手，"
              f"轮到 {_resume.get('turn')} 号位"
              f"（存档于 {time.strftime('%m-%d %H:%M:%S', time.localtime(_sa))}）")
        print("     想开新局：网页点「重开一局」，或重启时加 --fresh")
    else:
        print(f"\n  · 新开一局（{_resume.get('reason')}）")
    print(f"\n  观战地址： {url}")
    print("=" * 62)
    # 部署环境（有 PORT）不自动弹浏览器：容器里没有可用浏览器，弹只会报错
    if not env_port and os.environ.get("SANCHI_NO_BROWSER") != "1":
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")


if __name__ == "__main__":
    main()
