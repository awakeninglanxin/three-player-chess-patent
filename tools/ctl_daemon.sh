#!/usr/bin/env bash
# GPU 守护进程控制（只看状态 / 停）
#
# ⚠️ 为什么不用 `pgrep -f gpu_daemon`：本项目已踩过**五次**"自匹配"（SOUL 154），
#   最狠的一次是 `case ... in *gpu_daemon*)` 把**执行它的那个 shell 自己**杀了。
#   最保险的口径有两条：
#     ① 把匹配字面量放进**脚本文件**（这样调用者的 cmdline 里没有那个模式）；
#     ② 用**完整解释器路径 + 脚本相对路径**当模式，而不是宽关键字。
#   于是 `bash tools/ctl_daemon.sh stop` 这个进程的 cmdline 里
#   只有 "bash tools/ctl_daemon.sh stop"，绝不可能是被匹配的对象。
#
# 用法：
#   bash tools/ctl_daemon.sh status    # 打印 PID
#   bash tools/ctl_daemon.sh stop      # 停（autopilot 会在 ~90s 内用**新代码**拉起来）
#   bash tools/ctl_daemon.sh await     # 等它被 autopilot 拉起来（最多 150s）
set -u
PAT='miniconda3/bin/python -u tools/gpu_daemon.py'

pids() {
  ps -eo pid,cmd | grep -F -- "$PAT" | grep -v grep | awk '{print $1}' | tr '\n' ' '
}

case "${1:-status}" in
  status)
    p=$(pids)
    if [ -n "$(echo "$p" | tr -d ' ')" ]; then echo "守护在跑：$p"; else echo "守护没在跑"; fi
    ;;
  stop)
    p=$(pids)
    if [ -n "$(echo "$p" | tr -d ' ')" ]; then
      echo "STOP $p"
      # shellcheck disable=SC2086
      kill $p 2>/dev/null
      sleep 3
      r=$(pids)
      if [ -n "$(echo "$r" | tr -d ' ')" ]; then echo "仍在：$r（再 KILL 一次）"; kill -9 $r 2>/dev/null; fi
      echo "已停"
    else
      echo "（本来就没跑）"
    fi
    ;;
  await)
    for i in $(seq 1 30); do
      p=$(pids)
      if [ -n "$(echo "$p" | tr -d ' ')" ]; then echo "起来了：$p（等了 ${i}0s 量级）"; exit 0; fi
      sleep 5
    done
    echo "⚠ 150s 内没起来 —— autopilot 还活着吗？（bash tools/ctl_sp.sh status）"
    exit 1
    ;;
  *)
    echo "用法: $0 {status|stop|await}"
    exit 2
    ;;
esac
