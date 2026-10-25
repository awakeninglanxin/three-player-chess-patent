#!/bin/bash
# 等"一台 vs 两台纯搜索"跑完，接着补"第三方 vs seed 批次"那一格。
cd /root/autodl-tmp/sanchi || exit 1
n=0
while ! grep -q "VS2NONE DONE" /root/autodl-tmp/ab_vs2none.log 2>/dev/null; do
    n=$((n + 1))
    if [ "$n" -gt 240 ]; then
        echo "等待超时，直接开跑"
        break
    fi
    sleep 15
done
echo "[$(date '+%F %T')] vs2none 已完，开始 seed 批次实验"
bash tools/run_ab_seedbatch.sh
