#!/usr/bin/env bash
# 云端自动驾驶 —— 把当前算力顶到极限，直到截止时间（老师 2026-10-01）
#
#   nohup bash tools/cloud_autopilot.sh > /root/autodl-tmp/autopilot.out 2>&1 &
#
# 【它管两件事，都不需要人看】
#   ① **自对弈不断粮**：`cloud_selfplay.py` 跑完目标局数会退出。
#      这里检测到它退出就**接着跑**（同一条 `--out` + `--resume`，
#      分片文件已被跳过的会跳过，等于"续跑到 GOAL 局"）。
#   ② **GPU 守护别死**：`gpu_daemon.py` 若因任何原因退出就拉起来。
#      守护死了 = GPU 闲着 = 违反老师 2026-10-01 的硬要求（平均利用率 ≥70%）。
#
# 【第二轮时间线】（2026-10-02 09:5x 老师重新开机后重启本脚本）
#   自对弈截止 10-03 04:00 / GPU 守护截止 10-03 04:20
#   ⚠️ 老师若提前关机：本机每小时自动拉一次增量（见 WorkBuddy 的"增量拉取"自动化），
#      任何时刻断都只损失 ≤1 小时的增量。
#   ⚠️ 改时间**只需** sed 本文件的 SELFPLAY_STOP / DAEMON_STOP 两行，不必重启进程
#      （脚本启动时只读一次；改完要 kill 再重启才生效）。
#
# 【为什么不直接写死一个巨大的 --games】
#   一次要 40 万局的话，中途被打断就白等；用 resume 续跑，
#   分片粒度 300 局 ⇒ 任何时刻打断都只损失最多 300 局。
set -u

PY=/root/miniconda3/bin/python
DIR=/root/autodl-tmp/sanchi
DATA=/root/autodl-tmp/data
# ★★ 2026-10-02 第二轮：**开新的分片目录**，与第一轮（坏标签）数据物理隔离。
#   理由：第一轮的标签是「噪声加在 alpha-beta 上界上」那条退化路径产出的
#   （详见 SOUL.md 铁律 151/152），AUC 在 0.657 平台 7 倍数据毫无增益。
#   搜索修好后重新产的数据如果和旧数据混在一起，**看不出改善**；
#   物理隔离才能做干净的 A/B（旧 `selfplay_150k.parts` 保留不动）。
PARTS=$DATA/sp2.parts
OUT=$DATA/sp2.npz
SPLOG=$DATA/selfplay_sp2.log
# ★★ 2026-10-02 第二轮修：守护必须**同时**读两个目录。
#   只给 sp2（当时 2.7 万样本）会"饿着肚子空转"：mlp_512_256 的 batch=16384
#   ⇒ 一个 epoch 只 2 步矩阵乘 ⇒ GPU 采样均值 **4.6%**（老师："GPU 基本上空置"）。
#   旧目录 1130 片 / **1011 万样本**是盘上现成的燃料，合并喂进去才能把 batch 填满。
#   ⚠️ 两目录分片**同名** ⇒ gpu_daemon 的 seen 键已改为 (目录, 文件名)。
PARTS_ALL="$DATA/sp2.parts $DATA/selfplay_150k.parts"
DLOG=/root/autodl-tmp/gpu_daemon.log
ALOG=/root/autodl-tmp/autopilot.log
# ★ 守护的**退出人证**：任何退出（正常/异常/被杀）都留一行 EXIT=<码> + 时间。
#   2026-10-02 我在这上面吃过亏：守护日志里只是"某一行之后就没有了"，
#   我无法判断它是崩了、被 OOM 杀了、还是被我自己换代码时 kill 的，
#   只能逐一排查过程序、内存、文件演进史，白花很久。
#   ⚠️ 注意：`nohup bash -c "...; echo EXIT=$?"` 里的 `$?` 必须由**内层** shell 求值，
#     所以外层的 `$` 要转义（写成 \$?）；而 `>> $DEXIT` 要由外层展开成真实路径。
DEXIT=/root/autodl-tmp/gpu_daemon.exit
# ⚠️ 守护的状态文件写在 **包内** 的 server/agents/values/（= gpu_daemon.OUTDIR），
#    不是 /root/autodl-tmp/ 根下。2026-10-01 22:00 心跳一直取到 n/a 就是这个原因。
STATUS=$DIR/server/agents/values/gpu_daemon_status.json
# ★★ 2026-10-02 修（活锁）：门禁锁 —— 守护跑 `arena_gate` 标尺时写、跑完删。
#   标尺是**纯 CPU 对局**（300 局 × 三台搜索 Bot），全程 GPU 占用 0%。
#   自保判据「连续 6 分钟 <5% ⇒ 重启」原本不知道这件事 ⇒ 每轮门禁都被腰斩：
#     16:45:43 写候选 → 开门禁 → 16:47/16:49/16:51 三次心跳 0%
#     → 16:51:35 kill（EXIT=143）→ 16:51:40 重拉 → 又从"[轮 1]"开始
#   ⇒ `round` 永远停在 1，候选永远上不了位。
#   ⚠️ 根因是**估算错**：我在旁边注释里写"门禁一次约 3 分钟"，实测 >6 分钟。
#   锁路径必须与 `gpu_daemon.GATE_LOCK`（= OUTDIR/gate.lock）**逐字一致**。
GATE_LOCK=$DIR/server/agents/values/gate.lock
GATE_LOCK_MAX=2400   # 锁的存活上限（秒）。超过 ⇒ 认定守护崩了留下的死锁，删掉。
#   取 2400（40 分钟）的理由：门禁实测 6~8 分钟，留 5 倍余量足够；
#   而若守护真崩了，autopilot 最多 40 分钟后恢复判零能力，不会永久失明。

