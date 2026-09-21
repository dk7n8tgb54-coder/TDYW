#!/bin/bash
# 修复版：只改 file.path 列（上一版盲目 replace 所有列毁掉了二进制 numbits 位图）
set -e
cp /mnt/e/TDYW/spug-3.0/spug_api/.coverage /mnt/e/TDYW/spug-3.0/.coverage
python3 - <<'EOF'
import sqlite3
con = sqlite3.connect('/mnt/e/TDYW/spug-3.0/.coverage')
cur = con.cursor()
cur.execute("UPDATE file SET path = replace(path, '/data/spug/spug_api', '/mnt/e/TDYW/spug-3.0/spug_api')")
con.commit()
con.close()

from coverage import CoverageData
d = CoverageData(basename='/mnt/e/TDYW/spug-3.0/.coverage')
d.read()
fs = d.measured_files()
print(len(fs), 'measured files')
for f in fs:
    if 'apps/contract_agreement' in f and '/tests/' not in f:
        print('  target:', f, 'lines:', len(d.lines(f) or []))
        d.contexts_by_lineno(f)  # mutmut 读取时调用的同一 API，验证二进制列完好
print('READ_OK')
EOF
echo PREPARE2_DONE
