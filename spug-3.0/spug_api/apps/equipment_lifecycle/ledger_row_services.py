# Copyright: (c) OpenSpug Organization. https://github.com/openspug
# Released under the AGPL-3.0 License.
"""设备全生命周期——台账行对象树与矩阵单元格服务（第一阶段）。

行方向多级对象结构（最大 5 级）+ 平面列项目：
- 模板行节点（OperationLedgerRowTemplateNode）定义行结构：
  group 普通分组 / repeat_group 可重复分组（如"信道"）/ check 行对象叶子
  （如"主电台""备电台"）；
- 实际行实例（OperationLedgerRowInstance）是行节点在某张台账中的具体实例
  （"第1信道""第2信道"），可重复分组可创建多个实例，结构不在模板中复制；
- 实际单元格（OperationLedgerItem）= 行叶子实例 × 启用列项目，列项目只在
  模板中配置一次即可被所有行叶子复用；
- 单元格结果支持 未填写(空串)/正常/异常/不适用/待复核：生成即"未填写"，
  未填写不被自动转换为正常；必填单元格未填写在提交时统一拦截；
- 列方向父子结构与列分组表头属第二阶段，本文件不引入任何列层级概念。
"""
import json
from datetime import datetime

from django.db import transaction

from libs.tenant_utils import apply_tenant_filter

from apps.equipment_lifecycle.ledger_services import (
    LEDGER_CHOICE_ABNORMAL,
    LedgerValidationError,
    generate_ledger_no,
    get_active_template,
    get_systems_for_user,
    parse_datetime_value,
    validate_item_value,
)
from apps.equipment_lifecycle.models import (
    ITEM_RESULT_ABNORMAL,
    ITEM_RESULT_NORMAL,
    ITEM_RESULT_UNSET,
    ITEM_RESULT_VALUES,
    LEDGER_FROM_TEMPLATE,
    LEDGER_ROW_MAX_LEVEL,
    LEDGER_STATUS_DRAFT,
    ROW_NODE_TYPE_CHECK,
    ROW_NODE_TYPE_REPEAT_GROUP,
    ROW_NODE_TYPE_VALUES,
    ROW_PATH_SEPARATOR,
    ENTRY_CHANNEL_WEB,
    OperationLedger,
    OperationLedgerItem,
    OperationLedgerRowInstance,
    OperationLedgerRowTemplateNode,
)


# ======================================================================
# 行模板节点：树构建与校验
# ======================================================================

def validate_row_headers(raw):
    """行层级表头名称校验：空 → ''；否则必须为非空字符串数组（≤最大层级）。

    层级由数组顺序派生（第 1 项为第 1 级），不信任前端提交的 level 编号；
    返回规范化后的 JSON 存储串。
    """
    if raw in (None, ''):
        return ''
    if not isinstance(raw, list) \
            or any(not isinstance(x, str) or not x.strip() for x in raw):
        raise LedgerValidationError('行层级表头必须为非空字符串数组')
    if len(raw) > LEDGER_ROW_MAX_LEVEL:
        raise LedgerValidationError(
            '行层级表头最多支持 %d 级' % LEDGER_ROW_MAX_LEVEL)
    return json.dumps([x.strip() for x in raw], ensure_ascii=False)


def load_template_nodes(template, only_active=False):
    """加载模板全部（或仅启用）行节点，按显示顺序排列。"""
    nodes = list(template.row_nodes.order_by('display_order', 'id'))
    if only_active:
        nodes = [n for n in nodes if n.is_active]
    return nodes


def build_node_tree(nodes):
    """节点列表 → 树视图（level/path/is_leaf/children_count/children）。"""
    by_parent = {}
    for node in nodes:
        by_parent.setdefault(node.parent_id, []).append(node)

    def walk(parent_id, level, prefix):
        rows = []
        for node in by_parent.get(parent_id, []):
            path = '%s%s%s' % (prefix, ROW_PATH_SEPARATOR, node.name) if prefix else node.name
            children = walk(node.id, level + 1, path)
            view = node.to_view()
            view.update(level=level, path=path, is_leaf=not children,
                        children_count=len(children), children=children)
            rows.append(view)
        return rows

    return walk(None, 1, '')