GOAL=400000          # 自对弈总目标局数（会被截止时间截断）
WORKERS=8            # ★★ 2026-10-02 15:1x **从 14 降到 8**：为了把 GPU 占空比拉回来。
#   【病因】守护的**训练循环是 Python 主导的**（小 MLP 单步 matmul 只有几十微秒，
#   被 `zero_grad/forward/backward/step` 的开销淹没，见 SOUL 159 的占空比铁律）
#   ⇒ 它必须**被及时调度**才能持续喂 GPU。14 个 CPU 满载的自对弈 worker 一挤，
#     训练循环就被饿住 ⇒ **nvidia-smi 真的看到 GPU 闲着**（不是采样口径问题）。
#   【★ 实测（同一台机、同一守护，只改 worker 数）】
#     worker   数据吞吐（心跳算）                   GPU 占空比（60s 独立采样）
#       14     780→794 片 / 123s = **5.69 局/秒**   **25.2%**（峰 76%，215W/350W）
#        8     818→831 片 / 122s = **5.33 局/秒**   **96.2%**（峰 100%，**344W/350W**）
#     ⇒ **数据吞吐只掉 6%（心跳粒度内等同），GPU 从 25% 拉到 96%、功耗顶满。**
#   【为什么这是"白捡的"】自对弈并行效率极差：14 进程下每 worker **4.6 秒/局**，
#   单进程只要 **0.98 秒** ⇒ **14 个核只换到 3 倍吞吐**（效率 ~21%）。
#   那 6 个"多出来"的核本来就在互相抢内存带宽 ⇒ **让给训练循环是纯赚**。
#   ⚠️ 一整轮平均会低于 96%（`mlp_512_256` 的 batch 比 `mlp_1024_512` 小一半）：
#      守护自报的滑动窗口均值 **23.9（p50 16）→ 57.2（p50 57）**，还在往上走。
#   ⚠️ 若以后把 TL 或 depth 调大（单局变贵），要重新找这个平衡点。
CHUNK=50             # 每片局数。⚠️ 2026-10-02 实测：14 进程争抢下每 worker 要
                     # **4.6 秒/局**（单进程只要 0.98 秒 —— 争抢把单进程拖了 4.7 倍），
                     # 用 300 的话**一片要 23 分钟**，GPU 守护就干等没料训。
                     # 50 ⇒ 约 2 分钟一片，守护能持续拿到新数据（"流水线不停火"）。
