"""故障登记人与进展记录人：手动输入姓名，与登录账号审计字段独立。

内容：
- SystemFault 新增 registrar_name 列（varchar(200)，可空文本，default=''）：
  手动输入的登记人姓名（多人以顿号分隔），只表示实际登记故障的人，不代表其负责后续跟进
  或承担维修责任；不关联 User——实际登记人可能没有系统账号（共用登录
  账号场景），与系统档案 responsible_user_name 的姓名快照口径一致；
- SystemFaultHandlingRecord 新增 recorder_name 列（varchar(200)，
  default=''）：手动输入的进展记录人姓名（多人以顿号分隔）（语义同上）；handler 外键保留，
  语义调整为"记录操作账号（审计）"，历史记录无 recorder_name 时
  展示回落到 handler 的用户名；
- created_by / handler 的 help_text 同步调整（created_by/handler 注明
  登录账号审计口径），仅元数据。

兼容性说明：
- 两列均带空串默认：历史数据不回填、不改写，列表/详情/导出按空展示
  （前端显示"-"，进展记录人回落 handler 用户名）；
- 新增记录时由视图层写入姓名（缺省当前登录用户显示姓名），不依赖
  数据库默认值；
- AddField 空串默认；AlterField 仅涉及 help_text，均无破坏性 DDL，
  不触碰任何既有列；
- 可回滚：反向删除两个新列并恢复原 help_text。
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('equipment_lifecycle', '0031_fault_handling_progress_type'),
    ]

    operations = [
        migrations.AddField(
            model_name='systemfault',
            name='registrar_name',
            field=models.CharField(blank=True, default='',
                                   help_text='故障登记人（手动输入的登记人姓名，多人以顿号分隔；'
                                             '实际添加本条故障记录的人，不代表后续跟进与维修责任；'
                                             '与登录账号 created_by 独立，历史数据可为空）',
                                   max_length=200),
        ),
        migrations.AddField(
            model_name='systemfaulthandlingrecord',
            name='recorder_name',
            field=models.CharField(blank=True, default='',
                                   help_text='进展记录人（手动输入的记录人姓名，多人以顿号分隔；'
                                             '实际添加本条进展的人，不代表负责整个故障；'
                                             '空串=历史记录，展示回落 handler 用户名）',
                                   max_length=200),
        ),
        migrations.AlterField(
            model_name='systemfault',
            name='created_by',
            field=models.ForeignKey(help_text='创建人（实际登录账号，仅用于审计）',
                                    on_delete=models.PROTECT, related_name='+',
                                    to='account.user'),
        ),
        migrations.AlterField(
            model_name='systemfaulthandlingrecord',
            name='handler',
            field=models.ForeignKey(help_text='记录操作账号（审计字段；进展记录人姓名见 recorder_name）',
                                    on_delete=models.PROTECT, related_name='+',
                                    to='account.user'),
        ),
    ]
