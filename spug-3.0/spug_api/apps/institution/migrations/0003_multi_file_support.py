# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""多文件制度改造：新增制度文件条目与版本文件快照，存量数据回填

结构变更（依据《制度管理模块设计方案》§5/§9）：
- ManualFile：制度下 Word 文件的稳定条目（改名/排序/移除只影响待发布
  集合，ID 永不复用、记录不物理删除）。
- ManualVersionFile：每版完整、有序、不可变的文件快照清单。
- ManualOriginal/ManualDraft/ManualEditSession 挂 file 外键（回填后
  非空）；ManualOperationLog.file 可空（制度级动作不涉具体文件）。
- ManualVersion 旧单文件列保留为首快照兼容镜像，不删旧数据。

存量映射规则：
- 每个手册创建一个"主文件"条目；显示名按 当前草稿名 > 最新版本名 >
  最早原稿名 > 手册名.docx 取值，系统生成名（callback_/oo_cb_ 前缀）
  与空值回退为手册名，不据多条 ManualOriginal 推断多份正式文件。
- 历史 ManualVersion 每版一份文件 -> 该版一条快照（主文件，sort 0），
  路径/大小/哈希原样复制。
- 既有活跃编辑会话整体失效并清空 current_doc_key：document.key 协议
  变更（新增文件段），新旧协议不允许跨切流复用。