def _node_level(parent):
    """父节点所在层级（其祖先数 + 1）；根为 0 表示新节点将是第 1 级。"""
    level = 0
    current = parent
    seen = set()
    while current is not None and current.id not in seen:
        seen.add(current.id)
        level += 1
        current = current.parent
    return level


def _validate_node_parent(template, node, parent_id):
    """校验父节点：同模板、非自身、无循环；返回父节点或 None。"""
    if parent_id in (None, ''):
        return None
    parent = template.row_nodes.filter(pk=parent_id).first()
    if parent is None:
        raise LedgerValidationError('父节点不存在或不属于当前模板')
    if node is not None and parent.id == node.id:
        raise LedgerValidationError('父节点不能是节点自身')
    # 循环引用：从新父节点向上走不应遇到自身（同时兜底父链自环）
    seen = set()
    current = parent
    while current is not None and current.id not in seen:
        if node is not None and current.id == node.id:
            raise LedgerValidationError('行节点不能形成循环引用')
        seen.add(current.id)
        current = current.parent
    return parent


def _subtree_max_depth(children):
    """子树最大深度（子节点层算 1 层）。children 为节点可迭代。"""
    max_depth = 0
    for child in children:
        max_depth = max(max_depth, 1 + _subtree_max_depth(child.children.all()))
    return max_depth


def _check_depth(parent, subtree_children):
    """父节点层级 + 子树深度不得超过最大层级。"""
    parent_level = _node_level(parent)
    if parent_level + 1 + _subtree_max_depth(subtree_children) > LEDGER_ROW_MAX_LEVEL:
        raise LedgerValidationError(
            '行节点最多支持 %d 级（当前父节点为第 %d 级）' % (LEDGER_ROW_MAX_LEVEL, parent_level + 1))


def validate_node_fields(template, body, node=None):
    """行节点字段校验，返回字段 dict（is_repeatable 由类型派生）。"""
    name = str(body.get('name') or '').strip()
    if not name:
        raise LedgerValidationError('行节点名称不能为空')
    node_type = body.get('node_type')
    if node_type not in ROW_NODE_TYPE_VALUES:
        raise LedgerValidationError('行节点类型不合法：%s' % node_type)
    display_order = body.get('display_order')
    if not isinstance(display_order, int):
        display_order = node.display_order if node is not None else 0
    return {
        'name': name[:100],
        'node_type': node_type,
        'display_order': display_order,
        'is_repeatable': node_type == ROW_NODE_TYPE_REPEAT_GROUP,
    }


@transaction.atomic
def create_row_node(user, template, body):
    """新增行节点：层级/父节点/类型规则校验后落库，缺省编码自动补齐。"""
    fields = validate_node_fields(template, body)
    parent = _validate_node_parent(template, None, body.get('parent'))
    if parent is not None and parent.node_type == ROW_NODE_TYPE_CHECK:
        raise LedgerValidationError('行对象（check）节点不能包含子节点，请先将其改为行分组')
    _check_depth(parent, [])
    node = OperationLedgerRowTemplateNode(
        template=template, parent=parent, tenant_id=user.tenant_id,
        created_by=user, row_code=str(body.get('row_code') or '').strip(), **fields)
    node.save()
    if not node.row_code:
        node.row_code = 'RN%s' % node.id
        node.save(update_fields=['row_code'])
    return node


@transaction.atomic
def update_row_node(user, template, node, body):
    """编辑行节点：名称/类型/顺序/父级；改类型与移动需满足层级与类型规则。"""
    fields = validate_node_fields(template, body, node=node)
    if fields['node_type'] == ROW_NODE_TYPE_CHECK and node.children.exists():
        raise LedgerValidationError('该节点存在子节点，不能设置为行对象（check）')
    if 'parent' in body:
        parent = _validate_node_parent(template, node, body.get('parent'))
        if parent is not None:
            if parent.node_type == ROW_NODE_TYPE_CHECK:
                raise LedgerValidationError('行对象（check）节点不能包含子节点，请先将其改为行分组')
            _check_depth(parent, node.children.all())
        node.parent = parent
    for key, value in fields.items():
        setattr(node, key, value)
    node.updated_by = user
    node.save()
    return node


