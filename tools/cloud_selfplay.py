# -*- coding: utf-8 -*-
"""AlphaZero 化 · 云端自对弈产数据（多进程 / Linux fork 友好）

    python tools/cloud_selfplay.py --games 100000 --workers 16 --out data/selfplay_100k.npz
    python tools/cloud_selfplay.py --games 100000 --workers 16 --out ... --resume   # 断点续跑

【为什么要专写一个"云端版"】
  本机的 `tests/_train_value_net.py` 是**单进程**的：12 核只用了 1 核。
  云端有 12~64 核，必须并行才有意义。但并行有两个坑：

  ① **JIT 预热**：`engine/nb_core.py` 的 njit **一律不加 `cache=True`**
     （原因见该文件顶部：递归 njit + 磁盘缓存 = 读缓存必 SEGV）。
     ⇒ 每个**新进程**都要重新编译一次（约 10~40s）。
     · Linux `fork` 启动方式：**父进程先预热 → 再 fork** ⇒ 子进程白嫖已编译产物，零开销。
     · Windows/macOS `spawn`：每个子进程各自重编译（我们就别在 Windows 上跑大规模了）。
     本脚本在 `initializer` 里预热，`fork` 下每个 worker 只付一次极短的"继承检查"。

  ② **样本量爆炸**：一局 ~200 手 ⇒ 10 万局 = 2000 万样本 × 32 维 × 4B = **2.5 GB**。
     直接全存会打爆内存。⇒ 每局**降采样**（默认最多留 40 个局面，均匀抽样），
     10 万局 × 40 = 400 万样本 ≈ 512 MB，训练够用且放得下。

【产出】
  `--out` 指定路径的 `.npz`，含 `X`(N×32 float32) / `Y`(N float32) / `meta`(局号/方/手数)
  同名 `.json` 存统计（局数、胜负率、耗时、吞吐）。
  加 `--resume` 时会读同名分片目录 `data/selfplay_100k.parts/` 继续，已完成的片不重跑。
"""
import argparse
import json
import multiprocessing as mp
import os
import random
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRV = os.path.join(ROOT, "server")
for _p in (SRV, os.path.join(SRV, "engine"), os.path.join(SRV, "agents")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

ARMY_CN = {1: "魏", 2: "吴", 3: "蜀"}

# --------------------------------------------------------------------------
# 子进程侧
# --------------------------------------------------------------------------


def _warm():
    """每个 worker 启动时调一次：触发 JIT 编译（fork 下是近乎免费地继承）。"""
    try:
        from engine import nb_core as NB
        NB.warmup()
    except Exception as e:                                  # pragma: no cover
        print(f"  [warn] warmup 失败（不致命）：{e}", flush=True)


def _gen_chunk(task):
    """产一批局 → (X, Y, stats)。task = (start, count, tl, maxply, eps, cap, seed0)"""
    start, count, tl, maxply, eps, cap, seed0 = task

    from engine import game_dxf as GA
    from agents import features_dxf as F
    from agents.search_bot import SearchBot

    X, Y = [], []
    decisive = 0
    plies = []
    t0 = time.time()

    for g in range(start, start + count):
        seed = seed0 + g
        rng = random.Random(seed * 7919)
        s = GA.new_game(first=1 + (seed % 3))
        # ★ 2026-10-02：**显式**写 `use_value=False`，不再让它跟随
        #   `agents.json` 的 `value_net.enabled`。理由有两条：
        #     ① 对弈台上开价值网络 ≠ 自对弈也该开 —— 自对弈是"产数据"，
        #        `tl` 只有 0.02s，而价值重排每手要算 ~40 次前向（约 20~40ms），
        #        一旦某手被切断，整层作废、连价值重排一起失效（见 SOUL 155）。
        #     ② 更要紧的是**解耦**：如果自对弈跟随配置，那么以后"给对弈台开个开关"
        #        会**悄悄改变数据分布**，历史分片就不再可比 —— 这类"隐式耦合"
        #        在本项目已经吃过一次亏（守护重启让冠军归零，见 SOUL 164）。
        #   ⇒ 要改用价值网络产数据，必须是**显式、单独的一次决定**（并配 tl 上调）。
        bots = {k: SearchBot(depth=1, time_limit=tl, seed=seed * 17 + k,
                             use_value=False)
                for k in (1, 2, 3)}
        rows = []
        for _ in range(maxply):
            if s.get("winner") is not None:
                break
            cur = s["turn"]
            legal = GA.legal_moves(s, cur)
            if not legal:
                GA._advance(s)
                continue
            rows.append((F.extract(s, cur), cur))
            mv = None
            if rng.random() >= eps:
                r = bots[cur].choose(s, legal, "", ARMY_CN[cur])
                mv = (r or {}).get("move")
            if not mv or tuple(str(mv).split("-")) not in legal:
                frm, to = legal[rng.randrange(len(legal))]
                mv = f"{frm}-{to}"
            f, t = str(mv).split("-")
            GA.apply(s, f, t)

        win = s.get("winner")
        plies.append(s["ply"])
        if win is None:
            continue                              # 判和 / 触顶：没有胜负标签，丢弃
        decisive += 1

        # ★ 降采样：每局最多留 cap 个局面（均匀抽，保住开局/中局/残局各段）
        if cap and len(rows) > cap:
            idx = np.linspace(0, len(rows) - 1, cap).astype(int)
            rows = [rows[i] for i in idx]
        for feat, army in rows:
            X.append(feat)
            Y.append(1.0 if army == win else 0.0)

    return (np.asarray(X, dtype=np.float32) if X else np.zeros((0, 32), np.float32),
            np.asarray(Y, dtype=np.float32),
            dict(games=count, decisive=decisive,
                 samples=len(X), secs=time.time() - t0,
                 ply_mean=float(np.mean(plies)) if plies else 0.0))


# --------------------------------------------------------------------------
# 主控侧
# --------------------------------------------------------------------------


def cpu_budget():
    """**真正可用**的 CPU 数 —— 必须读 cgroup 配额，`os.cpu_count()` 靠不住！

    ⚠️ 2026-10-01 实测踩坑（AutoDL GPU 实例）：
        `nproc` / `os.cpu_count()` / `sched_getaffinity()` 全报 **128**，
        但 `/sys/fs/cgroup/cpu.max` = `1500000 100000` ⇒ 配额 = **15 核**。
        按 96 进程跑 ⇒ 每进程只分到 ~13% CPU，2 分钟 0 产出（看着像"卡死"，其实是超配）。
        ⇒ 进程数**必须**按配额给，不能按 nproc。

    返回配额核数（读不到就退回 os.cpu_count()）。
    """
    try:                                    # cgroup v2
        with open("/sys/fs/cgroup/cpu.max", encoding="utf-8") as f:
            q, p = f.read().split()
        if q != "max":
            return max(1, int(int(q) / int(p)))
    except Exception:                       # noqa: BLE001
        pass
    try:                                    # cgroup v1
        with open("/sys/fs/cgroup/cpu/cpu.cfs_quota_us", encoding="utf-8") as f:
            q = int(f.read().strip())
        with open("/sys/fs/cgroup/cpu/cpu.cfs_period_us", encoding="utf-8") as f:
            p = int(f.read().strip())
        if q > 0:
            return max(1, int(q / p))
    except Exception:                       # noqa: BLE001
        pass
    return os.cpu_count() or 4


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", type=int, default=100_000, help="总对局数")
    ap.add_argument("--workers", type=int, default=0, help="进程数（0=自动=核数）")
    ap.add_argument("--chunk", type=int, default=0, help="每片局数（0=自动）")
    ap.add_argument("--tl", type=float, default=0.02, help="每步搜索时间上限（秒）")
    ap.add_argument("--maxply", type=int, default=250, help="单局最大手数")
    ap.add_argument("--eps", type=float, default=0.12, help="ε 随机走子概率（保证多样）")
    ap.add_argument("--cap", type=int, default=40, help="每局最多保留的局面数（0=全留）")
    ap.add_argument("--seed0", type=int, default=1_000_000, help="随机种子起点")
    ap.add_argument("--out", default="data/selfplay.npz", help="输出 npz 路径")
    ap.add_argument("--resume", action="store_true", help="跳过已完成的分片")
    a = ap.parse_args()

    budget = cpu_budget()
    workers = a.workers or budget
    # 每片局数：让总片数 ≈ 核数 × 4（既是负载均衡粒度，也是断点续跑粒度）
    chunk = a.chunk or max(20, int(np.ceil(a.games / (workers * 4))))
    nchunks = int(np.ceil(a.games / chunk))

    out = a.out if os.path.isabs(a.out) else os.path.join(ROOT, a.out)
    parts = out[:-4] + ".parts" if out.endswith(".npz") else out + ".parts"
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    os.makedirs(parts, exist_ok=True)

    print("=" * 78)
    print(f"自对弈产数据：{a.games:,} 局   {workers} 进程   {nchunks} 片（每片 {chunk} 局）")
    if a.workers and a.workers > budget:
        print(f"  ⚠ 你显式给了 {a.workers} 进程，但 cgroup 配额只有 {budget} 核"
              f" ⇒ **超配**，每进程只有 {100.0 * budget / a.workers:.0f}% CPU，会极慢！")
    print(f"  tl={a.tl}s  maxply={a.maxply}  eps={a.eps}  每局留 {a.cap or '全部'} 局面")
    print(f"  输出 {out}")
    print(f"  启动方式 {mp.get_start_method()}   "
          f"({'fork ⇒ 子进程白嫖父进程 JIT' if mp.get_start_method() == 'fork' else 'spawn ⇒ 各自重编译，较慢'})")
    print("=" * 78, flush=True)

    # ★ 父进程预热：fork 之后子进程直接继承编译产物
    t_warm = time.time()
    _warm()
    print(f"父进程 JIT 预热完成，用时 {time.time() - t_warm:.1f}s", flush=True)

    todo = []
    for i in range(nchunks):
        st = i * chunk
        cnt = min(chunk, a.games - st)
        if cnt <= 0:
            break
        pf = os.path.join(parts, f"part{i:05d}.npz")
        if a.resume and os.path.exists(pf):
            continue
        todo.append((i, st, cnt, pf))

    if not todo:
        print("所有分片都已完成，直接汇总。", flush=True)
    else:
        print(f"待跑 {len(todo)} 片…", flush=True)

    t_all = time.time()
    done_games = 0
    if todo:
        ctx = mp.get_context("fork") if "fork" in mp.get_all_start_methods() else mp.get_context()
        pool = ctx.Pool(processes=workers, initializer=_warm)
        tasks = [(st, cnt, a.tl, a.maxply, a.eps, a.cap, a.seed0) for (_i, st, cnt, _pf) in todo]
        for (i, st, cnt, pf), res in zip(todo, pool.imap(_gen_chunk, tasks)):
            X, Y, stt = res
            np.savez_compressed(pf, X=X, Y=Y)
            done_games += stt["games"]
            print(f"  片 {i:>5} 完成：{stt['games']} 局 / {stt['samples']:,} 样本"
                  f"  胜负有解 {stt['decisive']}  平均 {stt['ply_mean']:.0f} 手"
                  f"  用时 {stt['secs']:.1f}s", flush=True)
        pool.close()
        pool.join()
    wall = time.time() - t_all

    # ---- 汇总所有分片 ----
    Xs, Ys = [], []
    for fn in sorted(os.listdir(parts)):
        if not fn.endswith(".npz"):
            continue
        d = np.load(os.path.join(parts, fn))
        if len(d["Y"]):
            Xs.append(d["X"])
            Ys.append(d["Y"])
    if not Xs:
        print("⚠ 没有任何有效样本（全部判和？）")
        return
    X = np.concatenate(Xs)
    Y = np.concatenate(Ys)
    np.savez_compressed(out, X=X, Y=Y)
    stat = dict(games=a.games, samples=int(len(Y)), pos_rate=float(Y.mean()),
                workers=workers, tl=a.tl, maxply=a.maxply, cap=a.cap,
                wall_secs=wall, throughput_gps=(a.games / wall if wall else 0.0))
    with open(out[:-4] + ".json", "w", encoding="utf-8") as f:
        json.dump(stat, f, ensure_ascii=False, indent=2)

    print("=" * 78)
    print(f"完成：{len(Y):,} 样本 × {X.shape[1]} 维   正例率 {Y.mean():.4f}")
    print(f"  墙钟 {wall:.1f}s（{wall / 60:.1f} 分钟）  吞吐 {stat['throughput_gps']:.1f} 局/秒")
    print(f"  → {out}   ({os.path.getsize(out) / 1e6:.1f} MB)")
    print(f"  → {out[:-4] + '.json'}")
    print("=" * 78)


if __name__ == "__main__":
    main()
