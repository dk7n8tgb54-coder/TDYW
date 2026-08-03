"""数据分析视图。"""
from libs.decorators import auth
from libs.utils import json_response
from .services.common import parse_date_range
from .services.cache import get_cache_scope, cache_get, cache_set
from .services.overview import get_overview
from .services.fault import get_fault_analysis
from .services.interference import get_interference_analysis
from .services.device import get_device_analysis
from .services.upgrade import get_upgrade_analysis


def _make_view(perm, service_func, endpoint):
    """生成一个带权限校验 + 缓存的视图函数。"""

    @auth(perm)
    def view_func(request):
        start_date, end_date, error = parse_date_range(request)
        if error:
            return json_response(error=error)

        scope = get_cache_scope(request.user)
        cached = cache_get(endpoint, scope, start_date, end_date)
        if cached is not None:
            return json_response(cached)

        data = service_func(request.user, start_date, end_date)
        cache_set(endpoint, scope, start_date, end_date, data)
        return json_response(data)

    return view_func


overview_view = _make_view(
    'data_analysis.overview.view', get_overview, 'overview'
)
fault_view = _make_view(
    'data_analysis.fault.view', get_fault_analysis, 'fault'
)
interference_view = _make_view(
    'data_analysis.interference.view', get_interference_analysis, 'interference'
)
device_view = _make_view(
    'data_analysis.device.view', get_device_analysis, 'device'
)
upgrade_view = _make_view(
    'data_analysis.upgrade.view', get_upgrade_analysis, 'upgrade'
)