@transaction.atomic
def set_row_node_active(user, template, node, is_active):
    """停用/启用行节点：停用节点不参与实例生成与预览。"""
    node.is_active = bool(is_active)
    node.updated_by = user
    node.save(update_fields=['is_active', 'updated_at', 'updated_by'])
    return node


@transaction.atomic
def sort_row_nodes(user, template, body):
    """同级排序：ordered_ids 顺序即 display_order 顺序（只调整给出的节点）。"""
    parent_id = body.get('parent')
    ordered_ids = body.get('ordered_ids')
    if not isinstance(ordered_ids, list) or not ordered_ids:
        raise LedgerValidationError('ordered_ids 不能为空')
    if not all(str(x).isdigit() for x in ordered_ids):
        raise LedgerValidationError('ordered_ids 必须为节点 ID 数组')
    normalized_parent = int(parent_id) if str(parent_id or '').isdigit() else None
    nodes = template.row_nodes.filter(pk__in=ordered_ids)
    if nodes.count() != len(set(ordered_ids)):
        raise LedgerValidationError('行节点不存在或不属于当前模板')
    for node in nodes:
        if node.parent_id != normalized_parent:
            raise LedgerValidationError('仅允许对同一父节点下的兄弟节点排序')
    for index, node_id in enumerate(ordered_ids):
        template.row_nodes.filter(pk=node_id).update(display_order=index)
    return True


@transaction.atomic
def create_template_row_nodes(user, template, payload):
    """模板创建时随表头一次性写入嵌套行节点树（[{...children: [...]}]）。"""
    if not isinstance(payload, list):
        raise LedgerValidationError('row_nodes 必须为数组')
    created = []
    for index, raw in enumerate(payload):
        if not isinstance(raw, dict):
            raise LedgerValidationError('行节点格式不正确')
        body = dict(raw)
        body.setdefault('display_order', index)
        node = create_row_node(user, template, body)
        created.append(node)
        children = body.get('children') or []
        if children:
            if node.node_type == ROW_NODE_TYPE_CHECK:
                raise LedgerValidationError('行对象（check）节点不能包含子节点：%s' % node.name)
            for child_index, child in enumerate(children):
                if not isinstance(child, dict):
                    raise LedgerValidationError('行节点格式不正确')
                child_body = dict(child)
                child_body['parent'] = node.id
                child_body.setdefault('display_order', child_index)
                created.extend(create_template_row_nodes(user, template, [child_body]))
    return created


# ======================================================================
# 行实例与矩阵单元格
# ======================================================================

def get_matrix_template(ledger):
    """矩阵台账的来源模板（实例管理依赖；历史台账无模板则明确报错）。"""
    if ledger.template_id is None:
        raise LedgerValidationError('历史台账未关联模板，不能管理行实例')
    return ledger.template


def template_columns(template):
    """启用的列项目（列方向第一阶段为平面结构；周月维护不再按周期过滤项目）。"""
    return list(template.items.filter(is_active=True).order_by('display_order', 'id'))


def load_instance_tree(ledger):
    """台账行实例树视图（path/level 来自存储快照；is_leaf 按子实例判定）。"""
    instances = list(ledger.row_instances.order_by('display_order', 'id'))
    child_map = {}
    for instance in instances:
        child_map.setdefault(instance.parent_instance_id, []).append(instance)

    def walk(parent_id):
        rows = []
        for instance in child_map.get(parent_id, []):
            children = walk(instance.id)
            view = instance.to_view()
            view.update(is_leaf=not children, children_count=len(children), children=children)
            rows.append(view)
        return rows

    return walk(None)


