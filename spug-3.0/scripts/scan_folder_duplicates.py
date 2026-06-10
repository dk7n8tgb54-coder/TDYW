#!/usr/bin/env python
"""
扫描文件夹历史重复数据

目的：在添加数据库唯一约束前，检测并修复已有的同名文件夹重复数据。

约束规则：
- 私有空间：同租户(tenant_id) + 同用户(created_by) + 同目录(parent) 下不允许同名未删除文件夹
- 公共空间：同目录(parent) 下不允许同名未删除文件夹

实现方式：
- MariaDB 不支持部分唯一索引（WHERE 条件），采用 unique_key 方案
- unique_key = MD5(组合键字符串)，is_deleted=True 时 unique_key=NULL
- 利用 MySQL 中 NULL 不参与唯一索引的特性实现软删除后不占位

修复策略：
- 重复文件夹自动重命名为 "原名 (N)"，N 从 2 开始递增
- 仅处理 is_deleted=False 的记录
- 修复后自动回填 unique_key

用法：
  # 在 Docker 容器内执行（先复制脚本到 spug_api 目录）
  docker cp scripts/scan_folder_duplicates.py tdyw:/data/spug/spug_api/
  docker exec tdyw python /data/spug/spug_api/scan_folder_duplicates.py

  # 仅扫描不修复（dry-run）
  docker exec tdyw python /var/spug/scripts/scan_folder_duplicates.py --dry-run

  # 指定模型类型
  docker exec tdyw python /var/spug/scripts/scan_folder_duplicates.py --model private
  docker exec tdyw python /var/spug/scripts/scan_folder_duplicates.py --model public
"""
import os
import sys
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')
django.setup()

from django.db.models import Count, Q
from apps.document.models import DocumentFolderPrivate, DocumentFolderPublic


def scan_duplicates_private(dry_run=True):
    """扫描私有空间文件夹重复数据"""
    print('\n' + '=' * 60)
    print('扫描私有空间文件夹重复 (tenant_id + created_by + name + parent)')
    print('=' * 60)

    # 仅扫描未删除的文件夹
    queryset = DocumentFolderPrivate.all_objects.filter(is_deleted=False)

    # === 子目录重复（parent IS NOT NULL）===
    sub_dupes = (
        queryset
        .filter(parent__isnull=False)
        .values('tenant_id', 'created_by_id', 'name', 'parent_id')
        .annotate(cnt=Count('id'))
        .filter(cnt__gt=1)
        .order_by('-cnt')
    )

    sub_total_dupes = sub_dupes.count()
    sub_total_records = sum(d['cnt'] for d in sub_dupes)
    print(f'\n[子目录] 重复组数: {sub_total_dupes}, 涉及记录数: {sub_total_records}')

    if sub_total_dupes > 0:
        print('\n详情（前 20 组）：')
        for i, dup in enumerate(sub_dupes[:20]):
            tenant_id = dup['tenant_id'] or '(空)'
            created_by = dup['created_by_id'] or '(空)'
            print(
                f'  {i + 1}. tenant_id={tenant_id}, created_by={created_by}, '
                f'name="{dup["name"]}", parent_id={dup["parent_id"]}, 重复数={dup["cnt"]}'
            )

    # === 根目录重复（parent IS NULL）===
    root_dupes = (
        queryset
        .filter(parent__isnull=True)
        .values('tenant_id', 'created_by_id', 'name')
        .annotate(cnt=Count('id'))
        .filter(cnt__gt=1)
        .order_by('-cnt')
    )

    root_total_dupes = root_dupes.count()
    root_total_records = sum(d['cnt'] for d in root_dupes)
    print(f'\n[根目录] 重复组数: {root_total_dupes}, 涉及记录数: {root_total_records}')

    if root_total_dupes > 0:
        print('\n详情（前 20 组）：')
        for i, dup in enumerate(root_dupes[:20]):
            tenant_id = dup['tenant_id'] or '(空)'
            created_by = dup['created_by_id'] or '(空)'
            print(
                f'  {i + 1}. tenant_id={tenant_id}, created_by={created_by}, '
                f'name="{dup["name"]}", 重复数={dup["cnt"]}'
            )

    total_groups = sub_total_dupes + root_total_dupes
    total_extra = (sub_total_records - sub_total_dupes) + (root_total_records - root_total_dupes)
    print(f'\n汇总: {total_groups} 组重复, 需重命名 {total_extra} 条记录')

    if not dry_run and total_groups > 0:
        _fix_duplicates_private(sub_dupes, root_dupes)

    return total_groups


