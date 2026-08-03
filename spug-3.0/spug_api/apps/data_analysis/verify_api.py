"""直接调用服务层验证数据查询正确性。"""
import json
from apps.account.models import User
from apps.data_analysis.services.overview import get_overview
from apps.data_analysis.services.fault import get_fault_analysis
from apps.data_analysis.services.interference import get_interference_analysis
from apps.data_analysis.services.device import get_device_analysis
from apps.data_analysis.services.upgrade import get_upgrade_analysis
import datetime

u = User.objects.filter(is_supper=True).first()
if not u:
    print("No super user found")
else:
    print(f"Testing as: {u.username}")
    start = datetime.date.today() - datetime.timedelta(days=364)
    end = datetime.date.today()

    tests = [
        ("overview", get_overview),
        ("fault", get_fault_analysis),
        ("interference", get_interference_analysis),
        ("device", get_device_analysis),
        ("upgrade", get_upgrade_analysis),
    ]

    for name, func in tests:
        try:
            data = func(u, start, end)
            print(f"\n=== {name} ===")
            print(f"  keys: {list(data.keys())}")
            print(f"  summary: {json.dumps(data.get('summary', {}), ensure_ascii=False)}")
            trends = data.get('trends', {})
            for tk, tv in trends.items():
                print(f"  trend {tk}: {len(tv)} months")
            dist = data.get('distributions', {})
            for dk, dv in dist.items():
                print(f"  dist {dk}: {len(dv)} items")
        except Exception as e:
            print(f"\n=== {name} ERROR: {e} ===")
            import traceback
            traceback.print_exc()
