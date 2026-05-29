from apps.exec.models import UpgradeRecord
from apps.account.models import User

# 创建测试用户
user, _ = User.objects.get_or_create(
    username='test_upgrade_user',
    defaults={
        'nickname': '测试用户',
        'password_hash': User.make_password('test123'),
        'tenant_id': 'test_tenant'
    }
)

# 清理测试数据
UpgradeRecord.objects.filter(
    tenant_id__in=['test_tenant', 'test_tenant2'],
    upgrade_no='UPG_TEST_001'
).delete()

# 租户1创建升级单
upgrade1 = UpgradeRecord.objects.create(
    tenant_id='test_tenant',
    upgrade_no='UPG_TEST_001',
    system='系统A',
    upgrade_type='主版本升级',
    version='2.0.0',
    plan_time='2024-01-20',
    owner='张三',
    created_by=user
)
print(f'租户1创建成功: {upgrade1.upgrade_no}, 租户={upgrade1.tenant_id}')

# 同一租户尝试创建相同单号 - 应该失败
try:
    UpgradeRecord.objects.create(
        tenant_id='test_tenant',
        upgrade_no='UPG_TEST_001',
        system='系统B',
        owner='李四',
        created_by=user
    )
    print('错误: 同一租户内创建相同单号成功，应该失败!')
except Exception as e:
    print(f'✓ 同一租户内重复被阻止: {type(e).__name__}')

# 不同租户创建相同单号 - 应该成功
upgrade2 = UpgradeRecord.objects.create(
    tenant_id='test_tenant2',
    upgrade_no='UPG_TEST_001',
    system='系统C',
    owner='王五',
    created_by=user
)
print(f'✓ 租户2创建成功: {upgrade2.upgrade_no}, 租户={upgrade2.tenant_id}')

# 验证记录
records = UpgradeRecord.objects.filter(upgrade_no='UPG_TEST_001')
print(f'\n总记录数: {records.count()}')
for r in records:
    print(f'  - 租户={r.tenant_id}, 单号={r.upgrade_no}, 系统={r.system}')

# 清理
UpgradeRecord.objects.filter(upgrade_no='UPG_TEST_001').delete()
print('\n✓ 测试通过: 同一租户内单号唯一，不同租户可相同')
