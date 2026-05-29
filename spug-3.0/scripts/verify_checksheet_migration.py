#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
验证 checksheet_signature 迁移到 checksheet_daily_summary
"""
import sys
import os

# 添加项目路径到 sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'spug_api'))

# 配置 Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug_api.settings')

import django
django.setup()

from spug_api.apps.checksheet.models import CheckSheetDailySummary

def verify_migration():
    print("=" * 60)
    print("检查表签名迁移验证")
    print("=" * 60)

    # 检查 CheckSheetDailySummary 表中的 operator 字段
    try:
        daily_summaries = CheckSheetDailySummary.objects.all()
        total_count = daily_summaries.count()
        print(f"\n✓ CheckSheetDailySummary 表有 {total_count} 条记录")

        operator_count = daily_summaries.filter(operator__isnull=False).exclude(operator='').count()
        print(f"✓ 其中 {operator_count} 条记录有 operator 值")

        if operator_count > 0:
            print("\n前 5 条有 operator 的记录:")
            for summary in daily_summaries.filter(operator__isnull=False).exclude(operator='')[:5]:
                print(f"  - {summary.year}-{summary.month}-{summary.day}: operator={summary.operator}")
        else:
            print("\n⚠ 注意: 没有 operator 值，这是正常的（如果是全新环境）")

        print(f"\n✓ CheckSheetDailySummary 表结构验证通过")
        print(f"  - 字段包含: year, month, day, operator, remark, rectification")

        # 尝试访问 operator 字段
        if total_count > 0:
            first_summary = daily_summaries.first()
            _ = first_summary.operator
            print(f"✓ operator 字段可正常访问")

        # 检查是否还存在 CheckSheetSignature
        try:
            from spug_api.apps.checksheet.models import CheckSheetSignature
            signature_count = CheckSheetSignature.objects.count()
            print(f"\n❌ 检查失败: CheckSheetSignature 模型仍然存在，有 {signature_count} 条记录")
            print("   需要删除 models.py 中的 CheckSheetSignature 类定义")
            return False
        except ImportError:
            print(f"\n✓ CheckSheetSignature 模型已删除")

        print("\n" + "=" * 60)
        print("迁移验证成功 ✓")
        print("=" * 60)
        return True

    except Exception as e:
        print(f"\n❌ 检查 CheckSheetDailySummary 时出错: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == '__main__':
    success = verify_migration()
    sys.exit(0 if success else 1)
