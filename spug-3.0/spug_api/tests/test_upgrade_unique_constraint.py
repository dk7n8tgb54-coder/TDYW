#!/usr/bin/env python3
"""
测试升级单号唯一约束验证脚本
验证：同一个租户下升级单号不能相同，不同租户下的升级单号可以相同
"""
import os
import sys
import django

# 设置 Django 环境
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')
django.setup()

from apps.exec.models import UpgradeRecord
from apps.account.models import User

def test_upgrade_unique_constraint():
    """测试升级单号唯一约束"""
    print("=" * 60)
    print("测试升级单号唯一约束")
    print("=" * 60)

    # 创建测试用户
    user, _ = User.objects.get_or_create(
        username='test_upgrade_user',
        defaults={
            'nickname': '测试用户',
            'password_hash': User.make_password('test123'),
            'tenant_id': 'test_tenant'
        }
    )

    print("\n1. 清理测试数据...")
    UpgradeRecord.objects.filter(
        tenant_id__in=['test_tenant', 'test_tenant2'],
        upgrade_no='UPG_TEST_001'
    ).delete()

    print("\n2. 租户1 (test_tenant) 创建升级单 UPG_TEST_001...")
    upgrade1 = UpgradeRecord.objects.create(
        tenant_id='test_tenant',
        upgrade_no='UPG_TEST_001',
        system='系统A',
        upgrade_type='主版本升级',
        version='2.0.0',
        plan_time='2024-01-20',
        status='待处理',
        owner='张三',
        checklist='[]',
        dependencies='[]',
        issues='[]',
        created_by=user
    )
    print(f"   ✓ 成功创建: ID={upgrade1.id}, 升级单号={upgrade1.upgrade_no}, 租户={upgrade1.tenant_id}")

    print("\n3. 同一租户 (test_tenant) 尝试创建相同升级单号 UPG_TEST_001...")
    try:
        UpgradeRecord.objects.create(
            tenant_id='test_tenant',
            upgrade_no='UPG_TEST_001',
            system='系统B',
            upgrade_type='主版本升级',
            version='3.0.0',
            plan_time='2024-01-21',
            owner='李四',
            created_by=user
        )
        print("   ✗ 错误：应该抛出异常，但创建成功了！")
        return False
    except Exception as e:
        print(f"   ✓ 正确抛出异常: {type(e).__name__}")
        print(f"      异常信息: {str(e)}")

    print("\n4. 不同租户 (test_tenant2) 尝试创建相同升级单号 UPG_TEST_001...")
    upgrade2 = UpgradeRecord.objects.create(
        tenant_id='test_tenant2',
        upgrade_no='UPG_TEST_001',
        system='系统C',
        upgrade_type='主版本升级',
        version='4.0.0',
        plan_time='2024-01-22',
        owner='王五',
        created_by=user
    )
    print(f"   ✓ 成功创建: ID={upgrade2.id}, 升级单号={upgrade2.upgrade_no}, 租户={upgrade2.tenant_id}")

    print("\n5. 验证数据库中的记录...")
    records = UpgradeRecord.objects.filter(upgrade_no='UPG_TEST_001').order_by('tenant_id')
    print(f"   找到 {records.count()} 条记录:")
    for record in records:
        print(f"   - ID={record.id}, 升级单号={record.upgrade_no}, 租户={record.tenant_id}, 系统={record.system}")

    print("\n6. 清理测试数据...")
    UpgradeRecord.objects.filter(
        tenant_id__in=['test_tenant', 'test_tenant2'],
        upgrade_no='UPG_TEST_001'
    ).delete()
    print("   ✓ 清理完成")

    print("\n" + "=" * 60)
    print("测试结果: ✓ 通过")
    print("  ✓ 同一租户内，升级单号不能重复")
    print("  ✓ 不同租户间，升级单号可以相同")
    print("=" * 60)
    return True

if __name__ == '__main__':
    success = test_upgrade_unique_constraint()
    sys.exit(0 if success else 1)
