#!/usr/bin/env python3
"""
运行事务保护和批量操作测试的便捷脚本

使用方法:
    python run_batch_transaction_tests.py

测试内容:
    1. Celery批量删除任务的事务保护
    2. Celery批量取消任务的事务保护
    3. 批量暂停/恢复API的事务行为
    4. 租户隔离验证
    5. 并发操作测试
"""

import os
import sys
import subprocess
import argparse

def print_header(title):
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70 + "\n")

def print_section(title):
    print(f"\n{'-' * 70}")
    print(f"  {title}")
    print(f"{'-' * 70}\n")

def run_test(test_type='all', verbose=False):
    """运行测试"""
    
    # 确定Python路径
    python_paths = [
        'python',
        'python3',
        '/usr/bin/python3',
        'C:\\Python39\\python.exe',
    ]
    
    python_cmd = None
    for cmd in python_paths:
        try:
            result = subprocess.run([cmd, '--version'], 
                                  capture_output=True, 
                                  timeout=5)
            if result.returncode == 0:
                python_cmd = cmd
                break
        except:
            continue
    
    if not python_cmd:
        print("错误: 未找到Python解释器")
        sys.exit(1)
    
    print(f"使用Python: {python_cmd}")
    
    # 构建测试路径
    base_dir = os.path.dirname(os.path.abspath(__file__))
    test_file = os.path.join(base_dir, 'spug_api', 'tests', 'test_batch_transaction_protection.py')
    
    if not os.path.exists(test_file):
        print(f"错误: 测试文件不存在: {test_file}")
        sys.exit(1)
    
    print(f"测试文件: {test_file}")
    
    # 设置环境变量
    env = os.environ.copy()
    env['PYTHONPATH'] = os.path.join(base_dir, 'spug_api')
    env['DJANGO_SETTINGS_MODULE'] = 'spug.settings'
    
    # 运行测试
    print_section("开始执行测试")
    
    try:
        result = subprocess.run(
            [python_cmd, test_file],
            env=env,
            capture_output=not verbose,
            text=True,
            timeout=120
        )
        
        if verbose:
            # 已经在实时输出了
            pass
        else:
            print(result.stdout)
            if result.stderr:
                print("错误输出:")
                print(result.stderr)
        
        if result.returncode == 0:
            print_section("测试通过 ✓")
            return True
        else:
            print_section("测试失败 ✗")
            return False
            
    except subprocess.TimeoutExpired:
        print("错误: 测试超时")
        return False
    except Exception as e:
        print(f"错误: 运行测试时发生异常: {e}")
        return False

def check_environment():
    """检查测试环境"""
    print_section("环境检查")
    
    checks = []
    
    # 检查Django
    try:
        import django
        checks.append(("Django", f"✓ {django.VERSION}"))
    except ImportError:
        checks.append(("Django", "✗ 未安装"))
    
    # 检查Celery
    try:
        import celery
        checks.append(("Celery", f"✓ {celery.__version__}"))
    except ImportError:
        checks.append(("Celery", "✗ 未安装"))
    
    # 检查数据库连接
    try:
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'spug_api'))
        os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')
        django.setup()
        from django.db import connection
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        checks.append(("数据库连接", "✓ 正常"))
    except Exception as e:
        checks.append(("数据库连接", f"✗ 失败 - {str(e)[:50]}"))
    
    # 打印检查结果
    for name, status in checks:
        print(f"  {name:.<20} {status}")
    
    return all('✓' in status for status in [s for _, s in checks])

def main():
    parser = argparse.ArgumentParser(
        description='运行事务保护和批量操作测试',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python run_batch_transaction_tests.py           # 运行所有测试
  python run_batch_transaction_tests.py -v        # 详细输出
  python run_batch_transaction_tests.py --check   # 仅检查环境
        """
    )
    parser.add_argument('-v', '--verbose', action='store_true', 
                       help='显示详细输出')
    parser.add_argument('--check', action='store_true',
                       help='仅检查环境，不运行测试')
    
    args = parser.parse_args()
    
    print_header("事务保护与批量操作测试运行器")
    
    # 检查环境
    if not check_environment():
        print("\n环境检查失败，请确保:")
        print("1. 已安装Django和Celery")
        print("2. 数据库配置正确")
        print("3. 在项目根目录运行此脚本")
        sys.exit(1)
    
    if args.check:
        print("\n环境检查完成")
        sys.exit(0)
    
    # 运行测试
    success = run_test(verbose=args.verbose)
    
    if success:
        print("\n所有测试通过！")
        sys.exit(0)
    else:
        print("\n部分测试失败，请查看输出详情")
        sys.exit(1)

if __name__ == '__main__':
    main()
