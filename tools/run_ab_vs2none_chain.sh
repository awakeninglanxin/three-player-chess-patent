#!/bin/bash
# 等 λ 扫描跑完，接着做"一台 vs 两台纯搜索"的决定性实验。
cd /root/autodl-tmp/sanchi || exit 1
n=0
while ! grep -q "LAM DONE" /root/autodl-tmp/ab_lam.log 2>/dev/null; do
    n=$((n + 1))
    if [ "$n" -gt 240 ]; then
        echo "等待超时，直接开跑"
        break
    fi
    sleep 15
done
echo "[$(date '+%F %T')] λ 扫描完毕，开始决定性实验"
bash tools/run_ab_vs2none.sh
