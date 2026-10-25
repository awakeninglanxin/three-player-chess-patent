# -*- coding: utf-8 -*-
"""_probe_loop_stall.py —— 诊断「自动对弈开着却一步不走」的探针

背景（老师 2026-10-02）：
    老师报「下棋很慢」，实测发现是**根本不动**：
    `auto=True`、`finished=False`、`ply=0`、`thinking=None`、进程 CPU ≈ 0.8%，
    一步没走，`log` 里也没有任何 error / pass 记录。
    在干净实例（8772 --fresh --nosave）上**完整复现** ⇒ 与老师的配置无关。

本探针要回答的唯一问题：`_loop` 线程到底停在哪一行？

手法：`sys._current_frames()` 拿到**每个线程的当前栈帧**，逐帧打印。
    这是唯一能在"进程还在跑、但某线程不干活"时看到真相的手段
    （py-spy 在清华镜像里没有，装不上）。
"""
import os
import sys
import time
import threading
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "server"))
sys.path.insert(0, os.path.join(ROOT, "server", "agents"))

from agents import llm as LLM            # noqa: E402
from match import Match                  # noqa: E402


def dump_threads(tag):
    print("=" * 74)
    print(f"== 线程栈快照 · {tag} ==")
    frames = sys._current_frames()
    for t in threading.enumerate():
        fr = frames.get(t.ident)
        print(f"\n-- {t.name}  ident={t.ident}  daemon={t.daemon}  alive={t.is_alive()} --")
        if fr is None:
            print("   （拿不到栈帧：线程已结束？）")
            continue
        stack = traceback.extract_stack(fr)
        # 只打最后 8 帧，够定位
        for f in stack[-8:]:
            print(f"   {os.path.basename(f.filename)}:{f.lineno}  {f.name}()"
                  f"   | {f.line or ''}"[:150])


def main():
    roster = LLM.load_roster()
    print("构造 Match ...")
    m = Match(roster)
    print(f"  auto={m.auto}  alive={m.alive}  thread={m.thread.name} "
          f"is_alive={m.thread.is_alive()}")

    dump_threads("刚构造完（未开自动）")

    print("\n>>> play() 打开自动对弈 ...")
    m.play()
    print(f"  auto={m.auto}")

    for i in (1, 2, 3, 4, 5, 6):
        time.sleep(1.5)
        st = m.state
        print(f"  +{i*1.5:4.1f}s  ply={st['ply']:<3} turn={st['turn']} "
              f"thinking={m.thinking}  log={len(m.log)}  "
              f"_loop_is_alive={m.thread.is_alive()}")

    dump_threads("play() 之后 9 秒")

    print("\n" + "=" * 74)
    print("== 结论提示 ==")
    print("· 若 `_loop` 线程栈停在 `time.sleep` / `continue` ⇒ 是判断分支把它拦住了；")
    print("· 若栈停在 `_loop` 之外（如 thread 已死，抓不到栈）⇒ 线程被异常弹出；")
    print("· 若栈停在 `step()` 内部 ⇒ 是搜索/网络阻塞。")


if __name__ == "__main__":
    main()