TL=0.05              # ★★ 2026-10-02 修正：从 0.02 提到 0.05（**推翻当天早些时候的判断**）。
                     # 当时我写"0.05 反而更慢 ⇒ 别动这个值"，那是只看吞吐、没看**质量**。
                     # 探针 `tests/_probe_jit_timeout.py`（depth=1、240 次搜索）实测：
                     #     tl=0.02 → 第一层(plies=3)作废 **26/240 = 10.8%**，且全部走 `legal[0]`
                     #     tl=0.05 → 仅 1/240 = 0.4%
                     #     tl=0.20 → 0/240
                     # 机制：`_choose_jit` 初值 `best_move = root[0] = legal[0]`，
                     # 而循环里 `if aborted or mv is None: break` ⇒ **第一层一超时就原样吐 legal[0]**
                     # （一枚与局面无关的定死着法）；放大器是内核每 4096 节点才查一次时钟，
                     # 而 3 plies 开局只有 ~4543 节点 ⇒ 整层只有 1 次检查机会。
                     # 10.8% 的手退化成"定死着法" ⇒ 对局结果与局面特征脱钩 ⇒ **自对弈标签质量受损**。
                     # 代价：单局变慢（更多手跑满预算）—— 但**数据可信 > 产出速度**。
SELFPLAY_STOP="2026-10-03 04:00:00"
DAEMON_STOP="2026-10-03 04:20:00"
HEARTBEAT=120        # 心跳间隔（秒）

cd "$DIR" || exit 1
log() { echo "[autopilot $(date '+%H:%M:%S')] $*" >> "$ALOG"; }

# ★★ 进程存在性判定：**必须看 /proc/<pid>/cmdline 的开头是不是那个 python**。
#   不能只写 `pgrep -f gpu_daemon` —— 2026-10-01 实测踩坑：
#   我用 ssh 启自动驾驶时，那条命令串里为了打印进程列表写了 `awk '/gpu_daemon./'`，
#   于是那个 `bash -c "…"` 进程的 **cmdline 里也含 "gpu_daemon"**，
#   `pgrep -f` 就把它当成"守护在跑" ⇒ **永不拉起守护 ⇒ GPU 一直闲着**。
#   （同一个坑在本项目已出现第二次：`pkill -f gpu_daemon.py` 把执行它的 shell 自己杀了。）
# ★★ 2026-10-02 第三次修：关键字从 `gpu_daemon` 收紧到 **`gpu_daemon.py`**。
#   起因：现在还会再开一个「均衡配比」守护做 A/B，它是用**符号链接**
#   `tools/_bal_runner.py → gpu_daemon.py` 起的 ——
#   · 符号链接 ⇒ 永远指向最新代码（不用维护副本，改一处就够了）；
#   · argv 里是 `_bal_runner.py` ⇒ **不含子串 `gpu_daemon.py`** ⇒ 本检查只认正式那个。
#   若还用宽关键字 `gpu_daemon`，那么"正式守护死了但实验守护还活着"时，
#   本脚本会误判"守护在跑"⇒ 正式守护永不重启（正是上面那个老坑的新变种）。
pids_of() {   # $1 = 脚本名关键字；回显所有"cmdline 以 $PY 开头且含 $1"的 pid
    local p c
    for p in /proc/[0-9]*; do
        # ⚠️ `< "$p/cmdline"` 失败时是 **shell** 报错，`2>/dev/null` 挂在 tr 上没用；
        #    必须把整个重定向+命令包起来才能吞掉（否则日志里刷 `No such file or directory`）。
        c=$({ tr '\0' ' ' < "$p/cmdline"; } 2>/dev/null) || continue
        case "$c" in
            "$PY"*"$1"*) echo "${p#/proc/}" ;;
        esac
    done
}
running() {   # $1 = 脚本名关键字
    [ -n "$(pids_of "$1")" ]
}
kill_script() {   # $1 = 脚本名关键字；只杀精确匹配的那些 pid，不误伤 shell
    local pid
    for pid in $(pids_of "$1"); do
        kill "$pid" 2>/dev/null || true
    done
}

log "================ 启动 ================"
log "自对弈截止 $SELFPLAY_STOP / GPU 守护截止 $DAEMON_STOP / 目标 $GOAL 局"
log "进程探测口径：/proc/<pid>/cmdline 以 $PY 开头（不用 pgrep -f）"

sp_stop=$(date -d "$SELFPLAY_STOP" +%s)
dm_stop=$(date -d "$DAEMON_STOP" +%s)
last_hb=0
restarts_sp=0
restarts_dm=0
zero_gpu=0            # 连续"守护活着但 GPU <5%"的 30s 计数

