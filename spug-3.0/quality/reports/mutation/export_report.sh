#!/bin/bash
# 导出变异测试完整报告：results 清单 + 幸存者逐个 diff + HTML 报告
set -e
cd /mnt/e/TDYW/spug-3.0
OUT=quality/reports/mutation/contract_agreement_20260921
mkdir -p "$OUT"
M=~/.local/bin/mutmut
$M results > "$OUT/results.txt" 2>&1 || true
$M result-ids survived | tr ' ' '\n' | sed '/^$/d' > "$OUT/survivor_ids.txt"
: > "$OUT/survivors_full.txt"
n=0
while read -r id; do
  [ -z "$id" ] && continue
  n=$((n+1))
  echo "===== MUTANT $id =====" >> "$OUT/survivors_full.txt"
  $M show "$id" >> "$OUT/survivors_full.txt" 2>&1 || echo "SHOW_FAILED" >> "$OUT/survivors_full.txt"
done < "$OUT/survivor_ids.txt"
echo "survivors exported: $n"
$M html > "$OUT/html_error.txt" 2>&1 || echo "html command failed"
if [ -f mutmut.html ]; then mv mutmut.html "$OUT/mutmut.html"; echo "html moved"; fi
ls -la "$OUT"
