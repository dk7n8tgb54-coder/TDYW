# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""状态日志支持步骤驱动的阶段完成记录。

- 新增 phase 字段：关联阶段名（phase_done 时用）
- 新增 outcome 字段：阶段完成结果 done/failed/revoked
- target_action 放宽 max_length 20→50（回退目标改为自定义阶段名）
- 老数据 outcome 默认 done（default 即可，无需 RunSQL）
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('upgrade', '0017_phase_to_display_name'),
    ]

    operations = [
        migrations.AddField(
            model_name='upgradestatuslog',
            name='phase',
            field=models.CharField(blank=True, default='', max_length=50, verbose_name='关联阶段'),
        ),
        migrations.AddField(
            model_name='upgradestatuslog',
            name='outcome',
            field=models.CharField(
                choices=[('done', '正常完成'), ('failed', '已失败'), ('revoked', '已撤销')],
                default='done', max_length=20, verbose_name='阶段完成结果',
            ),
        ),
        migrations.AlterField(
            model_name='upgradestatuslog',
            name='target_action',
            field=models.CharField(blank=True, default='', max_length=50, verbose_name='回退目标阶段'),
        ),
        migrations.AlterField(
            model_name='upgradestatuslog',
            name='action',
            field=models.CharField(
                choices=[
                    ('start', '升级启动'), ('backup', '备份完成'), ('gray_release', '灰度发布完成'),
                    ('full_release', '全量发布完成'), ('test', '升级测试完成'),
                    ('test_pass', '升级测试通过'), ('test_fail', '升级测试失败'),
                    ('rollback', '回退'), ('pause', '暂停'), ('resume', '继续'),
                    ('observe', '观察完成'), ('complete', '升级完成'), ('phase_done', '阶段完成'),
                ],
                max_length=20, verbose_name='动作类型',
            ),
        ),
    ]
