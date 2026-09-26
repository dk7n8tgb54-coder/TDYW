# Copyright: (c) OpenSpug Organization. https://github.com/openspug
# Released under the AGPL-3.0 License.
"""旧平面维护台账模板受控停用命令（2026-09 行对象树第一阶段改造）。

背景：维护台账引入"行对象树（行方向多级）+ 平面列项目"矩阵结构后，
新台账必须由"行结构 + 列项目"模板生成；未配置任何行节点的旧平面模板
（仅 OperationLedgerTemplateItem 列项目）不再支持新建台账，统一受控停用。

安全约束：
- 只做停用（is_active=False），不删除模板、列项目与任何台账数据；
- 已停用模板跳过（幂等，可重复执行）；
- 默认 dry-run 只统计；--confirm 才实际写库；
- 历史台账（含由旧模板生成的草稿/已提交/已复核台账）不受影响，
  继续保持可查看与可导出；旧模板生成的历史草稿不能再编辑矩阵结构，
  但保留 entries 明细编辑接口（后端兼容）。

用法：
    python manage.py deactivate_flat_ledger_templates            # 预览
    python manage.py deactivate_flat_ledger_templates --tenant admin
    python manage.py deactivate_flat_ledger_templates --confirm  # 执行停用
"""
from django.core.management.base import BaseCommand

from apps.equipment_lifecycle.models import OperationLedgerTemplate


class Command(BaseCommand):
    help = '停用未配置行结构的旧平面维护台账模板（不删除任何数据，幂等）'

    def add_arguments(self, parser):
        parser.add_argument('--tenant', default=None, help='仅处理指定租户（默认全部租户）')
        parser.add_argument('--confirm', action='store_true', help='实际执行停用（缺省仅预览）')

    def handle(self, *args, **options):
        tenant = options.get('tenant')
        confirm = options.get('confirm')
        templates = OperationLedgerTemplate.objects.all().filter(is_active=True)
        if tenant:
            templates = templates.filter(tenant_id=tenant)
        # 行节点为空的启用模板 = 旧平面模板（新结构模板至少有一个行节点）
        flat_templates = [t for t in templates if not t.row_nodes.exists()]
        if not flat_templates:
            self.stdout.write('没有需要停用的旧平面模板。')
            return
        for template in flat_templates:
            self.stdout.write('[%s] 模板 #%s %s（%s，列项目 %d 个）'
                              % (template.tenant_id, template.id, template.name,
                                 template.ledger_type,
                                 template.items.filter(is_active=True).count()))
        if not confirm:
            self.stdout.write(self.style.WARNING(
                'dry-run：共 %d 个模板将被停用；加 --confirm 执行。' % len(flat_templates)))
            return
        for template in flat_templates:
            template.is_active = False
            template.save(update_fields=['is_active', 'updated_at'])
        self.stdout.write(self.style.SUCCESS(
            '已停用 %d 个旧平面模板（历史台账不受影响）。' % len(flat_templates)))
