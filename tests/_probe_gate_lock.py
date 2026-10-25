# -*- coding: utf-8 -*-
"""门禁锁（gate.lock）回归探针 —— 治「守护开门禁时被 autopilot 当卡死杀掉」的活锁。

【事故】2026-10-02 实测活锁：
    16:45:43 守护写出候选权重 → 开 `arena_gate` 标尺（300 局纯 CPU 对局）
    → 门禁期间 GPU 必然 0% → autopilot 心跳 16:47 / 16:49 / 16:51 都读到 0%
    → 16:51:35 autopilot 判「守护连续 360s <5% ⇒ 卡死」并 kill（EXIT=143）
    → 16:51:40 重新拉起 → 又从「[轮 1] 训 mlp_512_256」开始
  ⇒ `round` 永远停在 1，门禁永远跑不完，候选永远无法上位。
  根因是我自己的**估算错**：在 autopilot 注释里写"门禁一次约 3 分钟"，
  实测 >6 分钟 ⇒ 恰好越过 6 分钟自保阈值。

【修法】守护跑标尺前后写/删一个锁文件；autopilot 见到锁就豁免判零。
        另有「陈旧锁」兜底：锁存在超过 GATE_LOCK_MAX ⇒ 认定守护崩了留下的
        死锁，删掉（否则 autopilot 会永久失明，比原 bug 还糟）。

【本探针查什么】修法横跨两个语言/两个文件的**隐性契约**：
  ① 路径一致 —— `gpu_daemon.GATE_LOCK` 与 autopilot 的 `$GATE_LOCK` 必须
     指向同一个文件。不一致 ⇒ 豁免**静默失效**（不报任何错，只是回到活锁）。
  ② 开关确实成对 —— 守护在**异常路径**上也要删锁（`try/finally`），
     否则一次 `yard_score` 抛异常就留下永久死锁。
  ③ 陈旧锁兜底存在 —— 光有 ① ② 不够：守护被 OOM 杀 / 被 kill 时
     `finally` 不会执行，锁会永远留着。
  ④ 行为正确 —— 真跑 `_gate_lock(True/False)`，验证写、读、删。

跑法：python tests/_probe_gate_lock.py
"""
import ast
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
GD = os.path.join(ROOT, "tools", "gpu_daemon.py")
AP = os.path.join(ROOT, "tools", "cloud_autopilot.sh")

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
    print("=" * 78)
    print("门禁锁（gate.lock）· 回归探针")
    print("=" * 78)

    src_gd = open(GD, encoding="utf-8").read()
    src_ap = open(AP, encoding="utf-8").read()

    # ---------------------------------------------------------- ① 守护侧
    print("\n① 守护侧（gpu_daemon.py）")
    chk("GATE_LOCK = os.path.join(OUTDIR," in src_gd,
        "定义了模块级 `GATE_LOCK`，且挂在 `OUTDIR` 下（= server/agents/values/）")
    chk("def _gate_lock(on, note=" in src_gd, "定义了 `_gate_lock(on, note)`")
    # 开关成对：`try` 里必须紧跟 `finally`，且 finally 里关锁
    m = re.search(r"_gate_lock\(True.*?\n(.*?)\n", src_gd, re.S)
    m_try = re.search(r"_gate_lock\(True[^\n]*\n\s*try:", src_gd)
    m_fin = re.search(r"finally:\s*\n\s*_gate_lock\(False\)", src_gd)
    chk(bool(m_try), "开锁后**立刻**进 `try:`（保证任何异常路径都能走到 finally）")
    chk(bool(m_fin), "`finally:` 里 `_gate_lock(False)` —— 异常路径也删锁")
    chk(src_gd.count("_gate_lock(True") == 1,
        f"开锁点**只有一处**（实得 {src_gd.count('_gate_lock(True')} 处）"
        f"—— 防漏改第二份副本")

    # ---------------------------------------------------------- ② 路径一致
    print("\n② 隐性契约：两边指向同一个文件 ★ 本探针的核心")
    #   守护侧：GATE_LOCK = os.path.join(OUTDIR, "gate.lock")，而 OUTDIR = SRV/agents/values
    p_gd = None
    m = re.search(r"OUTDIR\s*=\s*os\.path\.join\(([^)]*)\)", src_gd)
    if m:
        p_gd = os.path.join("server", "agents", "values", "gate.lock")
    #   autopilot 侧：GATE_LOCK=$DIR/server/agents/values/gate.lock
    m2 = re.search(r"^GATE_LOCK=(.+)$", src_ap, re.M)
    ap_path = m2.group(1).strip() if m2 else None
    #   真实值：$DIR = 包根，所以期望尾部是 /server/agents/values/gate.lock
    chk(ap_path is not None, f"autopilot 定义了 `GATE_LOCK` —— 实得 {ap_path!r}")
    chk(bool(ap_path) and ap_path.endswith("/server/agents/values/gate.lock"),
        f"autopilot 的路径以 `/server/agents/values/gate.lock` 结尾 —— 实得 {ap_path!r}")
    chk("OUTDIR" in src_gd and bool(re.search(r'OUTDIR\s*=\s*os\.path\.join\(SRV,\s*"agents",\s*"values"\)', src_gd)),
        "守护的 `OUTDIR` = `<SRV>/agents/values`（与 autopilot 的 `$DIR/server/…` 同源）")

    # ---------------------------------------------------------- ③ 主控侧判据
    print("\n③ 主控侧（cloud_autopilot.sh）")
    chk(bool(re.search(r'if\s+\[\s*-f\s+"\$GATE_LOCK"\s*\]', src_ap)),
        '判零前有 `if [ -f "$GATE_LOCK" ]` 分支')
    chk("GATE_LOCK_MAX" in src_ap,
        "有陈旧锁上限 `GATE_LOCK_MAX`（守护被 OOM/kill 时 finally 不执行 ⇒ 兜底必需）")
    chk(bool(re.search(r'find\s+"\$GATE_LOCK"\s+-mmin', src_ap)),
        "用 `find -mmin` 判陈旧锁（并按上限删除）")
    # 关键：豁免分支里必须把 zero_gpu 清零，否则计数还在悄悄累加
    blk = re.search(r'if\s+\[\s*-f\s+"\$GATE_LOCK"\s*\];\s*then(.*?)fi\s*\n\s*g=\$\(nvidia-smi',
                    src_ap, re.S)
    chk(bool(blk) and "zero_gpu=0" in blk.group(1),
        "豁免分支里 `zero_gpu=0`（否则计数仍在累加，锁一消失立刻误杀）")
    chk(bool(re.search(r'^\s*rm\s+-f\s+"\$GATE_LOCK"', src_ap, re.M)),
        "陈旧锁分支里真的删了锁（`rm -f`）")

    # ---------------------------------------------------------- ④ 行为验证
    print("\n④ 行为：真跑 `_gate_lock`（写 → 读 → 删）")
    #   只抽取函数体执行，不 import 整个模块（模块顶层会拉 torch / numba）。
    try:
        tree = ast.parse(src_gd)
        fn = next(n for n in tree.body
                  if isinstance(n, ast.FunctionDef) and n.name == "_gate_lock")
        ns = {"os": os, "time": time, "GATE_LOCK": None}
        #   临时给一个沙箱路径，别碰真实锁（真实锁会让 autopilot 豁免 40 分钟）
        tmp = os.path.join(ROOT, "tests", "_gate_lock_probe.tmp")
        ns["GATE_LOCK"] = tmp
        exec(compile(ast.Module(body=[fn], type_ignores=[]), "<_gate_lock>", "exec"), ns)
        g = ns["_gate_lock"]
        for old in (tmp, tmp + ".tmp"):
            if os.path.exists(old):
                os.remove(old)

        g(True, "probe selftest")
        chk(os.path.exists(tmp), "`_gate_lock(True)` 写出了锁文件")
        txt = open(tmp, encoding="utf-8").read()
        parts = txt.strip().splitlines()
        chk(len(parts) >= 3 and parts[0].isdigit() and parts[1].isdigit(),
            f"锁内容 = 时间戳 + pid + 说明（实得 {len(parts)} 行，首行是可解析的秒级时间戳）")
        chk(abs(int(parts[0]) - int(time.time())) < 60,
            "首行时间戳是**当下**（陈旧判定靠 mtime，内容这份是给人看的）")
        chk(not os.path.exists(tmp + ".tmp"),
            "原子写：`.tmp` 中转文件已被 `os.replace` 消化（不留残余）")
        g(False)
        chk(not os.path.exists(tmp), "`_gate_lock(False)` 删掉了锁文件")
        g(False)   # 再删一次（幂等）
        chk(not os.path.exists(tmp), "重复 `_gate_lock(False)` 幂等，不抛异常")
    except StopIteration:
        chk(False, "在源码里找到 `_gate_lock` 函数定义")
    except Exception as e:                        # noqa: BLE001
        chk(False, f"行为验证抛异常：{type(e).__name__}: {e}")

    print("\n" + "=" * 78)
    if _bad == 0:
        print(f"全部通过：{_ok}/{_ok + _bad}")
    else:
        print(f"❌ {_bad} 项失败 / 共 {_ok + _bad} 项")
    print("=" * 78)
    return 1 if _bad else 0


if __name__ == "__main__":
    sys.exit(main())