def build_row_headers_map(ledger):
    """行实例 id → 祖先链 row_headers（[{level, name, code}]，根为第 1 级）。

    供台账明细响应逐单元格携带：前端按 row_headers[0..4] 渲染行层级列；
    祖先链由真实父子外键回溯组装，不从路径文本拆分（实例名可能包含分隔符）。
    """
    instances = {i.id: i for i in ledger.row_instances.all()}
    headers_map = {}
    for instance_id, instance in instances.items():
        chain = []
        current = instance
        while current is not None:
            chain.append(current)
            current = instances.get(current.parent_instance_id)
        chain.reverse()
        headers_map[instance_id] = [
            {'level': index + 1, 'name': node.instance_name, 'code': node.instance_code}
            for index, node in enumerate(chain)]
    return headers_map


def _instantiate_subtree(ledger, node, parent_instance, name=None, order=0, created=None):
    """按模板子结构实例化节点及其全部启用子节点（各 1 个实例）。

    返回本节点对应的实例；全部实例追加进 created。
    """
    created = [] if created is None else created
    level = parent_instance.row_level_snapshot + 1 if parent_instance else 1
    if level > LEDGER_ROW_MAX_LEVEL:
        raise LedgerValidationError('行实例最多支持 %d 级' % LEDGER_ROW_MAX_LEVEL)
    prefix = parent_instance.row_path_snapshot if parent_instance else ''
    display = name or node.name
    path = '%s%s%s' % (prefix, ROW_PATH_SEPARATOR, display) if prefix else display
    instance = OperationLedgerRowInstance(
        ledger=ledger, template_node=node, parent_instance=parent_instance,
        instance_name=display[:100], row_path_snapshot=path[:500],
        row_level_snapshot=level, display_order=order, tenant_id=ledger.tenant_id)
    instance.save()
    if not instance.instance_code:
        instance.instance_code = 'I%s' % instance.id
        instance.save(update_fields=['instance_code'])
    created.append(instance)
    child_order = 0
    for child in node.children.filter(is_active=True).order_by('display_order', 'id'):
        _instantiate_subtree(ledger, child, instance, None, child_order, created)
        child_order += 1
    return instance


def _is_leaf_instance(instance):
    """行叶子实例：没有子实例（用于展示树折叠判断）。"""
    return not instance.children.exists()


def _cell_leaf_instances(template, instances):
    """参与单元格生成的行实例：行对象（check）叶子（check 不能有子节点，
    故必为叶子）；group/repeat_group 自身不直接生成单元格。"""
    types = dict(template.row_nodes.filter(
        pk__in=[i.template_node_id for i in instances if i.template_node_id])
        .values_list('id', 'node_type'))
    return [i for i in instances
            if types.get(i.template_node_id) == ROW_NODE_TYPE_CHECK]


def _generate_cells(ledger, template, system, leaf_instances, columns, order_start=0):
    """行叶子实例 × 列项目 → 未填写单元格（全量快照，生成后不受模板修改影响）。"""
    cells = []
    for leaf_index, instance in enumerate(leaf_instances):
        for column_index, item in enumerate(columns):
            cells.append(OperationLedgerItem(
                ledger=ledger, system=system, tenant_id=ledger.tenant_id,
                system_code_snapshot=system.system_code,
                system_name_snapshot=system.name,
                system_location_snapshot=system.install_location,
                row_instance=instance,
                row_path_snapshot=instance.row_path_snapshot,
                row_level_snapshot=instance.row_level_snapshot,
                row_code_snapshot=instance.instance_code,
                template_item=item,
                template_name_snapshot=template.name,
                item_name_snapshot=item.name,
                column_name_snapshot=item.name,
                column_code_snapshot=str(item.id),
                cell_code_snapshot='%s:%s' % (instance.instance_code, item.id),
                input_type=item.input_type,
                unit_snapshot=item.unit,
                choices_snapshot=json.dumps(item.get_choices(), ensure_ascii=False),
                is_required=item.is_required,
                operation_guide_snapshot=item.operation_guide,
                abnormal_rule_snapshot=item.abnormal_rule,
                value_text='', value_number=None, value_bool=None,
                result=ITEM_RESULT_UNSET,
                is_temporary=False,
                display_order=(order_start + leaf_index) * 1000 + column_index,
            ))
    return cells