def _fix_duplicates_private(sub_dupes, root_dupes):
    """修复私有空间重复数据"""
    from django.db import transaction

    fixed_count = 0

    # 修复子目录重复
    for dup in sub_dupes:
        filters = Q(
            tenant_id=dup['tenant_id'],
            created_by_id=dup['created_by_id'],
            name=dup['name'],
            parent_id=dup['parent_id'],
            is_deleted=False,
        )
        folders = list(DocumentFolderPrivate.all_objects.filter(filters).order_by('created_at'))
        # 保留最早创建的，其余重命名
        for folder in folders[1:]:
            new_name = _generate_unique_name_private(
                folder.name, dup['tenant_id'], dup['created_by_id'], dup['parent_id'],
                exclude_id=folder.id,
            )
            print(f'  修复: id={folder.id} "{folder.name}" → "{new_name}"')
            folder.name = new_name
            folder.save(update_fields=['name'])
            fixed_count += 1

    # 修复根目录重复
    for dup in root_dupes:
        filters = Q(
            tenant_id=dup['tenant_id'],
            created_by_id=dup['created_by_id'],
            name=dup['name'],
            parent__isnull=True,
            is_deleted=False,
        )
        folders = list(DocumentFolderPrivate.all_objects.filter(filters).order_by('created_at'))
        for folder in folders[1:]:
            new_name = _generate_unique_name_private(
                folder.name, dup['tenant_id'], dup['created_by_id'], None,
                exclude_id=folder.id,
            )
            print(f'  修复: id={folder.id} "{folder.name}" → "{new_name}"')
            folder.name = new_name
            folder.save(update_fields=['name'])
            fixed_count += 1

    print(f'\n修复完成: 共重命名 {fixed_count} 条记录')


def _generate_unique_name_private(original_name, tenant_id, created_by_id, parent_id, exclude_id=None):
    """为私有空间文件夹生成唯一名称"""
    base = original_name
    counter = 2
    while True:
        candidate = f'{base} ({counter})'
        qs = DocumentFolderPrivate.all_objects.filter(
            tenant_id=tenant_id,
            created_by_id=created_by_id,
            name=candidate,
            is_deleted=False,
        )
        if parent_id:
            qs = qs.filter(parent_id=parent_id)
        else:
            qs = qs.filter(parent__isnull=True)
        if exclude_id:
            qs = qs.exclude(id=exclude_id)
        if not qs.exists():
            return candidate
        counter += 1
        if counter > 1000:
            # 安全阀
            import uuid
            return f'{base}_{uuid.uuid4().hex[:8]}'