while true; do
    now=$(date +%s)

    # ---------------- ① 自对弈 ----------------
    if [ "$now" -lt "$sp_stop" ]; then
        if ! running cloud_selfplay; then
            n=$(ls "$PARTS" 2>/dev/null | wc -l)
            restarts_sp=$((restarts_sp + 1))
            log "自对弈未在跑（已完成分片 $n），续跑到 $GOAL 局（第 $restarts_sp 次拉起）"
            NUMBA_NUM_THREADS=1 nohup "$PY" -u tools/cloud_selfplay.py \
                --games "$GOAL" --chunk "$CHUNK" --workers "$WORKERS" \
                --tl "$TL" --resume --out "$OUT" >> "$SPLOG" 2>&1 &
            sleep 90                      # 防"秒退→秒起"打转
            continue
        fi
    fi

    # ---------------- ② GPU 守护 ----------------
    if [ "$now" -lt "$dm_stop" ]; then
        if ! running gpu_daemon.py; then
            restarts_dm=$((restarts_dm + 1))
            log "GPU 守护未在跑，拉起（第 $restarts_dm 次）"
            # ★ 外面包一层 bash -c：守护一退出就把退出码追加到 $DEXIT（人证）。
            #   顺带把"这次是谁拉起的、第几次"也记进去，便于对齐 autopilot 日志。
            #   ⚠️ `--threads 2;` 那个分号**必须留着**：双引号里的 `\`+换行会塌成
            #      空格，没有分号的话 `--threads 2` 和 `echo` 会连成一条命令，
            #      argparse 收到多余的 `echo EXIT=...` ⇒ 守护启动即退（exit 2）。
            # ★ 2026-10-02 第四次修：加 `--gate-games 300 --gate-workers 4`。
            #   守护的"选最优"原来只看验证 AUC，而当天实测证明 **AUC 不能选冠军**
            #   （同一份权重在两个 A/B 场次里差 20 个点；分源 AUC 提升反而实战更差）。
            #   门禁把"上位"改成必须**在固定标尺上超过现冠军**：
            #     · 标尺 = `{两台完全相同的纯搜索, 被测权重}`，seed 固定 2200000
            #     · 为什么不用 `{none, 冠军, 候选}`：两台价值网络同场时三方全平
            #       （判和率 31%→54%）⇒ 那个场次**没有分辨力**，门禁会永远不放行
            #   代价：触发条件见下，一次 6~8 分钟、6 个进程。
            #   ★★ 2026-10-02 第五次修（活锁）：`--gate-workers 4 → 6`，并且
            #      **必须有 gate.lock 配合**（守门人会把这 6 分钟当成"守护卡死"）。
            #      4 → 6 的依据：15 核里自对弈占 8、守护训练占 2 ⇒ 还剩 5，
            #      给门禁 6 个进程是允许轻度超配的（它是**短时**任务，且这段时间
            #      GPU 本来闲着 ⇒ 门禁越快跑完，GPU 空闲窗口越短，纯赚）。
            nohup bash -c "'$PY' -u tools/gpu_daemon.py \
                --parts $PARTS_ALL --idle 5 --threads 2 \
                --gate-games 300 --gate-workers 6; \
                echo \"EXIT=\$?  拉起第 $restarts_dm 次  结束于 \$(date '+%F %T')\" >> '$DEXIT'" \
                >> "$DLOG" 2>&1 &
            sleep 60
            continue
        fi
        # ★ 进程活着 ≠ 在出力：守护可能卡在某个角落（历史事故：
        #   demo_hanging 返回嵌套 dict → TypeError → 进程直接退；但更阴的是
        #   "活着却不出力"，用 ps 完全看不出来）。老师 2026-10-01 的硬要求是
        #   **平均利用率 ≥70%**，所以这里按"实际 GPU 读数"再兜一层：
        #   连续 6 分钟（12×30s）低于 5% ⇒ 判定卡死，重启它。
        #   合法的 0% 有**三种**：轮次之间的 --idle 5s、首轮读分片、
        #   以及**门禁标尺**（第三种当年漏了，见下方 gate.lock 豁免）。
        #   前两种远不到 6 分钟，不会误杀。
        # ★★ 2026-10-02 修（活锁）：合法的 0% 原本只列了两种（--idle 5s 间歇、
        #   首轮读分片），**漏了第三种：门禁标尺**。标尺是纯 CPU 对局（300 局 ×
        #   三台搜索 Bot），GPU 全程 0%，实测耗时 **>6 分钟**（我在旁边注释里估
        #   "约 3 分钟"）⇒ 每次都被下面这段判死并腰斩 ⇒ `round` 永远停在 1。
        #   现在以 `gate.lock` 为豁免凭据。
        if [ -f "$GATE_LOCK" ]; then
            # 陈旧锁兜底：守护崩了/被杀，不会留下"永不判零"的死锁。
            if [ -n "$(find "$GATE_LOCK" -mmin +$((GATE_LOCK_MAX / 60)) 2>/dev/null)" ]; then
                log "⚠ 门禁锁已存在超过 $((GATE_LOCK_MAX / 60)) 分钟 ⇒ 判定为死锁，删除"
                rm -f "$GATE_LOCK"
            else
                zero_gpu=0        # 门禁期间 GPU 空转是设计如此，不算卡死
                sleep 5
                continue
            fi
        fi
        g=$(nvidia-smi --query-gpu=utilization.gpu --format=csv,noheader,nounits 2>/dev/null | head -1)
        if [ "${g:-0}" -lt 5 ]; then
            zero_gpu=$((zero_gpu + 1))
        else
            zero_gpu=0
        fi
        if [ "$zero_gpu" -ge 12 ]; then
            log "⚠ GPU 连续 $((zero_gpu * 30))s <5%（守护活着但不出力），重启守护"
            kill_script gpu_daemon.py
            zero_gpu=0
            sleep 5
            continue
        fi
    fi

    # ---------------- 收工 ----------------
    if [ "$now" -ge "$dm_stop" ]; then
        log "到点，收工。自对弈拉起 $restarts_sp 次 / GPU 守护拉起 $restarts_dm 次"
        # 正式守护 + 实验用的均衡配比守护（符号链接 _bal_runner.py）都收掉，
        # 免得实验进程在本脚本退出后继续悄悄吃 GPU。
        kill_script gpu_daemon.py
        kill_script _bal_runner.py
        sleep 3
        n=$(ls "$PARTS" 2>/dev/null | wc -l)
        log "最终分片数 $n（约 $((n * CHUNK)) 局）"
        date > /root/autodl-tmp/AUTOPILOT_DONE
        log "已落 AUTOPILOT_DONE，可以拉回本机了"
        break
    fi

    # ---------------- 心跳 ----------------
    if [ $((now - last_hb)) -ge "$HEARTBEAT" ]; then
        last_hb=$now
        n=$(ls "$PARTS" 2>/dev/null | wc -l)
        gpu=$(nvidia-smi --query-gpu=utilization.gpu --format=csv,noheader,nounits 2>/dev/null | head -1)
        # 守护状态文件里 gpu 段是 GpuSampler.summary()：{"n","mean","p50","max","mean_all"}
        #   ★ 2026-10-02：`mean/p50` 现在是**最近 ~10 分钟的滑动窗口**（不再是全程累积均值，
        #     全程值在 mean_all）。另外把 `cur/done/total`（正在训哪个档位、第几个）
        #     和 `best` 的**权重指纹**也打出来 —— 之前只看一个"均值 17.0"，
        #     既分不清"守护卡住了"还是"这数字本来就陈旧"，也无从核对盘上权重的身世。
        mine=$("$PY" -c "import json;d=json.load(open('$STATUS'));g=d['gpu'];b=d.get('best') or {};print('窗口均值',g['mean'],'p50='+str(g['p50']),'全程',g.get('mean_all'),'n='+str(g['n']),'| 轮',d.get('round'),'训',d.get('cur') or '-','('+str(d.get('done'))+'/'+str(d.get('total'))+')','| best',b.get('name','-'),b.get('auc','-'),'@',b.get('mtime','-'))" 2>/dev/null)
        log "心跳：分片 $n（约 $((n * CHUNK)) 局） GPU 瞬时 ${gpu}% 守护 ${mine:-n/a}"
    fi

    sleep 30
done
