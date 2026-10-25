# -*- coding: utf-8 -*-
"""价值网络**懒加载**守门：没开就不许 import torch。

【为什么需要这个探针】2026-10-02 抓到一条**长期存在、极难归因**的性能 bug：

  `value_advisor.ValueAdvisor.load()` 旧写法**只在"权重文件不存在"时才短路**，
  而权重文件一旦存在（现在永远存在）⇒ 即使 `enabled=False` 也会执行
  `from agents import value_net` ⇒ **拖进 `import torch`（本机实测 ≈2.4 s）**。

  两条实测后果：
    ① 每次进程启动后的**第一次搜索白等 2.4 s** —— 魏/蜀两席明明是关的，照样付钱。
       老师重启对弈台后第一手棋 / 第一次点「推荐」会莫名慢一拍。
    ② `tests/_verify_difficulty.py` §⑫「1.0 s 预算 ⇒ 不超 2.5 s」被顶穿（2.60 s），
       而且会**永远红**，因为它把"一次性 import 开销"算进了"超时截断"。

  取证：`tests/_probe_timeout_grain.py`（首发 2.43 s / 之后 0.01 s；且
  `search_root.nopython_signatures` 前后数量不变 ⇒ 排除 JIT 编译）。
  cProfile：耗时几乎全在 `torch/nn/__init__.py` 与 `torch/_jit_internal._overload`。

【本探针怎么测】**必须用子进程**（全新解释器）—— 同进程里 torch 可能已被别人导入，
测出来必然假绿。子进程里只做一件事，然后回报 `torch in sys.modules`。

用法：python tests/_probe_value_lazy.py
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SERVER = os.path.join(ROOT, "server")

PASS, FAIL = [], []


def chk(cond, name, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'✓' if cond else '✗'} {name}" + (f"   [{detail}]" if detail else ""))
    return bool(cond)


def sub(code):
    """在**全新解释器**里跑一段代码，返回 (stdout.strip(), rc)"""
    prelude = (
        "import os, sys, json\n"
        f"sys.path.insert(0, {SERVER!r})\n"
        f"sys.path.insert(0, {os.path.join(SERVER, 'agents')!r})\n"
    )
    p = subprocess.run([sys.executable, "-c", prelude + code],
                       capture_output=True, text=True, timeout=600)
    return (p.stdout or "").strip(), p.returncode, (p.stderr or "")[-400:]


def sect(n, title):
    print("\n" + "=" * 74)
    print(f"{n}  {title}")
    print("=" * 74)


def main():
    print("=" * 74)
    print("价值网络懒加载守门：没开就不许 import torch")
    print("=" * 74)
    print(f"解释器：{sys.executable}")

    # ---------------------------------------------------------------- ①
    sect(1, "① disabled ⇒ **不许** import torch（子进程实测）")
    out, rc, err = sub(
        "from agents import value_advisor as VA\n"
        "adv = VA.ValueAdvisor.load(kind='mlp', lam=0.35, enabled=False)\n"
        "print(json.dumps({'torch': 'torch' in sys.modules,\n"
        "                  'enabled': bool(adv.enabled),\n"
        "                  'model_none': adv.model is None}))\n"
    )
    chk(rc == 0, "子进程正常退出", f"rc={rc} {err}")
    if rc == 0:
        import json
        d = json.loads(out.splitlines()[-1])
        chk(d["torch"] is False,
            "★ enabled=False ⇒ `torch` **不在** sys.modules（这就是那 2.4s 的去处）",
            f"torch={d['torch']}")
        #   ⚠️ 探针自身曾把这里写反（拿 `adv.model is not None` 的布尔值去 `is None` 判）
        #   ⇒ 改成子进程直接回报 `model is None`，语义与断言一一对应，不再有中转。
        chk(d["enabled"] is False and d["model_none"] is True,
            "disabled 顾问也没有模型（旧写法会白读一份 3.5MB 权重）",
            f"enabled={d['enabled']} model_none={d['model_none']}")

    # ---------------------------------------------------------------- ②
    sect(2, "② SearchBot(use_value=False) ⇒ 同样不许 import torch（真实入口）")
    out, rc, err = sub(
        "from search_bot import SearchBot\n"
        "b = SearchBot(depth=1, time_limit=1.0, seed=11, use_value=False)\n"
        "adv = b.advisor()\n"
        "print(json.dumps({'torch': 'torch' in sys.modules,\n"
        "                  'adv_none': adv is None,\n"
        "                  'enabled': None if adv is None else bool(adv.enabled)}))\n"
    )
    chk(rc == 0, "子进程正常退出", f"rc={rc} {err}")
    if rc == 0:
        import json
        d = json.loads(out.splitlines()[-1])
        chk(d["torch"] is False,
            "★ `SearchBot(use_value=False).advisor()` 不 import torch",
            f"torch={d['torch']}")
        chk(d["enabled"] in (False, None),
            "该顾问 enabled 为假（不会参与重排）", f"enabled={d['enabled']}")

    # ---------------------------------------------------------------- ③
    sect(3, "③ enabled=True ⇒ **必须**真的 import torch 并给出模型（不能修过头）")
    out, rc, err = sub(
        "from agents import value_advisor as VA\n"
        "adv = VA.ValueAdvisor.load(kind='mlp', lam=0.35, enabled=True)\n"
        "print(json.dumps({'torch': 'torch' in sys.modules,\n"
        "                  'enabled': bool(adv.enabled),\n"
        "                  'model': adv.model is not None}))\n"
    )
    chk(rc == 0, "子进程正常退出", f"rc={rc} {err}")
    if rc == 0:
        import json
        d = json.loads(out.splitlines()[-1])
        chk(d["torch"] is True,
            "enabled=True ⇒ torch 已导入（真要用网络时必须付这笔钱）",
            f"torch={d['torch']}")
        chk(d["enabled"] is True and d["model"] is True,
            "★ 吴方（唯一开的一席）仍能拿到模型 ⇒ 修懒加载没有把功能改坏",
            f"enabled={d['enabled']} model={d['model']}")

    # ---------------------------------------------------------------- ④
    sect(4, "④ 源码级：`if not enabled` 必须**排在** import value_net **之前**")
    src = open(os.path.join(SERVER, "agents", "value_advisor.py"),
               encoding="utf-8").read()
    #   只看 load() 的函数体，避免被别处的字样误判
    body = src.split("def load(cls", 1)[-1].split("\n    # ----", 1)[0]
    #   ★ 源码级断言必须先**剥掉注释行**再 find：
    #     修法本身的注释里就写了 `if not enabled` / `from agents import value_net`，
    #     不剥注释 ⇒ `find` 命中注释（旧版探针就是这样误报 `import@485 < enabled@1318`）。
    code = "\n".join(ln for ln in body.splitlines()
                     if not ln.strip().startswith("#"))
    i_en = code.find("if not enabled:")
    i_imp = code.find("from agents import value_net")
    i_file = code.find("os.path.exists(p)")
    chk(i_en != -1, "存在 `if not enabled:` 短路分支（剥注释后）", f"idx={i_en}")
    chk(i_imp != -1, "存在 `from agents import value_net`（真要用的那条路）", f"idx={i_imp}")
    chk(i_file != -1, "存在 `os.path.exists(p)` 权重文件判定", f"idx={i_file}")
    chk(i_en != -1 and i_imp != -1 and i_en < i_imp,
        "★ 顺序正确：先判 enabled、再判文件、最后才 import（这就是本次的修法）",
        f"enabled@{i_en} < import@{i_imp}")
    #   旧写法（"文件不存在"排在最前）必须已消失：不得出现"先判文件、后判 enabled"
    chk(i_file != -1 and i_en != -1 and i_en < i_file,
        "★ 旧顺序（先判文件、后判 enabled）已不存在 ⇒ 防退回",
        f"enabled@{i_en} < exists@{i_file}")

    print("\n" + "=" * 74)
    print(f"价值网络懒加载守门：{len(PASS)} 通过 / {len(FAIL)} 失败")
    for f in FAIL:
        print("  ✗", f)
    print("=" * 74)
    return 0 if not FAIL else 1


if __name__ == "__main__":
    sys.exit(main())