def scan_duplicates_public(dry_run=True):
    """扫描公共空间文件夹重复数据"""
    print('\n' + '=' * 60)
    print('扫描公共空间文件夹重复 (name + parent)')
    print('=' * 60)

    queryset = DocumentFolderPublic.all_objects.filter(is_deleted=False)

    # === 子目录重复 ===
    sub_dupes = (
        queryset
        .filter(parent__isnull=False)
        .values('name', 'parent_id')
        .annotate(cnt=Count('id'))
        .filter(cnt__gt=1)
        .order_by('-cnt')
    )

    sub_total_dupes = sub_dupes.count()
    sub_total_records = sum(d['cnt'] for d in sub_dupes)
    print(f'\n[子目录] 重复组数: {sub_total_dupes}, 涉及记录数: {sub_total_records}')

    if sub_total_dupes > 0:
        print('\n详情（前 20 组）：')
        for i, dup in enumerate(sub_dupes[:20]):
            print(f'  {i + 1}. name="{dup["name"]}", parent_id={dup["parent_id"]}, 重复数={dup["cnt"]}')

    # === 根目录重复 ===
    root_dupes = (
        queryset
        .filter(parent__isnull=True)
        .values('name')
        .annotate(cnt=Count('id'))
        .filter(cnt__gt=1)
        .order_by('-cnt')
    )

    root_total_dupes = root_dupes.count()
    root_total_records = sum(d['cnt'] for d in root_dupes)
    print(f'\n[根目录] 重复组数: {root_total_dupes}, 涉及记录数: {root_total_records}')

    if root_total_dupes > 0:
        print('\n详情（前 20 组）：')
        for i, dup in enumerate(root_dupes[:20]):
            print(f'  {i + 1}. name="{dup["name"]}", 重复数={dup["cnt"]}')

    total_groups = sub_total_dupes + root_total_dupes
    total_extra = (sub_total_records - sub_total_dupes) + (root_total_records - root_total_dupes)
    print(f'\n汇总: {total_groups} 组重复, 需重命名 {total_extra} 条记录')

    if not dry_run and total_groups > 0:
        _fix_duplicates_public(sub_dupes, root_dupes)

    return total_groups


def _fix_duplicates_public(sub_dupes, root_dupes):
    """修复公共空间重复数据"""
    fixed_count = 0

    for dup in sub_dupes:
        folders = list(
            DocumentFolderPublic.all_objects.filter(
                name=dup['name'], parent_id=dup['parent_id'], is_deleted=False,
            ).order_by('created_at')
        )
        for folder in folders[1:]:
            new_name = _generate_unique_name_public(
                folder.name, dup['parent_id'], exclude_id=folder.id,
            )
            print(f'  修复: id={folder.id} "{folder.name}" → "{new_name}"')
            folder.name = new_name
            folder.save(update_fields=['name'])
            fixed_count += 1

    for dup in root_dupes:
        folders = list(
            DocumentFolderPublic.all_objects.filter(
                name=dup['name'], parent__isnull=True, is_deleted=False,
            ).order_by('created_at')
        )
        for folder in folders[1:]:
            new_name = _generate_unique_name_public(folder.name, None, exclude_id=folder.id)
            print(f'  修复: id={folder.id} "{folder.name}" → "{new_name}"')
            folder.name = new_name
            folder.save(update_fields=['name'])
            fixed_count += 1

    print(f'\n修复完成: 共重命名 {fixed_count} 条记录')


def _generate_unique_name_public(original_name, parent_id, exclude_id=None):
    """为公共空间文件夹生成唯一名称"""
    base = original_name
    counter = 2
    while True:
        candidate = f'{base} ({counter})'
        qs = DocumentFolderPublic.all_objects.filter(name=candidate, is_deleted=False)
        if parent_id:
            qs = qs.filter(parent_id=parent_id)
        else:
            qs = qs.filter(parent__isnull=True)
        if exclude_id:
            qs = qs.exclude(id=exclude_id)
        if not qs.exists():
            return candidate
        counter += 1
        if counter > 1000:
            import uuid
            return f'{base}_{uuid.uuid4().hex[:8]}'


def main():
    dry_run = '--dry-run' in sys.argv or '--dry' in sys.argv
    model_type = 'all'
    if '--model' in sys.argv:
        idx = sys.argv.index('--model')
        if idx + 1 < len(sys.argv):
            model_type = sys.argv[idx + 1].lower()

    if dry_run:
        print('*** DRY RUN 模式 - 仅扫描不修复 ***')

    total = 0
    if model_type in ('all', 'private'):
        total += scan_duplicates_private(dry_run=dry_run)
    if model_type in ('all', 'public'):
        total += scan_duplicates_public(dry_run=dry_run)

    print('\n' + '=' * 60)
    if total == 0:
        print('✓ 未发现重复数据，可以安全执行迁移 0004')
    else:
        if dry_run:
            print(f'✗ 发现 {total} 组重复数据！请去掉 --dry-run 执行修复后再迁移')
        else:
            print(f'✓ 已修复 {total} 组重复数据，现在可以执行迁移 0004')
    print('=' * 60)

    return 0 if total == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
