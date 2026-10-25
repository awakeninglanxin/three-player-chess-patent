#!/bin/bash
# 自对弈 / 自动驾驶 的启停开关（2026-10-02）
#
# 【为什么单独成脚本，而不是内联 ssh 命令】
#   内联命令串里写字面量（例如 `case "$c" in *cloud_autopilot*)`）会被
#   **执行它的那个 shell 自己匹配到** —— 因为那个 shell 的 cmdline 就是这整条
#   命令串，里面含 `cloud_autopilot`。结果是"杀旧进程"变成"杀自己"，
#   命令中途断掉（SOUL 铁律 154 的第四变种，本项目已踩两次，第二次把
#   autopilot 误杀、守护没人看管）。
#   放进脚本文件后，进程的 cmdline 只有 `bash tools/ctl_sp.sh pause`，
#   字面量不在其中 ⇒ **结构上不可能自匹配**。
#
# 用法：
#   bash tools/ctl_sp.sh pause     # 停 autopilot + 自对弈（给 A/B 让出 CPU）
#   bash tools/ctl_sp.sh resume    # 重新拉起 autopilot（它会带回自对弈）
#   bash tools/ctl_sp.sh status    # 只看不动
cd /root/autodl-tmp/sanchi || exit 1
PY=/root/miniconda3/bin/python
SP_PAT="cloud_selfplay"
AP_PAT="cloud_autopilot"

pids_of() {
    local pat="$1" x c
    for x in /proc/[0-9]*; do
        c=$({ tr '\0' ' ' < "$x/cmdline"; } 2>/dev/null) || continue
        case "$c" in *"$pat"*) echo "${x#/proc/}";; esac
    done
}

show() {
    local label="$1" pat="$2" n
    n=$(pids_of "$pat" | wc -l)
    echo "  $label：$n 个（$(pids_of "$pat" | tr '\n' ' '）)"
}

case "$1" in
pause)
    echo "=== 停 autopilot（否则它 30s 内会把自对弈拉回来）==="
    p=$(pids_of "$AP_PAT"); [ -n "$p" ] && kill $p 2>/dev/null; echo "  已停：$p"
    sleep 3
    echo "=== 停自对弈 ==="
    p=$(pids_of "$SP_PAT"); [ -n "$p" ] && kill $p 2>/dev/null; echo "  已停：$p"
    sleep 5
    echo "=== 现状 ==="
    show "autopilot" "$AP_PAT"
    show "selfplay" "$SP_PAT"
    show "gpu_daemon" "gpu_daemon.py"
    echo "=== CPU 配额使用（3s 采样）==="
    a=$(awk '/^usage_usec/{print $2}' /sys/fs/cgroup/cpu.stat); sleep 3
    b=$(awk '/^usage_usec/{print $2}' /sys/fs/cgroup/cpu.stat)
    echo "  约 $(awk -v a="$a" -v b="$b" 'BEGIN{printf "%.2f", (b-a)/3000000}') 核 / 配额 15 核"
    ;;
resume)
    echo "=== 拉起 autopilot（它会带回自对弈；守护若活着不会被重复拉起）==="
    setsid nohup bash tools/cloud_autopilot.sh >> /root/autodl-tmp/autopilot.out 2>&1 < /dev/null &
    sleep 8
    show "autopilot" "$AP_PAT"
    show "selfplay" "$SP_PAT"
    show "gpu_daemon" "gpu_daemon.py"
    tail -3 /root/autodl-tmp/autopilot.log
    ;;
*)
    show "autopilot" "$AP_PAT"
    show "selfplay" "$SP_PAT"
    show "gpu_daemon" "gpu_daemon.py"
    show "ab_match" "ab_match"
    nvidia-smi --query-gpu=utilization.gpu,memory.used --format=csv,noheader
    ;;
esac
