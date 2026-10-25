# -*- coding: utf-8 -*-
"""
自对弈产能标定 —— 决定 AutoDL 该买几核 / 跑几小时的**唯一依据**。

测什么：
  ① 单进程 JIT 预热耗时（nb_core 一律不加 cache=True ⇒ 每个新进程都要重编译）
  ② N 进程并行的**有效产能**（局/秒）
  ③ 外推：10 万局 / 30 万局 需要多久

⚠️ 平台差异（很重要）：
  Windows 用 spawn ⇒ 每个子进程都要**各自**重新 JIT（预热耗时 ×N，但并行所以是 1 个预热时长）
  Linux  用 fork  ⇒ 父进程 `warmup()` 后 fork，子进程**白嫖**已编译产物 ⇒ 零预热
  AutoDL 是 Linux ⇒ 实际比这里测出来的还要快一点。

用法：
  python tests/_bench_selfplay_throughput.py            # 默认 1/2/4/8/12 进程
  python tests/_bench_selfplay_throughput.py 12 30      # 只测 12 进程，每进程 30 局
"""
import multiprocessing as mp
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SRV = os.path.abspath(os.path.join(HERE, "..", "server"))
for _p in (SRV, os.path.join(SRV, "engine"), os.path.join(SRV, "agents")):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _one(args):
    """子进程任务：先按需预热，再产 n 局。返回 (局数, 产局耗时秒, 预热秒)"""
    n, tl, maxply, seed0, warm = args
    from agents import selfplay as SP
    from agents import eval_dxf as E

    t_warm = 0.0
    if warm:
        t0 = time.time()
        SP.play_one(dict(E.DEFAULT_W), 8, tl, 1)      # 短局，只为触发 JIT
        t_warm = time.time() - t0

    w = dict(E.DEFAULT_W)
    t0 = time.time()
    done = 0
    for i in range(n):
        SP.play_one(w, maxply, tl, seed0 + i * 7919)
        done += 1
    return done, time.time() - t0, t_warm


def bench(nproc, per_proc, tl, maxply, warm):
    t0 = time.time()
    pool = mp.Pool(processes=nproc)
    res = pool.map(_one, [(per_proc, tl, maxply, 1000 + k * 100003, warm)
                          for k in range(nproc)])
    pool.close()
    pool.join()
    wall = time.time() - t0
    games = sum(r[0] for r in res)
    warm_max = max(r[2] for r in res)
    # 子进程各自的纯产局耗时（并行，取最大 = 关键路径）
    produce = max(r[1] for r in res)
    return dict(nproc=nproc, games=games, wall=wall,
                produce=produce, warm=warm_max,
                rate=games / wall if wall > 0 else 0.0)


def main():
    argv = sys.argv[1:]
    if argv:
        nprocs = [int(argv[0])]
        per = int(argv[1]) if len(argv) > 1 else 20
    else:
        cpu = os.cpu_count() or 4
        nprocs = sorted(set([1, 2, 4, 8, cpu]))
        per = 12

    tl = float(os.environ.get("SANCHI_TL", "0.02"))
    maxply = int(os.environ.get("SANCHI_MAXPLY", "250"))
    warm = os.environ.get("SANCHI_NO_WARM", "") == ""

    print("=" * 78)
    print(f"自对弈产能标定   逻辑核={os.cpu_count()}   "
          f"tl={tl}s  maxply={maxply}  每进程 {per} 局")
    print(f"启动方式={mp.get_start_method()}   "
          f"(fork=子进程白嫖父进程 JIT；spawn=各自重编译)")
    print("=" * 78)
    rows = []
    for np_ in nprocs:
        r = bench(np_, per, tl, maxply, warm)
        rows.append(r)
        print(f"  {np_:>3} 进程：{r['games']:>4} 局 / 墙钟 {r['wall']:>7.1f}s"
              f"  ⇒ {r['rate']:>6.2f} 局/秒"
              f"   〔预热 {r['warm']:.1f}s，纯产局 {r['produce']:.1f}s〕")

    print("\n" + "-" * 78)
    print("外推（按最快那档的 局/秒）")
    best = max(rows, key=lambda r: r["rate"])
    print(f"  最优档：{best['nproc']} 进程 ⇒ {best['rate']:.2f} 局/秒")
    for target, nm in ((100_000, "10 万局"), (300_000, "30 万局"), (1_000_000, "100 万局")):
        h = target / best["rate"] / 3600
        print(f"  {nm:<8} 需要 {h:>6.2f} 小时（{best['nproc']} 进程）")

    print("\n按核数线性外推（12 核实测为基准，纯 CPU 任务近似线性）")
    r12 = next((r for r in rows if r["nproc"] == 12), None)
    if r12:
        per_core = r12["rate"] / 12
        print(f"  单核 {per_core:.3f} 局/秒")
        for c in (8, 12, 16, 24, 32, 64):
            rate = per_core * c
            print(f"  {c:>3} 核 ⇒ {rate:>6.1f} 局/秒   "
                  f"10 万局 {100000 / rate / 3600:>5.2f}h   "
                  f"30 万局 {300000 / rate / 3600:>5.2f}h")
    print("=" * 78)


if __name__ == "__main__":
    main()
