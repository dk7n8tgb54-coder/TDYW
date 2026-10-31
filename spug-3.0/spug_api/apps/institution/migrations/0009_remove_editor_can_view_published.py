# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""第二轮权限模型改造（2026-10-31）：退役 editor_can_view_published 开关

本轮为纯权限放宽 + 开关退役，无数据冲突：
- Manual.editor_can_view_published 字段删除（查看发布版的新判定为
  所有者 / 平台超管 / can_view 授权，仅 can_edit 授权不再可见——开关
  语义整体废弃）。
- 0008 之后的文件分工、提交编制与编辑会话在新模型下依旧有效，不做
  会话清理；所有者移交时的会话撤销由服务层动作承担
  （authorization_services.set_manual_owner）。
- 回滚 = AddField(default=True)（与原字段定义一致）。
"""
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('institution', '0008_manual_owner_and_account_grants'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='manual',
            name='editor_can_view_published',
        ),
    ]
