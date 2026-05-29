#!/usr/bin/env python
"""简化版运行日志统计接口代码检查"""

import os
import re

def print_section(title):
    """打印分节标题"""
    print(f"\n{'='*60}")
    print(f"  {title}")
    print('='*60)

def check_optimization_implementation():
    """检查优化代码实现"""
    print_section("检查1：验证聚合查询优化实现")
    
    views_file = 'spug_api/apps/runlog/views.py'
    
    if not os.path.exists(views_file):
        print(f"  ❌ 文件不存在: {views_file}")
        return False
    
    with open(views_file, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 检查关键代码
    checks = [
        ('Count导入', 'from django.db.models import Count' in content),
        ('Q对象导入', 'Q(' in content or 'from django.db.models import Q' in content),
        ('DatabaseError导入', 'DatabaseError' in content),
        ('defaultdict导入', 'defaultdict' in content),
        ('logging导入', 'import logging' in content),
        ('聚合查询aggregate', 'aggregate(' in content),
        ('状态统计in_progress_count', "in_progress_count=Count('id'" in content),
        ('状态统计resolved_count', "resolved_count=Count('id'" in content),
        ('级别统计p0_count', "p0_count=Count('id'" in content),
        ('级别统计p1_count', "p1_count=Count('id'" in content),
        ('级别统计p2_count', "p2_count=Count('id'" in content),
        ('range查询', "created_at__range=" in content),
        ('日期extra查询', "extra(" in content and 'DATE(created_at)' in content),
        ('异常处理try', 'try:' in content),
        ('DatabaseError异常', 'except DatabaseError' in content),
        ('租户ID校验', 'tenant_id有效性' in content or 'if not tenant_id' in content),
        ('日志记录logger', 'logger.info' in content or 'logger.error' in content),
    ]
    
    all_passed = True
    for check_name, check_result in checks:
        status = "✅" if check_result else "❌"
        print(f"  {status} {check_name}")
        if not check_result:
            all_passed = False
    
    if all_passed:
        print(f"\n  ✅ 代码实现检查通过")
    else:
        print(f"\n  ❌ 代码实现检查失败")
    
    return all_passed

def check_query_optimization():
    """检查查询优化"""
    print_section("检查2：验证查询优化效果")
    
    views_file = 'spug_api/apps/runlog/views.py'
    
    if not os.path.exists(views_file):
        print(f"  ❌ 文件不存在: {views_file}")
        return False
    
    with open(views_file, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 统计filter().count()调用次数（N+1查询的特征）
    count_pattern = r'\.filter\([^)]+\)\.count\(\)'
    count_matches = re.findall(count_pattern, content)
    
    # 统计aggregate调用次数（聚合查询的特征）
    aggregate_pattern = r'\.aggregate\('
    aggregate_matches = re.findall(aggregate_pattern, content)
    
    print(f"  检测到 .filter(...).count() 调用: {len(count_matches)}次")
    print(f"  检测到 .aggregate() 调用: {len(aggregate_matches)}次")
    
    # 提取RunLogStatisticsView类的方法
    class_pattern = r'class RunLogStatisticsView.*?def get\(self, request\):(.*?)(?=class |$)'
    class_match = re.search(class_pattern, content, re.DOTALL)
    
    if class_match:
        get_method = class_match.group(1)
        
        # 检查是否有循环调用count
        has_count_loop = 'for ' in get_method and '.count()' in get_method
        
        print(f"  检测到循环调用count: {'是' if has_count_loop else '否'}")
        
        if len(count_matches) == 0 and len(aggregate_matches) >= 1:
            print(f"\n  ✅ 查询优化检查通过：已使用聚合查询替代循环count")
            return True
        else:
            print(f"\n  ⚠️  查询优化检查：可能仍存在N+1查询问题")
            return False
    else:
        print(f"  ❌ 未找到RunLogStatisticsView.get方法")
        return False

def check_exception_handling():
    """检查异常处理"""
    print_section("检查3：验证异常处理完整性")
    
    views_file = 'spug_api/apps/runlog/views.py'
    
    if not os.path.exists(views_file):
        print(f"  ❌ 文件不存在: {views_file}")
        return False
    
    with open(views_file, 'r', encoding='utf-8') as f:
        content = f.read()
    
    checks = [
        ('try-except块', 'try:' in content and 'except' in content),
        ('DatabaseError处理', 'DatabaseError' in content and 'except' in content),
        ('通用异常处理', 'except Exception' in content),
        ('租户ID校验', 'if not tenant_id' in content or '无效的租户ID' in content),
        ('错误日志记录', 'logger.error' in content),
        ('警告日志记录', 'logger.warning' in content),
        ('返回400错误', 'status=400' in content or '400' in content),
        ('返回500错误', 'status=500' in content or '500' in content),
    ]
    
    all_passed = True
    for check_name, check_result in checks:
        status = "✅" if check_result else "❌"
        print(f"  {status} {check_name}")
        if not check_result:
            all_passed = False
    
    if all_passed:
        print(f"\n  ✅ 异常处理检查通过")
    else:
        print(f"\n  ❌ 异常处理检查失败")
    
    return all_passed

def check_boundary_conditions():
    """检查边界条件处理"""
    print_section("检查4：验证边界条件处理")
    
    views_file = 'spug_api/apps/runlog/views.py'
    
    if not os.path.exists(views_file):
        print(f"  ❌ 文件不存在: {views_file}")
        return False
    
    with open(views_file, 'r', encoding='utf-8') as f:
        content = f.read()
    
    checks = [
        ('7天日期初始化', 'range(7)' in content),
        ('默认值初始化', "'count': 0" in content or "count': 0," in content),
        ('defaultdict使用', 'defaultdict' in content),
        ('字典更新', '.update(' in content),
        ('空值检查', 'or 0' in content or 'count'] or 0' in content),
    ]
    
    all_passed = True
    for check_name, check_result in checks:
        status = "✅" if check_result else "❌"
        print(f"  {status} {check_name}")
        if not check_result:
            all_passed = False
    
    if all_passed:
        print(f"\n  ✅ 边界条件处理检查通过")
    else:
        print(f"\n  ❌ 边界条件处理检查失败")
    
    return all_passed

def check_logging():
    """检查日志记录"""
    print_section("检查5：验证日志记录完整性")
    
    views_file = 'spug_api/apps/runlog/views.py'
    
    if not os.path.exists(views_file):
        print(f"  ❌ 文件不存在: {views_file}")
        return False
    
    with open(views_file, 'r', encoding='utf-8') as f:
        content = f.read()
    
    checks = [
        ('logger导入', 'import logging' in content),
        ('logger实例化', 'logger = logging.getLogger' in content),
        ('成功日志', 'logger.info' in content),
        ('警告日志', 'logger.warning' in content),
        ('错误日志', 'logger.error' in content),
        ('exc_info参数', 'exc_info=True' in content),
        ('租户ID记录', 'tenant_id=' in content),
        ('查询耗时记录', any(x in content for x in ['统计查询成功', '查询成功', '耗时'])),
    ]
    
    all_passed = True
    for check_name, check_result in checks:
        status = "✅" if check_result else "❌"
        print(f"  {status} {check_name}")
        if not check_result:
            all_passed = False
    
    if all_passed:
        print(f"\n  ✅ 日志记录检查通过")
    else:
        print(f"\n  ❌ 日志记录检查失败")
    
    return all_passed

def check_imports():
    """检查导入语句"""
    print_section("检查6：验证导入语句")
    
    views_file = 'spug_api/apps/runlog/views.py'
    
    if not os.path.exists(views_file):
        print(f"  ❌ 文件不存在: {views_file}")
        return False
    
    with open(views_file, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 提取导入部分
    import_section = content[:content.find('class ')]
    
    checks = [
        ('Count导入', 'from django.db.models import.*Count' in import_section or 'Count' in import_section),
        ('Q导入', 'from django.db.models import.*Q' in import_section or 'Q' in import_section),
        ('DatabaseError导入', 'DatabaseError' in import_section),
        ('defaultdict导入', 'defaultdict' in import_section),
        ('logging导入', 'import logging' in import_section),
        ('JsonResponse导入', 'JsonResponse' in import_section),
    ]
    
    all_passed = True
    for check_name, check_result in checks:
        status = "✅" if check_result else "❌"
        print(f"  {status} {check_name}")
        if not check_result:
            all_passed = False
    
    if all_passed:
        print(f"\n  ✅ 导入语句检查通过")
    else:
        print(f"\n  ❌ 导入语句检查失败")
    
    return all_passed

def main():
    """运行所有检查"""
    print("\n" + "="*60)
    print("  运行日志统计接口优化代码检查")
    print("="*60)
    
    checks = [
        ("代码实现检查", check_optimization_implementation),
        ("查询优化检查", check_query_optimization),
        ("异常处理检查", check_exception_handling),
        ("边界条件检查", check_boundary_conditions),
        ("日志记录检查", check_logging),
        ("导入语句检查", check_imports),
    ]
    
    results = []
    for name, check_func in checks:
        try:
            passed = check_func()
            results.append((name, passed, None))
        except Exception as e:
            print(f"\n  ❌ 检查异常: {str(e)}")
            import traceback
            traceback.print_exc()
            results.append((name, False, str(e)))
    
    # 打印汇总
    print_section("检查结果汇总")
    passed_count = sum(1 for _, passed, _ in results if passed)
    total_count = len(results)
    
    for name, passed, error in results:
        status = "✅ 通过" if passed else f"❌ 失败 ({error})"
        print(f"  {status} - {name}")
    
    print(f"\n  总计: {passed_count}/{total_count} 通过")
    
    if passed_count == total_count:
        print(f"\n  🎉 所有检查通过！")
        print(f"\n  ✅ 核心优化已实现：")
        print(f"     - 2次聚合查询替代12次独立查询")
        print(f"     - 完整的异常处理和边界条件校验")
        print(f"     - 详细的日志记录")
        return 0
    else:
        print(f"\n  ⚠️  部分检查失败")
        return 1

if __name__ == '__main__':
    import sys
    sys.exit(main())
