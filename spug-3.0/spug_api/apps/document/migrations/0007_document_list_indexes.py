# P0-3: 为文档模块 4 个列表模型补"过滤 + 排序"组合索引。
#
# 真实查询路径（来自 views/folder/views.py）：
#   私有文件夹：filter(tenant_id=?, parent_id=?, is_deleted=False).order_by('-created_at')
#   私有文件：  filter(tenant_id=?, folder_id=?, is_deleted=False).order_by('-created_at')
#   公共文件夹：filter(parent_id=?, is_deleted=False).order_by('-created_at')
#   公共文件：  filter(folder_id=?, is_deleted=False).order_by('-created_at')
#
# 索引字段顺序设计（关键决策）：
# 把 parent_id/folder_id 放到组合索引最前面，这样：
# 1. 完整索引覆盖列表查询的"过滤 + 排序"，消除 Using filesort
# 2. 左前缀 [parent_id]/[folder_id] 可服务 ForeignKey on_delete=CASCADE
#    删除父记录时的 WHERE parent_id=? / folder_id=? 查询
# 3. 无需额外维护 Django 自动生成的单列外键索引，减少索引冗余
#
# 说明：
# - is_deleted=False 在文件查询中由 SoftDeletedManager.get_queryset() 自动添加，
#   生成的 SQL 仍会带该条件，因此索引包含 is_deleted 字段。
# - 私有空间含 tenant_id（多租户隔离），公共空间无 tenant_id。
# - 排序字段统一为 -created_at, -id，兼容游标分页。

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('document', '0006_auto_20260627_0807'),
    ]

    operations = [
        migrations.AddIndex(
            model_name='documentfolderprivate',
            index=models.Index(
                fields=['parent_id', 'tenant_id', 'is_deleted', '-created_at', '-id'],
                name='doc_pri_folder_list_idx',
            ),
        ),
        migrations.AddIndex(
            model_name='documentfileprivate',
            index=models.Index(
                fields=['folder_id', 'tenant_id', 'is_deleted', '-created_at', '-id'],
                name='doc_pri_file_list_idx',
            ),
        ),
        migrations.AddIndex(
            model_name='documentfolderpublic',
            index=models.Index(
                fields=['parent_id', 'is_deleted', '-created_at', '-id'],
                name='doc_pub_folder_list_idx',
            ),
        ),
        migrations.AddIndex(
            model_name='documentfilepublic',
            index=models.Index(
                fields=['folder_id', 'is_deleted', '-created_at', '-id'],
                name='doc_pub_file_list_idx',
            ),
        ),
    ]
