#!/bin/bash
# 等第二批诊断（run_ab_diag2.sh）跑完，接着做 λ 扫描。
cd /root/autodl-tmp/sanchi || exit 1
n=0
while ! grep -q "ALL DONE" /root/autodl-tmp/ab_diag2.log 2>/dev/null; do
    n=$((n + 1))
    if [ "$n" -gt 240 ]; then
        echo "等待超时，直接开跑"
        break
    fi
    sleep 15
done
echo "[$(date '+%F %T')] 第二批已完，开始 λ 扫描"
bash tools/run_ab_lam.sh
