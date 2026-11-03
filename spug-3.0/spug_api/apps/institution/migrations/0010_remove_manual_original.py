# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""原稿体系移除（2026-11-02）：删除来源原稿字段与原稿记录表

背景：新增制度文件改为「上传文件直接建立当前草稿」，不再额外保存原稿
副本；草稿缺失时只从当前生效版本快照恢复，不再提供原稿历史/预览/下载、
按原稿重建草稿或更换来源。本迁移只做 schema 收口：

1. `ManualDraft.source_original` 外键删除（草稿不再引用原稿记录）。
2. `ManualOriginal` 模型/表 `tdyw_institution_original` 删除。

**数据范围与不可恢复性（部署前必读）**：
- 本迁移执行后原稿表连同全部原稿记录（名称/上传人/时间/哈希/路径）
  一并从数据库删除，反向迁移只能重建空表结构，**记录不可恢复**。
- 迁移本身**不做任何物理文件删除**：原稿物理文件位于存储根
  `<institution storage>/originals/`，由独立的幂等清理入口
  `python manage.py purge_institution_originals` 负责（路径校验限定在
  originals 根目录内，绝不误删 drafts/ 或 versions/ 下的草稿与发布
  快照）。推荐部署顺序：先执行清理命令（旧表仍在时可「删文件→删记录」
  一条条安全推进，失败逐项报告），确认成功后再 migrate 本迁移；若先
  migrate，命令仍可对 originals 目录做幂等扫描收尾。
- 保留数据：当前草稿、全部发布版本快照（ManualVersion/
  ManualVersionFile 及 versions/ 物理文件）、操作记录、授权、文件
  条目等均不受影响；草稿的 base_version 与发布版本关系不变。

**回滚**：CreateModel(ManualOriginal) + AddField(source_original) 仅恢复
结构（空表、字段全 NULL），已删除的原稿记录与文件不会回来。
"""
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('institution', '0009_remove_editor_can_view_published'),
    ]

    operations = [
        # 先删草稿对原稿的引用，再删原稿表（避免反向迁移时外键无处指向）
        migrations.RemoveField(
            model_name='manualdraft',
            name='source_original',
        ),
        migrations.DeleteModel(
            name='manualoriginal',
        ),
    ]
