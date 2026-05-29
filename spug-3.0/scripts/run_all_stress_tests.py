#!/usr/bin/env python3
"""
资料库全量性能测试运行脚本
一键运行所有性能测试并生成综合报告

使用方法:
    python run_all_stress_tests.py

可选参数:
    --host: 目标主机地址 (默认: http://localhost)
    --users: 并发用户数 (默认: 50)
    --time: 测试时长 (默认: 5m)
    --output: 输出目录 (默认: ./stress_test_reports)
"""

import os
import sys
import subprocess
import argparse
import json
from datetime import datetime
from pathlib import Path


# 测试配置
TEST_CONFIGS = [
    {
        "name": "基础功能压测",
        "file": "locustfile_document.py",
        "port": 8090,
        "description": "资料库基础功能高并发测试"
    },
    {
        "name": "回收站压测", 
        "file": "locustfile_recycle_bin.py",
        "port": 8091,
        "description": "回收站大容量场景测试"
    },
    {
        "name": "分页功能压测",
        "file": "locustfile_pagination.py", 
        "port": 8092,
        "description": "真实分页功能压力测试"
    },
    {
        "name": "深度嵌套压测",
        "file": "locustfile_folder_depth.py",
        "port": 8093,
        "description": "文件夹深度嵌套测试"
    }
]


def run_locust_test(config, host, users, time, output_dir):
    """
    运行单个Locust测试
    
    Args:
        config: 测试配置
        host: 目标主机
        users: 并发用户数
        time: 测试时长
        output_dir: 输出目录
        
    Returns:
        dict: 测试结果摘要
    """
    print(f"\n{'='*70}")
    print(f"开始测试: {config['name']}")
    print(f"描述: {config['description']}")
    print(f"{'='*70}\n")
    
    # 构建输出文件名
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    test_name = config['name'].replace(' ', '_')
    csv_prefix = f"{output_dir}/{test_name}_{timestamp}"
    
    # 构建命令
    cmd = [
        "locust",
        "-f", config['file'],
        "-H", host,
        "--users", str(users),
        "--spawn-rate", str(users // 5),
        "--run-time", time,
        "--headless",
        "--csv", csv_prefix
    ]
    
    print(f"执行命令: {' '.join(cmd)}\n")
    
    # 运行测试
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=parse_time_to_seconds(time) + 300  # 额外5分钟缓冲
        )
        
        # 检查CSV文件是否生成
        stats_file = f"{csv_prefix}_stats.csv"
        if os.path.exists(stats_file):
            summary = parse_stats_csv(stats_file)
            summary['test_name'] = config['name']
            summary['status'] = 'success'
            print(f"✅ {config['name']} 测试完成")
            return summary
        else:
            print(f"⚠️ {config['name']} 测试未完成，未生成统计文件")
            return {
                'test_name': config['name'],
                'status': 'failed',
                'error': '未生成统计文件'
            }
            
    except subprocess.TimeoutExpired:
        print(f"❌ {config['name']} 测试超时")
        return {
            'test_name': config['name'],
            'status': 'timeout'
        }
    except Exception as e:
        print(f"❌ {config['name']} 测试异常: {e}")
        return {
            'test_name': config['name'],
            'status': 'error',
            'error': str(e)
        }


def parse_time_to_seconds(time_str):
    """将时间字符串转换为秒数"""
    time_str = time_str.lower()
    if time_str.endswith('s'):
        return int(time_str[:-1])
    elif time_str.endswith('m'):
        return int(time_str[:-1]) * 60
    elif time_str.endswith('h'):
        return int(time_str[:-1]) * 3600)
    else:
        return int(time_str)


def parse_stats_csv(csv_file):
    """解析Locust统计CSV文件"""
    summary = {
        'total_requests': 0,
        'failed_requests': 0,
        'avg_response_time': 0,
        'p95_response_time': 0,
        'p99_response_time': 0,
        'max_response_time': 0,
        'requests_per_sec': 0
    }
    
    try:
        with open(csv_file, 'r', encoding='utf-8') as f:
            lines = f.readlines()
            
        if len(lines) < 2:
            return summary
            
        # 跳过标题行
        for line in lines[1:]:
            parts = line.strip().split(',')
            if len(parts) >= 10:
                # Locust CSV格式: Type,Name,Request Count,Failure Count,...
                try:
                    request_count = int(parts[2])
                    failure_count = int(parts[3])
                    
                    summary['total_requests'] += request_count
                    summary['failed_requests'] += failure_count
                except ValueError:
                    continue
                    
        # 计算失败率
        if summary['total_requests'] > 0:
            summary['failure_rate'] = summary['failed_requests'] / summary['total_requests']
        else:
            summary['failure_rate'] = 0
            
    except Exception as e:
        print(f"解析CSV文件失败: {e}")
        
    return summary


