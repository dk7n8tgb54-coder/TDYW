# 截断 views.py 文件，只保留到迁移注释为止
with open('spug_api/apps/document/views.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# 找到需要保留的行
end_line = None
for i, line in enumerate(lines):
    if '所有 Transfer Views 代码已迁移至 views/transfer.py' in line:
        end_line = i + 1  # 保留这一行
        break

if end_line:
    with open('spug_api/apps/document/views.py', 'w', encoding='utf-8') as f:
        f.writelines(lines[:end_line])
    print(f'文件已截断到第 {end_line} 行，剩余 {len(lines) - end_line} 行已删除')
else:
    print('未找到截断标记')
