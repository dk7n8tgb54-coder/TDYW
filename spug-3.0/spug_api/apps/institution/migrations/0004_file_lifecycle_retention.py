# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""文件生命周期保留策略：原稿清理标记与版本保留状态

结构变更（2026-10-29 保留策略，全部为可空/默认值新增列，历史数据
零改写——存量原稿与版本快照在迁移后视为"未清理"，行为与迁移前一致）：
- ManualOriginal.cleaned_at：原稿本体清理时间。保护边界为"该文件首次
  进入成功发布的版本"，首次发布并经过配置缓冲期后原稿本体才可成为
  清理候选；记录行与来源元数据（名称/上传人/时间/哈希/路径）永久保留。
- ManualVersion.long_term_protected：重要版本长期保留标记。
- ManualVersion.files_cleaned_at / files_clean_status / files_clean_error：
  整版文件清理状态（'' 未清理 / 'partial' 部分清理失败可重试 /
  'cleaned' 整版文件已清理）；当前生效版本永久受保护，is_effective=False
  不作为可清理依据。
- ManualVersionFile.cleaned_at：单份快照物理文件清理时间；快照行
  （清单/名称/哈希）永久保留，供"文件已按保留策略清理"标记与审计。

不启用自动物理清理：清理仅能经显式的保留策略预检/执行入口发生，
且期限未配置时执行入口整体拒绝。
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('institution', '0003_multi_file_support'),
    ]

    operations = [
        migrations.AddField(
            model_name='manualoriginal',
            name='cleaned_at',
            field=models.DateTimeField(blank=True, null=True,
                                       verbose_name='原稿清理时间'),
        ),
        migrations.AddField(
            model_name='manualversion',
            name='long_term_protected',
            field=models.BooleanField(default=False, verbose_name='长期保留'),
        ),
        migrations.AddField(
            model_name='manualversion',
            name='files_cleaned_at',
            field=models.DateTimeField(blank=True, null=True,
                                       verbose_name='整版文件清理时间'),
        ),
        migrations.AddField(
            model_name='manualversion',
            name='files_clean_status',
            field=models.CharField(blank=True, default='', max_length=20,
                                   verbose_name='整版文件清理状态'),
        ),
        migrations.AddField(
            model_name='manualversion',
            name='files_clean_error',
            field=models.TextField(blank=True, default='',
                                   verbose_name='整版文件清理失败说明'),
        ),
        migrations.AddField(
            model_name='manualversionfile',
            name='cleaned_at',
            field=models.DateTimeField(blank=True, null=True,
                                       verbose_name='快照清理时间'),
        ),
    ]