def generate_report(all_results, output_dir):
    """生成综合测试报告"""
    report_file = f"{output_dir}/综合测试报告_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
    
    with open(report_file, 'w', encoding='utf-8') as f:
        f.write("# 资料库性能测试综合报告\n\n")
        f.write(f"**测试时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        
        # 汇总表格
        f.write("## 测试结果汇总\n\n")
        f.write("| 测试项目 | 状态 | 总请求数 | 失败数 | 失败率 |\n")
        f.write("|---------|------|---------|--------|--------|\n")
        
        total_requests = 0
        total_failed = 0
        
        for result in all_results:
            status_icon = "✅" if result['status'] == 'success' else "❌"
            requests = result.get('total_requests', 0)
            failed = result.get('failed_requests', 0)
            failure_rate = f"{result.get('failure_rate', 0)*100:.2f}%"
            
            f.write(f"| {result['test_name']} | {status_icon} | {requests} | {failed} | {failure_rate} |\n")
            
            total_requests += requests
            total_failed += failed
            
        # 总体统计
        overall_failure_rate = (total_failed / total_requests * 100) if total_requests > 0 else 0
        f.write(f"\n**总体统计**: 总请求 {total_requests}, 失败 {total_failed}, 失败率 {overall_failure_rate:.2f}%\n\n")
        
        # 详细结果
        f.write("## 详细测试结果\n\n")
        for result in all_results:
            f.write(f"### {result['test_name']}\n\n")
            
            if result['status'] == 'success':
                f.write(f"- **状态**: ✅ 成功\n")
                f.write(f"- **总请求数**: {result.get('total_requests', 0)}\n")
                f.write(f"- **失败请求数**: {result.get('failed_requests', 0)}\n")
                f.write(f"- **失败率**: {result.get('failure_rate', 0)*100:.2f}%\n")
                f.write(f"- **平均响应时间**: {result.get('avg_response_time', 0):.2f}ms\n")
                f.write(f"- **P95响应时间**: {result.get('p95_response_time', 0):.2f}ms\n")
                f.write(f"- **P99响应时间**: {result.get('p99_response_time', 0):.2f}ms\n")
            else:
                f.write(f"- **状态**: ❌ 失败\n")
                f.write(f"- **错误信息**: {result.get('error', '未知错误')}\n")
                
            f.write("\n")
            
        # 建议
        f.write("## 性能优化建议\n\n")
        
        if overall_failure_rate > 1:
            f.write("⚠️ **失败率较高，建议进行以下优化**:\n\n")
            f.write("1. 检查数据库连接池配置\n")
            f.write("2. 优化慢查询\n")
            f.write("3. 增加缓存层\n")
            f.write("4. 检查是否有锁竞争\n\n")
        else:
            f.write("✅ **整体性能良好**，建议持续监控以下指标:\n\n")
            f.write("1. 数据库连接数\n")
            f.write("2. 慢查询日志\n")
            f.write("3. 内存使用情况\n")
            f.write("4. 磁盘IO\n\n")
            
    print(f"\n📊 综合报告已生成: {report_file}")
    return report_file


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='资料库全量性能测试')
    parser.add_argument('--host', default='http://localhost', help='目标主机地址')
    parser.add_argument('--users', type=int, default=50, help='并发用户数')
    parser.add_argument('--time', default='5m', help='测试时长 (如 5m, 10m, 1h)')
    parser.add_argument('--output', default='./stress_test_reports', help='输出目录')
    
    args = parser.parse_args()
    
    # 创建输出目录
    os.makedirs(args.output, exist_ok=True)
    
    print("\n" + "="*70)
    print("资料库全量性能测试")
    print("="*70)
    print(f"目标主机: {args.host}")
    print(f"并发用户: {args.users}")
    print(f"测试时长: {args.time}")
    print(f"输出目录: {args.output}")
    print("="*70)
    
    # 检查Locust是否安装
    try:
        subprocess.run(['locust', '--version'], capture_output=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("\n❌ 错误: 未安装Locust，请先安装: pip install locust")
        sys.exit(1)
        
    # 运行所有测试
    all_results = []
    for config in TEST_CONFIGS:
        result = run_locust_test(config, args.host, args.users, args.time, args.output)
        all_results.append(result)
        
    # 生成综合报告
    report_file = generate_report(all_results, args.output)
    
    # 输出摘要
    print("\n" + "="*70)
    print("测试完成摘要")
    print("="*70)
    
    success_count = sum(1 for r in all_results if r['status'] == 'success')
    print(f"通过: {success_count}/{len(all_results)}")
    
    for result in all_results:
        status = "✅" if result['status'] == 'success' else "❌"
        print(f"{status} {result['test_name']}")
        
    print(f"\n📊 详细报告: {report_file}")
    print("="*70 + "\n")


if __name__ == "__main__":
    main()
