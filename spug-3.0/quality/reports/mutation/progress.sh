#!/bin/bash
# 变异测试进度速览：读 .mutmut-cache 汇总各状态计数
python3 - <<'EOF'
import sqlite3, datetime, os
CACHE = '/mnt/e/TDYW/spug-3.0/.mutmut-cache'
TOTAL = 783
con = sqlite3.connect(CACHE)
cur = con.cursor()
counts = dict(cur.execute('SELECT status, COUNT(*) FROM mutant GROUP BY status'))
killed = counts.get('ok_killed', 0)
survived = counts.get('bad_survived', 0)
timeout = counts.get('bad_timeout', 0)
suspicious = counts.get('bad_suspicious', 0)
skipped = counts.get('skipped', 0)
tested = killed + survived + timeout + suspicious + skipped
pct = 100.0 * tested / TOTAL
print('进度: %d/%d (%.0f%%)' % (tested, TOTAL, pct))
print('杀伤 %d  幸存 %d  超时 %d  可疑 %d  跳过 %d' % (killed, survived, timeout, suspicious, skipped))
if killed + survived:
    print('当前杀伤率: %.0f%% (killed/(killed+survived), 仅已判定部分, 全程结束才有最终意义)' % (100.0 * killed / (killed + survived)))
print('缓存最后更新: %s' % datetime.datetime.fromtimestamp(os.path.getmtime(CACHE)).strftime('%H:%M:%S'))
EOF