def _parse_row_spec(template, raw, parent_node=None):
    """递归解析行实例规格：{template_node, name?, children?}。"""
    node = template.row_nodes.filter(pk=raw.get('template_node'), is_active=True).first()
    if node is None:
        raise LedgerValidationError('行实例模板节点不存在或已停用')
    if parent_node is None:
        if node.parent_id is not None:
            raise LedgerValidationError('根级行实例必须对应模板根节点')
    elif node.parent_id != parent_node.id:
        raise LedgerValidationError('行实例父级与模板结构不一致：%s' % node.name)
    children_payload = raw.get('children') or []
    if children_payload and node.node_type == ROW_NODE_TYPE_CHECK:
        raise LedgerValidationError('行对象（check）节点不能包含子实例：%s' % node.name)
    return {
        'node': node,
        'name': str(raw.get('name') or '').strip()[:100] or node.name,
        'children': [_parse_row_spec(template, child, node) for child in children_payload
                     if isinstance(child, dict)],
    }


def _default_row_specs(template):
    """未显式给出实例规格时：每个启用根节点生成 1 个实例。"""
    return [{'node': node, 'name': node.name, 'children': []}
            for node in template.row_nodes.filter(parent__isnull=True, is_active=True)
            .order_by('display_order', 'id')]


def _instantiate_specs(ledger, specs, parent_instance=None, created=None):
    """按实例规格树实例化（嵌套 children 按序挂到对应实例之下）。"""
    created = [] if created is None else created
    for order, spec in enumerate(specs):
        instance = _instantiate_subtree(
            ledger, spec['node'], parent_instance, spec['name'], order, created)
        _instantiate_spec_children(ledger, instance, spec['children'], created)
    return created


def _instantiate_spec_children(ledger, parent_instance, child_specs, created):
    for order, child in enumerate(child_specs):
        instance = _instantiate_subtree(
            ledger, child['node'], parent_instance, child['name'], order, created)
        _instantiate_spec_children(ledger, instance, child['children'], created)


def _matrix_system(ledger):
    """矩阵台账唯一归属系统（创建时写入全部单元格，取任一单元格即可）。"""
    first = ledger.items.select_related('system').first()
    if first is None:
        raise LedgerValidationError('台账没有可归属的系统明细')
    return first.system


def _resolve_matrix_template(user, header, template_id):
    """矩阵创建：校验模板（启用、类型匹配、已配置行结构与列项目）。"""
    template = get_active_template(user, template_id, header['ledger_type'])
    if not template.row_nodes.filter(is_active=True).exists():
        raise LedgerValidationError('模板未配置行结构，不能生成矩阵台账（旧模板已停用）')
    columns = template_columns(template)
    if not columns:
        raise LedgerValidationError('模板没有启用的列项目')
    return template, columns


def _resolve_matrix_specs(template, specs_payload):
    """矩阵创建：解析行实例规格（缺省每个启用根节点 1 个实例）。"""
    if isinstance(specs_payload, list) and specs_payload:
        specs = [_parse_row_spec(template, raw) for raw in specs_payload
                 if isinstance(raw, dict)]
        if not specs:
            raise LedgerValidationError('行实例规格不正确')
        return specs
    return _default_row_specs(template)


