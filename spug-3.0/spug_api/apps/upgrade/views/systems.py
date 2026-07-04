# Copyright: (c) OpenSpug Organization. https://github.com/openspug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""升级系统候选项字典视图（按租户隔离）

GET    /api/upgrade/systems/             获取当前租户启用中的系统候选列表
POST   /api/upgrade/systems/create/       新增系统候选项（同租户内 trim + 大小写不敏感去重）
DELETE /api/upgrade/systems/<id>/delete/  移除系统候选项（有历史记录则停用，无则物理删除）

租户隔离：每个租户维护独立的系统候选列表，互不可见。
不同租户允许存在相同系统名，同一租户内不可重复。
历史升级记录的 system 字段是纯文本，不受本表停用/删除影响。
"""
from django.views import View
from django.utils import timezone
from libs import json_response, auth, Argument, JsonParser
from apps.upgrade.models import UpgradeSystem, UpgradeRecord


class UpgradeSystemListView(View):
    """获取启用中的系统候选项列表"""

    @auth('upgrade.upgrade.view')
    def get(self, request):
        tenant_id = request.user.tenant_id
        qs = UpgradeSystem.objects.filter(
            tenant_id=tenant_id, is_active=True
        ).order_by('sort_order', 'name')
        data = [{'id': s.id, 'name': s.name, 'sort_order': s.sort_order} for s in qs]
        return json_response(data)


class UpgradeSystemCreateView(View):
    """新增系统候选项

    - name 自动 trim
    - 大小写不敏感去重：若已存在同名（忽略大小写）系统，返回已存在项并提示
    - 新增成功后返回新项
    """

    @auth('upgrade.upgrade.edit')
    def post(self, request):
        form, error = JsonParser(
            Argument('name', help='请输入系统名称'),
        ).parse(request.body)

        if error:
            return json_response(error=error)

        name = (form.name or '').strip()
        if not name:
            return json_response(error='系统名称不能为空')
        if len(name) > 100:
            return json_response(error='系统名称过长（最多 100 字符）')

        tenant_id = request.user.tenant_id

        # 同租户内大小写不敏感查重（不同租户允许同名）
        existing = UpgradeSystem.objects.filter(
            tenant_id=tenant_id, name__iexact=name
        ).first()
        if existing:
            # 已存在：若已停用则恢复启用，确保立即可选
            if not existing.is_active:
                existing.is_active = True
                existing.updated_at = timezone.now().strftime('%Y-%m-%d %H:%M:%S')
                existing.updated_by = request.user
                existing.save()
            return json_response({
                'id': existing.id, 'name': existing.name, 'sort_order': existing.sort_order,
                'existed': True,
            })

        now = timezone.now().strftime('%Y-%m-%d %H:%M:%S')
        # 新增项 sort_order 取当前租户内最大 +1（排在末尾）
        max_order = UpgradeSystem.objects.filter(
            tenant_id=tenant_id
        ).order_by('-sort_order').first()
        next_order = (max_order.sort_order + 1) if max_order else 1

        obj = UpgradeSystem.objects.create(
            tenant_id=tenant_id,
            name=name,
            is_active=True,
            sort_order=next_order,
            created_at=now,
            created_by=request.user,
        )
        return json_response({'id': obj.id, 'name': obj.name, 'sort_order': obj.sort_order, 'existed': False})


class UpgradeSystemDeleteView(View):
    """移除系统候选项

    语义：从候选列表移除，不影响已有升级记录的 system 字段。

    规则：
    - 该系统已被历史升级记录使用 → 停用（is_active=False），返回 disabled=True
      停用后不再出现在新建/编辑下拉，但仍可在列表筛选中找到（历史兜底）
    - 该系统无任何关联升级记录 → 物理删除
    - 已停用的系统再次移除 → 直接物理删除（若仍无关联记录）
    """

    @auth('upgrade.system.manage')
    def delete(self, request, pk):
        tenant_id = request.user.tenant_id
        try:
            obj = UpgradeSystem.objects.get(pk=pk, tenant_id=tenant_id)
        except UpgradeSystem.DoesNotExist:
            return json_response(error='系统候选项不存在或无权限')

        name = obj.name

        # 检查当前租户是否有关联升级记录（system 是纯文本字段）
        has_records = UpgradeRecord.objects.filter(
            tenant_id=tenant_id, system=name
        ).exists()

        if has_records:
            # 有关联记录：只能停用，不能物理删除
            if obj.is_active:
                obj.is_active = False
                obj.updated_at = timezone.now().strftime('%Y-%m-%d %H:%M:%S')
                obj.updated_by = request.user
                obj.save()
                return json_response({
                    'disabled': True,
                    'msg': f'系统「{name}」已被升级记录使用，已从候选列表停用（不影响已有记录）',
                })
            else:
                return json_response({
                    'disabled': True,
                    'msg': f'系统「{name}」已处于停用状态',
                })

        # 无关联记录：物理删除
        obj.delete()
        return json_response({
            'deleted': True,
            'msg': f'系统「{name}」已从候选列表移除',
        })
