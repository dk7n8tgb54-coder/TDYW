#!/bin/bash
# 对比两个镜像中的迁移文件 MD5

echo "=== 提取 tdyw:07272 迁移文件 ==="
docker run --rm --entrypoint find tdyw:07272 \
    /data/spug/spug_api/apps -path '*/migrations/*.py' \
    -not -name '__init__.py' -exec md5sum {} \; \
    | sed 's|/data/spug/spug_api/||' | sort -k2 > /tmp/migrations_07272.txt
echo "旧镜像: $(wc -l < /tmp/migrations_07272.txt) 个迁移文件"

echo "=== 提取 tdyw:0802 迁移文件 ==="
docker run --rm --entrypoint find tdyw:0802 \
    /data/spug/spug_api/apps -path '*/migrations/*.py' \
    -not -name '__init__.py' -exec md5sum {} \; \
    | sed 's|/data/spug/spug_api/||' | sort -k2 > /tmp/migrations_0802.txt
echo "新镜像: $(wc -l < /tmp/migrations_0802.txt) 个迁移文件"

echo ""
echo "=== 对比结果 ==="
diff /tmp/migrations_07272.txt /tmp/migrations_0802.txt > /tmp/migration_diff.txt 2>&1
if [ $? -eq 0 ]; then
    echo "完全一致：两个镜像的迁移文件完全相同"
else
    echo "发现差异！"
    echo ""
    echo "--- 只在旧镜像中有的文件 ---"
    grep "^<" /tmp/migration_diff.txt | head -20
    echo ""
    echo "--- 只在新镜像中有的文件 ---"
    grep "^>" /tmp/migration_diff.txt | head -20
    echo ""
    echo "--- 两镜像都有但内容不同的文件（同名但 MD5 不同）---"
    # 提取文件名列，找交集再比 MD5
    cut -d' ' -f3 /tmp/migrations_07272.txt | sort > /tmp/old_names.txt
    cut -d' ' -f3 /tmp/migrations_0802.txt | sort > /tmp/new_names.txt
    comm -12 /tmp/old_names.txt /tmp/new_names.txt | while read -r fname; do
        old_md5=$(grep " $fname$" /tmp/migrations_07272.txt | awk '{print $1}')
        new_md5=$(grep " $fname$" /tmp/migrations_0802.txt | awk '{print $1}')
        if [ "$old_md5" != "$new_md5" ]; then
            echo "  [改过] $fname"
            echo "         旧 MD5: $old_md5"
            echo "         新 MD5: $new_md5"
        fi
    done
fi
