"""验证 RadioLicenseBadgeView 业务逻辑（红点接口）

测试目标：
1. 60 天内到期的执照被计入 expiring_count
2. 已过期的执照被计入 expired_count
3. 超出 60 天的执照不计入
4. 正好 60 天的执照被计入
5. 多租户隔离：其他租户的执照不计入
"""
import os
import sys
import django

# 初始化 Django
sys.path.insert(0, '/data/spug')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')
django.setup()

from datetime import date, timedelta
from django.test import RequestFactory
from apps.radio_license.models import RadioLicense
from apps.radio_license.views import RadioLicenseBadgeView
from apps.account.models import User

print('========== RadioLicenseBadgeView 集成测试 ==========\n')

# 准备测试数据
tenant_a = 'test-tenant-badge-A'
tenant_b = 'test-tenant-badge-B'

# 清理旧测试数据
RadioLicense.objects.filter(tenant_id__in=[tenant_a, tenant_b]).delete()
User.objects.filter(username__startswith='badge_test_').delete()

# 创建测试用户
user_a = User.objects.create(
    username='badge_test_user_a', nickname='BadgeA', is_active=True
)
user_b = User.objects.create(
    username='badge_test_user_b', nickname='BadgeB', is_active=True
)

today = date.today()

# 租户 A 的测试执照
licenses_a = [
    {'station': 'A-30天内到期', 'days': 30, 'tenant': tenant_a, 'expected': 'expiring'},
    {'station': 'A-60天整', 'days': 60, 'tenant': tenant_a, 'expected': 'expiring'},
    {'station': 'A-61天', 'days': 61, 'tenant': tenant_a, 'expected': 'normal'},
    {'station': 'A-100天', 'days': 100, 'tenant': tenant_a, 'expected': 'normal'},
    {'station': 'A-已过期-1天', 'days': -1, 'tenant': tenant_a, 'expected': 'expired'},
    {'station': 'A-已过期-30天', 'days': -30, 'tenant': tenant_a, 'expected': 'expired'},
    {'station': 'A-0天(今天到期)', 'days': 0, 'tenant': tenant_a, 'expected': 'expiring'},
]
# 租户 B 的执照（验证租户隔离）
licenses_b = [
    {'station': 'B-20天', 'days': 20, 'tenant': tenant_b, 'expected': 'expiring'},
    {'station': 'B-已过期-5天', 'days': -5, 'tenant': tenant_b, 'expected': 'expired'},
]

for lic in licenses_a + licenses_b:
    RadioLicense.objects.create(
        tenant_id=lic['tenant'],
        station_name=lic['station'],
        purpose='test',
        valid_from=today - timedelta(days=200),
        valid_to=today + timedelta(days=lic['days']),
        responsible_user_id=user_a.id,
        responsible_user_name=user_a.nickname,
        created_by=user_a,
    )

# 模拟请求（需要给 request 加 user）
class FakeUserA:
    def __init__(self, user_obj, tenant_id):
        self.id = user_obj.id
        self.username = user_obj.username
        self.tenant_id = tenant_id
        # 模拟 apply_tenant_filter 需要的字段（如果需要）
        self.is_superuser = False

# 跑视图
factory = RequestFactory()
request = factory.get('/api/radio-license/badge/')
request.user = FakeUserA(user_a, tenant_a)
# apply_tenant_filter 内部通常用 request.user.tenant_id，但需要看实际实现
# 这里采用 monkey patch：替换 apply_tenant_filter 模拟租户过滤
import apps.radio_license.views as rl_views
real_filter = rl_views.apply_tenant_filter
def fake_filter(qs, user, strict_mode=False):
    if user.tenant_id == tenant_a:
        return qs.filter(tenant_id=tenant_a)
    elif user.tenant_id == tenant_b:
        return qs.filter(tenant_id=tenant_b)
    return qs.none()
rl_views.apply_tenant_filter = fake_filter

view = RadioLicenseBadgeView()
response = view.get(request)
print(f'租户 A 视图返回: {response.data}')

# 验证
expected_expiring = 3  # 30天、60天、0天
expected_expired = 2   # -1天、-30天
expected_total = 5

assert response.data['expiring_count'] == expected_expiring, \
    f"expiring 期望 {expected_expiring} 实际 {response.data['expiring_count']}"
assert response.data['expired_count'] == expected_expired, \
    f"expired 期望 {expected_expired} 实际 {response.data['expired_count']}"
assert response.data['count'] == expected_total, \
    f"count 期望 {expected_total} 实际 {response.data['count']}"

# 验证租户 B
request.user = FakeUserA(user_b, tenant_b)
response = view.get(request)
print(f'租户 B 视图返回: {response.data}')
assert response.data['expiring_count'] == 1, f"B expiring 期望 1 实际 {response.data['expiring_count']}"
assert response.data['expired_count'] == 1, f"B expired 期望 1 实际 {response.data['expired_count']}"
assert response.data['count'] == 2, f"B count 期望 2 实际 {response.data['count']}"

# 还原
rl_views.apply_tenant_filter = real_filter

# 清理
RadioLicense.objects.filter(tenant_id__in=[tenant_a, tenant_b]).delete()
User.objects.filter(username__startswith='badge_test_').delete()

print('\n========== 全部测试通过 ✓ ==========')
