"""统一分页工具。

用法：
    from libs.pagination import paginate, paginate_response

    page, page_size = paginate(request)
    data = paginate_response(qs, page, page_size, serialize_fn=lambda x: x.to_view())
    return json_response(data)

返回结构：
    {"total": 100, "page": 1, "page_size": 20, "items": [...]}
"""
from django.http import HttpRequest


def paginate(request: HttpRequest, default_page_size: int = 20, max_page_size: int = 200):
    """从 request.GET 解析分页参数。

    Args:
        request: Django HTTP 请求对象
        default_page_size: 默认每页条数
        max_page_size: 每页最大条数（防止恶意超大请求）

    Returns:
        (page, page_size) 两个 int
    """
    try:
        page = max(int(request.GET.get('page', 1)), 1)
    except (TypeError, ValueError):
        page = 1
    try:
        page_size = int(request.GET.get('page_size', default_page_size))
    except (TypeError, ValueError):
        page_size = default_page_size
    page_size = min(max(page_size, 1), max_page_size)
    return page, page_size


def paginate_response(qs, page: int, page_size: int, serialize_fn=None, items_key='items'):
    """分页查询 + 序列化，返回标准响应字典。

    Args:
        qs: Django QuerySet（已过滤、已排序）
        page: 当前页码（从 1 开始）
        page_size: 每页条数
        serialize_fn: 序列化函数，默认 lambda x: x.to_dict()
        items_key: 返回字典中列表的键名，默认 'items'

    Returns:
        dict: {"total": int, "page": int, "page_size": int, items_key: list}
    """
    if serialize_fn is None:
        serialize_fn = lambda x: x.to_dict()  # noqa: E731

    total = qs.count()
    offset = (page - 1) * page_size
    items = [serialize_fn(x) for x in qs[offset:offset + page_size]]

    return {
        'total': total,
        'page': page,
        'page_size': page_size,
        items_key: items,
    }
