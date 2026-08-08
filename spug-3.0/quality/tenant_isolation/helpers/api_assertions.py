"""API 断言辅助 - 请求发送、响应解析、跨租户断言"""
import json


def get_body(resp):
    """解析 HTTP 响应体为 JSON"""
    try:
        return resp.json()
    except Exception:
        return {'raw': resp.content[:200].decode('utf-8', 'ignore')}


def get_items(body):
    """从各种响应格式中提取列表项

    支持格式:
    - 纯列表 [item, ...]
    - {'data': [item, ...]}
    - {'data': {'data': [item, ...]}}
    - {'items': [...]}
    - {'records': [...]}
    - {'list': [...]}
    """
    if isinstance(body, list):
        return body
    if isinstance(body, dict):
        if body.get('error'):
            return []
        for key in ['data', 'items', 'records', 'list']:
            v = body.get(key)
            if isinstance(v, list):
                return v
            if isinstance(v, dict):
                for sub_key in ['data', 'items', 'records', 'list']:
                    if isinstance(v.get(sub_key), list):
                        return v[sub_key]
    return []


def assert_no_cross_tenant(items, target_prefix, field='title'):
    """断言列表中不包含其他租户的数据

    Args:
        items: 响应中的列表项
        target_prefix: 目标租户数据的命名前缀 (如 'NB_' 表示租户B导航)
        field: 检查的字段名

    Returns:
        (bool, str): (是否通过, 详情描述)
    """
    leaked = [i for i in items if target_prefix in str(i.get(field, ''))]
    if leaked:
        return False, f'发现 {len(leaked)} 条跨租户数据 (prefix={target_prefix})'
    return True, f'未发现跨租户数据 (共 {len(items)} 条)'


def assert_object_not_modified(obj, field, forbidden_value):
    """断言对象字段未被修改为禁止值

    Args:
        obj: Django 模型实例
        field: 字段名
        forbidden_value: 不应被设置的值

    Returns:
        (bool, str): (是否通过, 详情描述)
    """
    current = getattr(obj, field)
    if current == forbidden_value:
        return False, f'{field} 被修改为 {forbidden_value} (跨租户篡改成功)'
    return True, f'{field}={current} (未被修改)'


def assert_object_exists(model, pk, use_is_deleted=True):
    """断言对象仍存在（未被跨租户删除）

    Args:
        model: Django 模型类
        pk: 主键
        use_is_deleted: 是否检查 is_deleted 字段

    Returns:
        (bool, str): (是否通过, 详情描述)
    """
    if use_is_deleted:
        obj = model.objects.filter(pk=pk, is_deleted=False).first()
    else:
        obj = model.objects.filter(pk=pk).first()
    if obj is None:
        return False, f'对象 pk={pk} 已被删除 (跨租户删除成功)'
    return True, f'对象 pk={pk} 仍存在'
