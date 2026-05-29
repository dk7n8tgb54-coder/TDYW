# 检查表模块API测试脚本
import os
import sys
import django

# 设置Django环境
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../spug_api/apps'))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')
django.setup()

import json
from apps.checksheet.models import CheckSheetTemplate, CheckSheetRecord, CheckSheetSignature
from apps.account.models import User


def test_create_template():
    """测试创建检查表模板"""
    print("测试创建检查表模板...")

    template = CheckSheetTemplate.objects.create(
        project="导航",
        check_items=[
            "导航设备运行情况",
            "导航信号强度检查",
            "导航系统备份检查",
            "导航设备外观检查"
        ],
        tenant_id="test"
    )

    print(f"创建模板成功: ID={template.id}, 项目={template.project}, 检查项数量={len(template.check_items)}")
    return template


def test_create_records():
    """测试创建检查记录"""
    print("\n测试创建检查记录...")

    template = CheckSheetTemplate.objects.filter(project="导航", tenant_id="test").first()
    if not template:
        print("模板不存在，请先创建模板")
        return

    # 创建几条测试记录
    records = [
        CheckSheetRecord(
            template=template,
            year="2026",
            month="03",
            day=12,
            item_index=0,
            status="NORMAL",
            remark="运行正常",
            tenant_id="test"
        ),
        CheckSheetRecord(
            template=template,
            year="2026",
            month="03",
            day=12,
            item_index=1,
            status="ABNORMAL",
            remark="信号强度偏低",
            tenant_id="test"
        ),
        CheckSheetRecord(
            template=template,
            year="2026",
            month="03",
            day=11,
            item_index=0,
            status="NORMAL",
            remark="",
            tenant_id="test"
        )
    ]

    for record in records:
        record.save()
        print(f"创建记录成功: {record.template.project} {record.year}-{record.month}-{record.day} 第{record.item_index + 1}项")


def test_create_signature():
    """测试创建签名"""
    print("\n测试创建签名...")

    template = CheckSheetTemplate.objects.filter(project="导航", tenant_id="test").first()
    if not template:
        print("模板不存在，请先创建模板")
        return

    signature = CheckSheetSignature.objects.create(
        template=template,
        year="2026",
        month="03",
        operator="张三",
        reviewer="李四",
        tenant_id="test"
    )

    print(f"创建签名成功: {signature.template.project} {signature.year}-{signature.month}")


def test_query_data():
    """测试查询数据"""
    print("\n测试查询数据...")

    # 查询模板
    templates = CheckSheetTemplate.objects.filter(tenant_id="test")
    print(f"\n找到 {templates.count()} 个模板:")
    for t in templates:
        print(f"  - {t.project}: {len(t.check_items)}个检查项")

    # 查询记录
    records = CheckSheetRecord.objects.filter(
        year="2026",
        month="03",
        tenant_id="test"
    )

    print(f"\n找到 {records.count()} 条记录:")
    for r in records[:10]:  # 只显示前10条
        print(f"  - {r.template.project} {r.year}-{r.month}-{r.day} 第{r.item_index + 1}项: {r.status}")

    # 查询签名
    signatures = CheckSheetSignature.objects.filter(
        year="2026",
        month="03",
        tenant_id="test"
    )

    print(f"\n找到 {signatures.count()} 个签名:")
    for s in signatures:
        print(f"  - {s.template.project} {s.year}-{s.month}: 值班人员={s.operator}, 审核人={s.reviewer}")


def cleanup_test_data():
    """清理测试数据"""
    print("\n清理测试数据...")

    deleted_templates = CheckSheetTemplate.objects.filter(tenant_id="test").delete()[0]
    deleted_records = CheckSheetRecord.objects.filter(tenant_id="test").delete()[0]
    deleted_signatures = CheckSheetSignature.objects.filter(tenant_id="test").delete()[0]

    print(f"删除了 {deleted_templates} 个模板, {deleted_records} 条记录, {deleted_signatures} 个签名")


if __name__ == '__main__':
    print("=" * 60)
    print("检查表模块数据库测试")
    print("=" * 60)

    try:
        # 清理旧数据
        cleanup_test_data()

        # 创建测试数据
        template = test_create_template()
        test_create_records()
        test_create_signature()

        # 查询数据
        test_query_data()

        print("\n" + "=" * 60)
        print("测试完成！")
        print("=" * 60)

    except Exception as e:
        print(f"\n测试出错: {e}")
        import traceback
        traceback.print_exc()
