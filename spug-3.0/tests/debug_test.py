from apps.exec.models import UpgradeRecord
from apps.account.models import User

# 清理测试数据
UpgradeRecord.objects.filter(
    tenant_id='test_tenant',
    upgrade_no='UPG001'
).delete()

# 创建测试用户
user, _ = User.objects.get_or_create(
    username='testuser',
    defaults={
        'nickname': '测试用户',
        'password_hash': User.make_password('password123'),
        'tenant_id': 'test_tenant'
    }
)

# 完全按照测试代码执行
print('执行测试代码...')
try:
    r1 = UpgradeRecord.objects.create(
        tenant_id='test_tenant',
        upgrade_no='UPG001',
        system='系统A',
        upgrade_type='主版本升级',
        version='2.0.0',
        plan_time='2024-01-20',
        owner='张三',
        checklist='[]',
        dependencies='[]',
        issues='[]',
        created_by=user
    )
    print(f'第一条记录创建成功: ID={r1.id}')

    r2 = UpgradeRecord.objects.create(
        tenant_id='test_tenant',
        upgrade_no='UPG001',
        system='系统B',
        upgrade_type='主版本升级',
        version='3.0.0',
        plan_time='2024-01-21',
        owner='李四',
        checklist='[]',
        dependencies='[]',
        issues='[]',
        created_by=user
    )
    print(f'第二条记录创建成功: ID={r2.id}')
    print('✗ 问题：没有抛出异常！')
except Exception as e:
    print(f'✓ 正确抛出异常: {type(e).__name__}: {e}')

# 清理
UpgradeRecord.objects.filter(upgrade_no='UPG001').delete()