@transaction.atomic
def create_matrix_ledger(user, body):
    """矩阵台账创建：行实例树 + 全部单元格一次写入（任一校验失败整体回滚）。

    载荷：表头字段 + system_id（单一系统，按系统拆分立账语义不变）+
    template_id + row_instances（可重复分组实例规格，缺省每根节点 1 实例）。
    返回 (ledger, None) 或 (None, error_message)。
    """
    from apps.equipment_lifecycle.ledger_services import _parse_header_payload

    try:
        header = _parse_header_payload(user, body)
    except LedgerValidationError as e:
        return None, str(e)
    client_token = header.pop('client_token', '')
    if client_token:
        exists = apply_tenant_filter(OperationLedger.objects.all(), user).filter(
            client_token=client_token).first()
        if exists:
            return exists, None
    template_id = body.get('template_id')
    if not template_id:
        return None, '请选择台账模板'
    try:
        template, columns = _resolve_matrix_template(user, header, template_id)
        systems_map = get_systems_for_user(user, [body.get('system_id')])
        system = systems_map.get(int(body['system_id']))
        if system is None:
            return None, '请选择系统'
        specs = _resolve_matrix_specs(template, body.get('row_instances'))
        ledger = OperationLedger(
            tenant_id=user.tenant_id, status=LEDGER_STATUS_DRAFT,
            entry_channel=ENTRY_CHANNEL_WEB, created_from=LEDGER_FROM_TEMPLATE,
            template=template, created_by=user,
            row_headers_snapshot=template.row_headers, **header)
        ledger.ledger_no = generate_ledger_no(user.tenant_id, ledger.ledger_type,
                                              ledger.executed_date)
        ledger.client_token = client_token
        ledger.save()
        instances = _instantiate_specs(ledger, specs)
        leaves = _cell_leaf_instances(template, instances)
        if not leaves:
            raise LedgerValidationError('模板行结构没有可生成单元格的行对象（行对象节点）')
        cells = _generate_cells(ledger, template, system, leaves, columns)
        _apply_prefilled_values(cells, body.get('values'))
        OperationLedgerItem.objects.bulk_create(cells)
    except LedgerValidationError as e:
        return None, str(e)
    except (TypeError, ValueError):
        return None, '请选择系统'
    return ledger, None


def _apply_prefilled_values(cells, values_payload):
    """创建时的预填值：按（行路径快照, 列项目 ID）匹配本次生成的单元格。

    前端矩阵填写后随创建载荷提交 values: [{path, column_id, ...填写字段}]；
    未匹配到生成单元格时显式报错（不静默丢弃填写内容）。
    """
    if not values_payload:
        return
    if not isinstance(values_payload, list):
        raise LedgerValidationError('values 必须为数组')
    cell_map = {(c.row_path_snapshot, c.template_item_id): c for c in cells}
    for row in values_payload:
        if not isinstance(row, dict):
            raise LedgerValidationError('单元格填写值格式不正确')
        key = (str(row.get('path') or ''), row.get('column_id'))
        cell = cell_map.get(key)
        if cell is None:
            raise LedgerValidationError('单元格不存在或不在本次台账范围内：%s' % (key[0] or '-',))
        _apply_cell_fields(cell, row)


@transaction.atomic
def add_row_instance(user, ledger, body):
    """新增行实例（可重复分组）：级联实例化子树并补生成对应单元格。"""
    template = get_matrix_template(ledger)
    node = template.row_nodes.filter(pk=body.get('template_node'), is_active=True).first()
    if node is None:
        raise LedgerValidationError('行模板节点不存在或已停用')
    if node.node_type != ROW_NODE_TYPE_REPEAT_GROUP:
        raise LedgerValidationError('只有可重复分组的行节点可以创建多个实例')
    parent_instance = _resolve_parent_instance(ledger, node, body.get('parent_instance'))
    name = str(body.get('name') or '').strip()
    if not name:
        raise LedgerValidationError('请填写实例名称（如"第2信道"）')
    columns = template_columns(template)
    if not columns:
        raise LedgerValidationError('模板没有启用的列项目')
    system = _matrix_system(ledger)
    max_order = ledger.row_instances.filter(
        parent_instance=parent_instance).order_by('-display_order'
                                                  ).values_list('display_order', flat=True).first()
    created = []
    _instantiate_subtree(ledger, node, parent_instance, name, (max_order or 0) + 1, created)
    leaves = _cell_leaf_instances(template, created)
    order_start = ledger.items.count() // max(len(columns), 1)
    OperationLedgerItem.objects.bulk_create(
        _generate_cells(ledger, template, system, leaves, columns, order_start))
    ledger.version += 1
    ledger.save(update_fields=['version'])
    return created


def _resolve_parent_instance(ledger, node, parent_id):
    """解析新增实例的父实例：根级不传；否则必须属于本台账且节点匹配。"""
    if not parent_id:
        if node.parent_id is not None:
            raise LedgerValidationError('该行节点不是模板根节点，请指定父行实例')
        return None
    parent_instance = ledger.row_instances.filter(pk=parent_id).first()
    if parent_instance is None:
        raise LedgerValidationError('父行实例不存在')
    if node.parent_id != parent_instance.template_node_id:
        raise LedgerValidationError('新增行实例的父级与模板结构不一致')
    return parent_instance


