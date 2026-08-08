"""跨租户文件/附件隔离测试

覆盖: document, evidence, regulation, kkFileView
当前状态: 源码审查结论，未执行行为测试
"""
from helpers.file_assertions import FILE_ISOLATION_FINDINGS


def run(context):
    """执行跨租户文件隔离测试

    Returns:
        list: 测试结果列表
    """
    results = []

    for f in FILE_ISOLATION_FINDINGS:
        results.append({
            'module': f['module'],
            'test': f'文件隔离: {f["finding"]}',
            'passed': None,  # 待行为测试
            'detail': f['detail'],
            'severity': f['risk'].lower(),
        })

    return results
