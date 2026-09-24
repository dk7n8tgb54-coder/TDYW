# 手写迁移（今日巡检工作台合并矩阵表改造）。

"""巡检单增加"已记录轮次"状态字段。

内容：
- InspectionDutySheet 新增 recorded_rounds（TextField 存 JSON 数组，
  如 '["r1","r2"]'，沿用本项目 JSON 状态字段的 TextField 惯例）：
  "记录本轮"成功后写入对应轮次，已记录轮次在后端只读、不能被再次修改；
- 回填：历史巡检单按已有巡检明细的 distinct 轮次回填 recorded_rounds
  （旧流程中"记录本轮"已落库的轮次即为已记录轮次），提交/作废单不受影响
  （它们本就不可修改）。

兼容性说明：
- 默认值为空串（无已记录轮次），对已有巡检单语义安全；
- 只新增一列并回填本表数据，不删除、不修改任何历史巡检数据与无关模型；
- 可回滚：反向直接删除该列（回填数据随之消失，属字段自身的逆操作）。
"""
import json

from django.db import migrations, models

# 固定四轮（与模型 INSPECTION_ROUND_VALUES 一致；迁移内不 import 业务模型）
_ROUND_VALUES = ['r1', 'r2', 'r3', 'r4']


def backfill_recorded_rounds(apps, schema_editor):
    """按巡检明细的 distinct 轮次回填各巡检单的已记录轮次。"""
    sheet_model = apps.get_model('equipment_lifecycle', 'InspectionDutySheet')
    record_model = apps.get_model('equipment_lifecycle', 'InspectionRecord')
    for sheet in sheet_model.objects.all().iterator():
        rounds = set(record_model.objects.filter(
            sheet_id=sheet.pk).values_list('round_no', flat=True))
        valid = [r for r in _ROUND_VALUES if r in rounds]
        if valid:
            sheet.recorded_rounds = json.dumps(valid, ensure_ascii=False)
            sheet.save(update_fields=['recorded_rounds'])


class Migration(migrations.Migration):

    dependencies = [
        ('equipment_lifecycle', '0023_remove_systemconfigvalue_field_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='inspectiondutysheet',
            name='recorded_rounds',
            field=models.TextField(
                blank=True, default='',
                help_text='已记录轮次 JSON 数组（如 ["r1","r2"]）：记录本轮成功后写入，'
                          '已记录轮次只读、不能被再次修改'),
        ),
        migrations.RunPython(backfill_recorded_rounds, migrations.RunPython.noop),
    ]
