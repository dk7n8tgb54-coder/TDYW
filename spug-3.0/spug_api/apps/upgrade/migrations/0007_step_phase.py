# Generated for adding phase field to UpgradeRecordStep and UpgradePlanStep

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('upgrade', '0006_status_log'),
    ]

    operations = [
        # 1. UpgradeRecordStep 加 phase 字段
        migrations.AddField(
            model_name='upgraderecordstep',
            name='phase',
            field=models.CharField(blank=True, default='', max_length=20, verbose_name='所属阶段'),
        ),
        # 2. UpgradePlanStep 加 phase 字段
        migrations.AddField(
            model_name='upgradeplanstep',
            name='phase',
            field=models.CharField(blank=True, default='', max_length=20, verbose_name='所属阶段'),
        ),
    ]
