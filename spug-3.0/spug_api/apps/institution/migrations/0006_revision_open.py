# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""修订状态字段（2026-10-30）：ManualFile.revision_open 显式记录"本轮修订进行中"

此前"修订是否进行中"只能凭草稿哈希与生效快照是否一致推断，发布后保留的
工作副本会被误读成"有未发布草稿"。本迁移引入显式布尔状态：

- AddField default=True：所有存量文件先保守置为"修订进行中"——绝不因状态
  迁移丢失可能尚未发布的修改或编辑会话。
- RunPython 回填（保守规则，只把"可确认已结束"的文件翻转为 False）：
  文件存在于当前生效版本快照中、草稿有效且哈希与该快照一致、且该文件
  无活跃编辑会话（会话可能携带未同步内容）时，本轮修订视为已随发布结束；
  其余一切情形（含草稿缺失、哈希不一致、有活跃会话、当前版本不含该文件）
  保持 True。旧行为下无法区分的"发布后原样保留的工作副本"与"修改后未
  发布的工作副本"按哈希一致判定，不丢失任何数据。
- 回滚：RemoveField 即可，字段值不承载唯一数据（可由发布动作重建）。
"""
from django.db import migrations, models
from django.utils import timezone


def _backfill_revision_open(apps, schema_editor):
    """把"发布后原样保留"的文件修订状态翻转为已结束（False）

    使用迁移当时的模型注册表（历史模型）；测试中以真实 apps 调用同一
    函数验证回填规则（见 tests/characterization/test_revision_state.py）。
    """
    ManualFile = apps.get_model('institution', 'ManualFile')
    ManualDraft = apps.get_model('institution', 'ManualDraft')
    ManualEditSession = apps.get_model('institution', 'ManualEditSession')
    ManualVersionFile = apps.get_model('institution', 'ManualVersionFile')

    # 活跃编辑会话占用的文件：可能有未同步内容，保守保持"修订进行中"
    busy_file_ids = set(ManualEditSession.objects.filter(
        revoked_at__isnull=True, expires_at__gt=timezone.now(),
    ).values_list('file_id', flat=True))

    drafts_by_file = {d.file_id: d for d in ManualDraft.objects.all()}
    closable_ids = []
    for snap in ManualVersionFile.objects.filter(
            version__manual__current_version=models.F('version')):
        draft = drafts_by_file.get(snap.manual_file_id)
        if not draft or not draft.file_path:
            continue
        if draft.file_hash != snap.file_hash:
            continue
        if snap.manual_file_id in busy_file_ids:
            continue
        closable_ids.append(snap.manual_file_id)
    if closable_ids:
        ManualFile.objects.filter(id__in=closable_ids).update(revision_open=False)


class Migration(migrations.Migration):

    dependencies = [
        ('institution', '0005_file_assignment'),
    ]

    operations = [
        migrations.AddField(
            model_name='manualfile',
            name='revision_open',
            field=models.BooleanField(default=True, verbose_name='修订进行中'),
        ),
        migrations.RunPython(_backfill_revision_open, migrations.RunPython.noop),
    ]
