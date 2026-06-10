# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""
为文件夹模型添加/修复唯一约束

变更内容：
1. DocumentFolderPrivate：新增两个条件唯一约束
   - unique_root_folder_private:  同租户同用户根目录下不允许同名未删除文件夹
   - unique_subfolder_private:    同租户同用户同父目录下不允许同名未删除文件夹

2. DocumentFolderPublic：修复原有约束缺少 is_deleted=False 条件的 bug
   - 删除旧约束 unique_folder_name_parent_public（不区分软删除，导致 IntegrityError）
   - 新增 unique_root_folder_public:  根目录下不允许同名未删除文件夹
   - 新增 unique_subfolder_public:    同父目录下不允许同名未删除文件夹

前置条件：
- 执行此迁移前，需先运行历史数据扫描脚本修复重复数据
  参见：spug_api/scripts/scan_folder_duplicates.py

注意：
- parent=NULL 时，数据库 UniqueConstraint 的 NULL!=NULL 语义导致 (name, parent) 约束失效
- 因此拆分为根目录（parent IS NULL）和子目录（parent IS NOT NULL）两个约束
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('document', '0003_transfer_add_merging_choice'),
    ]

    operations = [
        # ===== DocumentFolderPrivate：新增约束 =====
        migrations.AddConstraint(
            model_name='documentfolderprivate',
            constraint=models.UniqueConstraint(
                condition=models.Q(models.Q(('parent__isnull', True), ('is_deleted', False))),
                fields=['tenant_id', 'created_by', 'name'],
                name='unique_root_folder_private',
            ),
        ),
        migrations.AddConstraint(
            model_name='documentfolderprivate',
            constraint=models.UniqueConstraint(
                condition=models.Q(models.Q(('parent__isnull', False), ('is_deleted', False))),
                fields=['tenant_id', 'created_by', 'name', 'parent'],
                name='unique_subfolder_private',
            ),
        ),

        # ===== DocumentFolderPublic：修复约束 =====
        # 先删除旧约束（缺少 is_deleted=False 条件）
        migrations.RemoveConstraint(
            model_name='documentfolderpublic',
            name='unique_folder_name_parent_public',
        ),
        # 新增根目录约束
        migrations.AddConstraint(
            model_name='documentfolderpublic',
            constraint=models.UniqueConstraint(
                condition=models.Q(models.Q(('parent__isnull', True), ('is_deleted', False))),
                fields=['name'],
                name='unique_root_folder_public',
            ),
        ),
        # 新增子目录约束
        migrations.AddConstraint(
            model_name='documentfolderpublic',
            constraint=models.UniqueConstraint(
                condition=models.Q(models.Q(('parent__isnull', False), ('is_deleted', False))),
                fields=['name', 'parent'],
                name='unique_subfolder_public',
            ),
        ),
    ]