@transaction.atomic
def rename_row_instance(user, ledger, instance, name):
    """重命名行实例：同步刷新自身与子树路径快照及其单元格行路径。"""
    name = str(name or '').strip()
    if not name:
        raise LedgerValidationError('实例名称不能为空')
    instance.instance_name = name[:100]
    affected_leaves = _refresh_instance_paths(instance)
    instance.save(update_fields=['instance_name', 'row_path_snapshot'])
    for leaf in affected_leaves:
        OperationLedgerItem.objects.filter(row_instance=leaf, ledger=ledger).update(
            row_path_snapshot=leaf.row_path_snapshot)
    ledger.version += 1
    ledger.save(update_fields=['version'])
    return instance


def _refresh_instance_paths(instance):
    """递归重算实例自身及子树的路径快照，返回受影响的行叶子实例列表。"""
    parent = instance.parent_instance
    prefix = parent.row_path_snapshot if parent else ''
    instance.row_path_snapshot = (
        '%s%s%s' % (prefix, ROW_PATH_SEPARATOR, instance.instance_name)
        if prefix else instance.instance_name)
    affected = []
    for child in instance.children.all():
        affected.extend(_refresh_instance_paths(child))
        child.save(update_fields=['row_path_snapshot', 'row_level_snapshot'])
    if not instance.children.exists():
        affected.append(instance)
    return affected


@transaction.atomic
def delete_row_instance(user, ledger, instance):
    """删除行实例：级联删除子树实例与对应单元格；同一节点至少保留一个实例。"""
    if instance.template_node_id is not None:
        has_sibling = ledger.row_instances.filter(
            template_node_id=instance.template_node_id).exclude(pk=instance.pk).exists()
        if not has_sibling:
            raise LedgerValidationError(
                '可重复分组至少保留一个实例（%s）' % instance.instance_name)
    instance.delete()  # 子树实例与单元格由外键级联删除
    ledger.version += 1
    ledger.save(update_fields=['version'])
    return True


# ======================================================================
# 单元格填写与结果规则
# ======================================================================

def _cell_value_empty(item):
    """单元格是否未填写值（多选空数组视为未填写）。"""
    if item.value_number is not None or item.value_bool is not None:
        return False
    if item.input_type == 'multi_choice':
        return not item.get_value_list()
    return not str(item.value_text or '').strip()


def resolve_cell_result(item, explicit_result):
    """单元格结果：显式提交优先；有值按填写值派生（不正常→异常）；
    无值保持"未填写"——未填写不会被自动转换为正常。"""
    if explicit_result:
        if explicit_result not in ITEM_RESULT_VALUES:
            raise LedgerValidationError('结果不合法：%s' % explicit_result)
        return explicit_result
    if not _cell_value_empty(item):
        if item.input_type == 'choice' and str(item.value_text) == LEDGER_CHOICE_ABNORMAL:
            return ITEM_RESULT_ABNORMAL
        return ITEM_RESULT_NORMAL
    return ITEM_RESULT_UNSET


def apply_cell_edit(item, row):
    """编辑矩阵单元格：仅填写值/结果类字段；必填校验延迟到提交统一执行。"""
    _apply_cell_fields(item, row)
    item.save()
    return item


def _apply_cell_fields(item, row):
    """在内存中应用单元格填写值/结果类字段（不落库；创建预填复用）。"""
    payload = {
        'value_text': row.get('value_text', item.value_text),
        'value_number': row.get('value_number', item.value_number),
        'value_bool': row.get('value_bool', item.value_bool),
        'is_required': False,
        'choices': item.get_choices(),
    }
    value_text, value_number, value_bool = validate_item_value(item.input_type, payload)
    item.value_text, item.value_number, item.value_bool = value_text, value_number, value_bool
    item.result = resolve_cell_result(item, row.get('result'))
    if 'abnormal_desc' in row:
        item.abnormal_desc = str(row.get('abnormal_desc') or '').strip()
    if 'na_reason' in row:
        item.na_reason = str(row.get('na_reason') or '').strip()
    if 'onsite_action' in row:
        item.onsite_action = str(row.get('onsite_action') or '').strip()
    if 'executor_name' in row:
        item.executor_name = str(row.get('executor_name') or '').strip()
    if 'executed_at' in row:
        item.executed_at = parse_datetime_value(
            row.get('executed_at'), '明细实际执行时间', allow_empty=True)
    return item


