#!/bin/bash
# 等第一批诊断（run_ab_diag.sh）写出 ALL DONE，再跑第二批（正交拆解）。
#
# 【为什么用日志标志而不是 pgrep】
#   `pgrep -f run_ab_diag` 会匹配到**这条命令自己**（cmdline 里有那个字符串），
#   于是"等待"变成"匹配成功立刻往下跑"。标志文件/日志行没有这个问题。
cd /root/autodl-tmp/sanchi || exit 1
n=0
while ! grep -q "ALL DONE" /root/autodl-tmp/ab_diag.log 2>/dev/null; do
    n=$((n + 1))
    if [ "$n" -gt 240 ]; then            # 最多等 60 分钟
        echo "等待超时，直接开跑"
        break
    fi
    sleep 15
done
echo "[$(date '+%F %T')] 第一批诊断已完，启动第二批（正交拆解）"
bash tools/run_ab_diag2.sh
echo "[$(date '+%F %T')] 两批诊断全部完毕"
