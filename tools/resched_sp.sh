#!/bin/bash
# 重排资源：把自对弈的进程数降下来，给 A/B 对局让核（2026-10-02）。
#
# 【为什么需要这个脚本，而不是一行 ssh 命令】
#   `pgrep -f` / `case "$c" in *foo*)` 在**内联 ssh 命令**里必然自匹配 ——
#   模式串本身就在执行者的 cmdline 里，于是脚本会把自己杀掉（实测踩过两次，
#   见 SOUL 铁律 154）。放进脚本文件里，脚本的 cmdline 只有 `bash tools/xxx.sh`，
#   不含模式串 ⇒ 安全。
#
# 用法：bash tools/resched_sp.sh 6
set -u
N=${1:-6}
cd /root/autodl-tmp/sanchi || exit 1

# 1) 停 autopilot（锚定匹配，别用"包含"）
for x in /proc/[0-9]*; do
    c=$({ tr "\0" " " < "$x/cmdline"; } 2>/dev/null) || continue
    case "$c" in "bash tools/cloud_autopilot.sh "*) echo "停 autopilot ${x#/proc/}"; kill ${x#/proc/} 2>/dev/null ;;
    esac
done
# 2) 停自对弈（主控 + 全部 worker；它退出后 autopilot 会用新 N 拉起）
for x in /proc/[0-9]*; do
    c=$({ tr "\0" " " < "$x/cmdline"; } 2>/dev/null) || continue
    case "$c" in */miniconda3/bin/python*cloud_selfplay*) echo "停 selfplay ${x#/proc/}"; kill ${x#/proc/} 2>/dev/null ;;
    esac
done
sleep 5

# 3) 改 WORKERS
sed -i "s/^WORKERS=[0-9]*/WORKERS=$N/" tools/cloud_autopilot.sh
echo "现在的 WORKERS 行：$(grep '^WORKERS=' tools/cloud_autopilot.sh)"

# 4) 重启 autopilot（它会拉起自对弈；守护若已在跑则不动）
setsid nohup bash tools/cloud_autopilot.sh >> /root/autodl-tmp/autopilot.out 2>&1 < /dev/null &
sleep 3
echo "已重启 autopilot；自对弈将以 $N 进程拉起"