def _apply_matrix_header_edits(ledger, body):
    """矩阵单元格编辑接口携带的可选表头字段。"""
    if 'executed_date' in body:
        raw = str(body['executed_date'] or '').strip()
        if not raw:
            raise LedgerValidationError('请填写实际执行日期')
        try:
            ledger.executed_date = datetime.strptime(raw[:10], '%Y-%m-%d').date()
        except ValueError:
            raise LedgerValidationError('实际执行日期格式不正确')
    if 'executor_names' in body:
        ledger.executor_names = str(body['executor_names']).strip()
    if 'executed_start' in body:
        ledger.executed_start = parse_datetime_value(
            body['executed_start'], '实际执行开始时间', allow_empty=True)
    if 'executed_end' in body:
        ledger.executed_end = parse_datetime_value(
            body['executed_end'], '实际执行结束时间', allow_empty=True)


@transaction.atomic
def edit_matrix_cells(user, ledger, body):
    """矩阵台账单元格批量编辑（仅更新，无删除语义）+ 可选表头字段更新。

    载荷：{version?, executed_date?/executor_names?/executed_start?/executed_end?,
    values: [{id, value_text?/value_number?/value_bool?/result?/abnormal_desc?...}]}
    """
    from apps.equipment_lifecycle.ledger_services import _validate_expected_version

    error = _validate_expected_version(ledger, body.get('version'))
    if error:
        raise LedgerValidationError(error)
    values = body.get('values')
    if not isinstance(values, list) or not values:
        raise LedgerValidationError('请提交需要更新的单元格')
    wanted_ids = [row.get('id') for row in values if isinstance(row, dict) and row.get('id')]
    cells = {c.id: c for c in ledger.items.filter(
        row_instance__isnull=False, pk__in=wanted_ids)}
    for row in values:
        if not isinstance(row, dict) or not row.get('id'):
            raise LedgerValidationError('单元格格式不正确')
        cell = cells.get(row['id'])
        if cell is None:
            raise LedgerValidationError('台账单元格不存在或已移除')
        apply_cell_edit(cell, row)
    _apply_matrix_header_edits(ledger, body)
    ledger.version += 1
    ledger.save(update_fields=['version', 'executed_date', 'executor_names',
                               'executed_start', 'executed_end'])
    return True


def validate_matrix_submit(ledger):
    """矩阵台账提交校验：必填单元格未填写（含仅一键正常的空值格）不能提交。"""
    cells = ledger.items.filter(row_instance__isnull=False, is_required=True)
    missing = [c for c in cells
               if _cell_value_empty(c) and c.result in ('', ITEM_RESULT_NORMAL)]
    if missing:
        preview = '、'.join(
            '%s[%s]' % (c.row_path_snapshot or '-', c.item_name_snapshot)
            for c in missing[:3])
        return '还有 %d 个必填单元格未填写，不能提交：%s' % (len(missing), preview)
    return None


@transaction.atomic
def confirm_normal_matrix(ledger, item_ids):
    """矩阵台账一键正常：仅允许作用于未填写单元格，不改已有异常结果。"""
    cells = list(ledger.items.filter(pk__in=item_ids, row_instance__isnull=False))
    if len(cells) != len(set(item_ids)):
        raise LedgerValidationError('台账单元格不存在或已移除')
    not_unset = [c for c in cells if c.result != ITEM_RESULT_UNSET]
    if not_unset:
        raise LedgerValidationError('一键正常只能作用于未填写的单元格')
    for cell in cells:
        cell.result = ITEM_RESULT_NORMAL
        cell.save(update_fields=['result'])
    return len(cells)