回滚边界：回退删除本次回填派生的文件条目与快照并解绑 file 外键。
一旦产生多文件草稿或新格式发布版本，旧模型无法完整表达，应停止写入
并采用前向修复，不得回退本迁移丢弃数据。
"""
from django.db import migrations, models
import django.db.models.deletion
from django.db.models import Q
from django.utils import timezone

# 与 services._SYSTEM_DRAFT_NAME_PREFIXES 保持一致（迁移内自包含，避免
# 引用业务模块内部实现）
_SYSTEM_DRAFT_NAME_PREFIXES = ('callback_', 'oo_cb_')


def _derive_display_name(manual, draft, latest_version, first_original):
    """存量主文件显示名：草稿名 > 最新版本名 > 最早原稿名 > 手册名.docx"""
    for raw in (
        draft.original_name if draft else '',
        latest_version.original_name if latest_version else '',
        first_original.original_name if first_original else '',
    ):
        name = (raw or '').strip()
        if name and not name.startswith(_SYSTEM_DRAFT_NAME_PREFIXES):
            return name
    return f'{manual.name}.docx'


def backfill_multi_file(apps, schema_editor):
    Manual = apps.get_model('institution', 'Manual')
    ManualFile = apps.get_model('institution', 'ManualFile')
    ManualVersion = apps.get_model('institution', 'ManualVersion')
    ManualVersionFile = apps.get_model('institution', 'ManualVersionFile')
    ManualDraft = apps.get_model('institution', 'ManualDraft')
    ManualEditSession = apps.get_model('institution', 'ManualEditSession')
    ManualOriginal = apps.get_model('institution', 'ManualOriginal')

    now = timezone.now()
    for manual in Manual.objects.all().order_by('id'):
        draft = ManualDraft.objects.filter(manual_id=manual.id).first()
        latest_version = ManualVersion.objects.filter(
            manual_id=manual.id).order_by('-version_no').first()
        first_original = ManualOriginal.objects.filter(
            manual_id=manual.id).order_by('id').first()
        main = ManualFile.objects.create(
            manual_id=manual.id,
            display_name=_derive_display_name(
                manual, draft, latest_version, first_original),
            sort_order=0, is_removed=False,
            created_by_id=manual.created_by_id,
        )
        if draft:
            draft.file = main
            draft.save(update_fields=['file'])
        # 历史版本 -> 每版一条快照（主文件，首位），值原样复制
        for version in ManualVersion.objects.filter(
                manual_id=manual.id).order_by('version_no'):
            ManualVersionFile.objects.create(
                version=version, manual_file=main,
                display_name=version.original_name or main.display_name,
                sort_order=0, file_path=version.file_path,
                file_size=version.file_size, file_hash=version.file_hash,
            )
        # 会话挂主文件；活跃会话整体失效（新旧协议不复用），旧 key 清空
        ManualEditSession.objects.filter(
            manual_id=manual.id,
        ).exclude(Q(revoked_at__isnull=True) & Q(expires_at__gt=now)).update(
            file=main, current_doc_key='')
        ManualEditSession.objects.filter(
            manual_id=manual.id, revoked_at__isnull=True,
            expires_at__gt=now,
        ).update(
            file=main, current_doc_key='',
            revoked_at=now, revoked_reason='多文件改造切流，编辑会话整体失效',
        )
        ManualOriginal.objects.filter(manual_id=manual.id).update(file=main)

    # ---- fail-closed 校验：任一断言失败即终止切流，旧数据未改动 ----
    manual_count = Manual.objects.count()
    file_count = ManualFile.objects.count()
    if file_count != manual_count:
        raise RuntimeError(
            f'institution 多文件回填校验失败: 手册数 {manual_count} != '
            f'主文件数 {file_count}')
    version_count = ManualVersion.objects.count()
    snapshot_count = ManualVersionFile.objects.count()
    if snapshot_count != version_count:
        raise RuntimeError(
            f'institution 多文件回填校验失败: 版本数 {version_count} != '
            f'快照数 {snapshot_count}')
    broken = []
    for version in ManualVersion.objects.all().order_by('id'):
        snap = ManualVersionFile.objects.filter(version_id=version.id).first()
        if snap is None:
            broken.append(f'version {version.id} 缺快照')
            continue
        if (snap.file_path != version.file_path or
                snap.file_hash != version.file_hash or
                snap.file_size != version.file_size):
            broken.append(f'version {version.id} 快照与旧文件列不一致')
    if broken:
        raise RuntimeError('institution 多文件回填校验失败: ' + '; '.join(broken[:5]))
    for label, qs in (
        ('草稿', ManualDraft.objects.filter(file__isnull=True)),
        ('编辑会话', ManualEditSession.objects.filter(file__isnull=True)),
        ('原稿', ManualOriginal.objects.filter(file__isnull=True)),
    ):
        if qs.exists():
            raise RuntimeError(
                f'institution 多文件回填校验失败: 存在未绑定主文件的{label}')


def revert_multi_file(apps, schema_editor):
    """回退：清空派生表与 file 外键（仅限未产生多文件写入时使用）"""
    ManualFile = apps.get_model('institution', 'ManualFile')
    ManualVersionFile = apps.get_model('institution', 'ManualVersionFile')
    ManualDraft = apps.get_model('institution', 'ManualDraft')
    ManualEditSession = apps.get_model('institution', 'ManualEditSession')
    ManualOriginal = apps.get_model('institution', 'ManualOriginal')
    ManualOperationLog = apps.get_model('institution', 'ManualOperationLog')
    ManualDraft.objects.update(file=None)
    ManualEditSession.objects.update(file=None)
    ManualOriginal.objects.update(file=None)
    ManualOperationLog.objects.update(file=None)
    ManualVersionFile.objects.all().delete()
    ManualFile.objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ('institution', '0002_manualeditsession_current_doc_key'),
    ]

    operations = [
        migrations.AlterField(
            model_name='manualdraft',
            name='manual',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                                    related_name='+', to='institution.manual',
                                    verbose_name='所属手册'),
        ),
        migrations.CreateModel(
            name='ManualFile',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('tenant_id', models.CharField(default='', help_text='租户标识',
                                              max_length=50)),
                ('display_name', models.CharField(max_length=255, verbose_name='文件显示名')),
                ('sort_order', models.IntegerField(default=0, verbose_name='排序')),
                ('is_removed', models.BooleanField(db_index=True, default=False,
                                                   verbose_name='已移除')),
                ('removed_at', models.DateTimeField(blank=True, null=True,
                                                    verbose_name='移除时间')),
                ('created_by', models.ForeignKey(null=True,
                                                 on_delete=models.SET_NULL,
                                                 related_name='+',
                                                 to='account.user',
                                                 verbose_name='创建人')),
                ('created_at', models.DateTimeField(auto_now_add=True,
                                                    verbose_name='创建时间')),
                ('manual', models.ForeignKey(on_delete=models.CASCADE,
                                             related_name='files',
                                             to='institution.manual',
                                             verbose_name='所属手册')),
            ],
            options={
                'verbose_name': '制度文件',
                'verbose_name_plural': '制度文件',
                'db_table': 'tdyw_institution_file',
                'ordering': ['sort_order', 'id'],
            },
        ),
        migrations.CreateModel(
            name='ManualVersionFile',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('tenant_id', models.CharField(default='', help_text='租户标识',
                                              max_length=50)),
                ('display_name', models.CharField(max_length=255, verbose_name='文件显示名')),
                ('sort_order', models.IntegerField(default=0, verbose_name='排序')),
                ('file_path', models.CharField(max_length=500, verbose_name='相对存储路径')),
                ('file_size', models.BigIntegerField(default=0, verbose_name='文件大小')),
                ('file_hash', models.CharField(blank=True, default='', max_length=64,
                                               verbose_name='SHA256')),
                ('manual_file', models.ForeignKey(on_delete=models.PROTECT,
                                                  related_name='version_snapshots',
                                                  to='institution.manualfile',
                                                  verbose_name='制度文件条目')),
                ('version', models.ForeignKey(on_delete=models.CASCADE,
                                              related_name='files',
                                              to='institution.manualversion',
                                              verbose_name='所属版本')),
            ],
            options={
                'verbose_name': '版本文件快照',
                'verbose_name_plural': '版本文件快照',
                'db_table': 'tdyw_institution_version_file',
                'ordering': ['sort_order', 'id'],
                'unique_together': (('version', 'manual_file'),),
            },
        ),
        migrations.AddField(
            model_name='manualoriginal',
            name='file',
            field=models.ForeignKey(null=True, on_delete=models.CASCADE,
                                    related_name='originals',
                                    to='institution.manualfile',
                                    verbose_name='所属制度文件'),
        ),
        migrations.AddField(
            model_name='manualdraft',
            name='file',
            field=models.OneToOneField(null=True, on_delete=models.CASCADE,
                                       related_name='draft',
                                       to='institution.manualfile',
                                       verbose_name='所属制度文件'),
        ),
        migrations.AddField(
            model_name='manualeditsession',
            name='file',
            field=models.ForeignKey(null=True, on_delete=models.CASCADE,
                                    related_name='edit_sessions',
                                    to='institution.manualfile',
                                    verbose_name='编辑的制度文件'),
        ),
        migrations.AddField(
            model_name='manualoperationlog',
            name='file',
            field=models.ForeignKey(blank=True, null=True,
                                    on_delete=models.SET_NULL, related_name='+',
                                    to='institution.manualfile',
                                    verbose_name='涉及制度文件'),
        ),
        migrations.AddIndex(
            model_name='manualfile',
            index=models.Index(fields=['manual', 'sort_order'],
                               name='inst_file_manual_idx'),
        ),
        migrations.AddIndex(
            model_name='manualversionfile',
            index=models.Index(fields=['version', 'sort_order'],
                               name='inst_vfile_ver_idx'),
        ),
        migrations.RunPython(backfill_multi_file, revert_multi_file),
        migrations.AlterField(
            model_name='manualdraft',
            name='file',
            field=models.OneToOneField(on_delete=models.CASCADE,
                                       related_name='draft',
                                       to='institution.manualfile',
                                       verbose_name='所属制度文件'),
        ),
        migrations.AlterField(
            model_name='manualeditsession',
            name='file',
            field=models.ForeignKey(on_delete=models.CASCADE,
                                    related_name='edit_sessions',
                                    to='institution.manualfile',
                                    verbose_name='编辑的制度文件'),
        ),
        migrations.AlterField(
            model_name='manualoriginal',
            name='file',
            field=models.ForeignKey(on_delete=models.CASCADE,
                                    related_name='originals',
                                    to='institution.manualfile',
                                    verbose_name='所属制度文件'),
        ),
    ]
