#!/usr/bin/env python3
"""
租户隔离修复验证脚本
快速检查所有租户过滤和审计日志是否正确添加
"""

import re
import sys

# ==================== 配置 ====================
VIEWS_FILE = "data/backend/apps/document/views.py"
TENANT_UTILS_FILE = "data/backend/apps/libs/tenant_utils.py"

# ==================== 验证结果 ====================
checks = []

def check(description: str, passed: bool, details: str = ""):
    """记录检查结果"""
    status = "✅" if passed else "❌"
    checks.append({
        "name": description,
        "passed": passed,
        "details": details
    })
    print(f"{status} {description} {details}")

# ==================== 读取文件 ====================

try:
    with open(VIEWS_FILE, 'r', encoding='utf-8') as f:
        views_content = f.read()
except Exception as e:
    print(f"❌ 无法读取 {VIEWS_FILE}: {e}")
    sys.exit(1)

try:
    with open(TENANT_UTILS_FILE, 'r', encoding='utf-8') as f:
        utils_content = f.read()
except Exception as e:
    print(f"❌ 无法读取 {TENANT_UTILS_FILE}: {e}")
    sys.exit(1)

# ==================== 验证检查 ====================

print("🔍 开始验证租户隔离修复...\n")

# 1. 检查 log_operation 函数是否定义
if "def log_operation(" in views_content:
    check("审计日志函数定义", True)
else:
    check("审计日志函数定义", False, "log_operation 函数未找到")

# 2. 检查 log_operation 函数调用次数
log_operation_calls = len(re.findall(r'log_operation\(', views_content))
check(f"审计日志调用次数", log_operation_calls > 0, f"共 {log_operation_calls} 处调用")

# 3. 检查关键接口的租户过滤
critical_interfaces = [
    ("FolderView.delete", "FolderModel.objects.filter(pk=form.id)", "apply_tenant_filter"),
    ("FileView.delete", "FileModel.objects.filter(pk=form.id)", "apply_tenant_filter"),
    ("FileDownloadView.get", "FileModel.objects.filter(pk=form.id)", "apply_tenant_filter"),
    ("FilePreviewView.get", "FileModel.objects.filter(pk=form.id)", "apply_tenant_filter"),
    ("FileCopyView.post", "FileModel.objects.filter(pk=file_id)", "apply_tenant_filter"),
    ("FolderCopyView.post", "FolderModel.objects.filter(pk=folder_id)", "apply_tenant_filter"),
    ("FolderMoveView.post", "FolderModel.objects.filter(pk=folder_id)", "apply_tenant_filter"),
    ("FileMoveView.post", "FileModel.objects.filter(pk=file_id)", "apply_tenant_filter"),
]

for interface_name, filter_pattern, apply_func in critical_interfaces:
    # 查找该接口的代码块
    pattern = rf'class {interface_name.split(".")[0]}\([^:]+?def [^:]+?\(.*?\):(.*?)(?=class |$)'
    match = re.search(pattern, views_content, re.DOTALL)

    if not match:
        check(f"{interface_name} 代码块", False, "未找到接口定义")
        continue

    interface_code = match.group(1)

    # 检查是否有 .filter(pk=...) 模式
    if filter_pattern in interface_code:
        # 检查后续是否有 apply_tenant_filter 调用
        # 查找 filter 调用和 apply_tenant_filter 调用之间的代码
        filter_index = interface_code.find(filter_pattern)
        if filter_index != -1:
            # 提取 filter 调用之后的代码（500字符内）
            after_filter = interface_code[filter_index:filter_index+500]
            if apply_func in after_filter:
                check(f"{interface_name} 租户过滤", True)
            else:
                check(f"{interface_name} 租户过滤", False, "缺少 apply_tenant_filter 调用")
    else:
        check(f"{interface_name} 租户过滤", True, "使用了其他过滤方式")

# 4. 检查递归方法的租户过滤
recursive_methods = [
    "_delete_folder",
    "_copy_folder_recursive",
    "_add_folder_to_zip",
]

for method_name in recursive_methods:
    # 查找方法定义
    pattern = rf'def {method_name}\([^)]*\):(.*?)(?=\n    def |\nclass |$)'
    match = re.search(pattern, views_content, re.DOTALL)

    if not match:
        check(f"{method_name} 方法定义", False, "未找到方法")
        continue

    method_code = match.group(1)

    # 检查是否显式传递租户参数
    has_request_user = "request_user" in method_code
    has_is_public = "is_public" in method_code
    has_tenant_filter = "apply_tenant_filter" in method_code

    if has_request_user and has_is_public and has_tenant_filter:
        check(f"{method_name} 递归租户过滤", True)
    else:
        missing_params = []
        if not has_request_user:
            missing_params.append("request_user")
        if not has_is_public:
            missing_params.append("is_public")
        if not has_tenant_filter:
            missing_params.append("apply_tenant_filter")

        check(f"{method_name} 递归租户过滤", False, f"缺少: {', '.join(missing_params)}")

# 5. 检查越权告警
if "潜在越权拦截" in utils_content:
    check("越权拦截告警", True)
else:
    check("越权拦截告警", False, "未找到告警逻辑")

# 6. 检查数据库索引脚本
try:
    with open("scripts/add_document_tenant_indexes.sql", 'r', encoding='utf-8') as f:
        index_content = f.read()
except Exception:
    check("数据库索引脚本", False, "文件不存在")
else:
    index_count = index_content.count("CALL create_index_if_not_exists")
    if index_count >= 6:
        check("数据库索引脚本", True, f"包含 {index_count} 个索引定义")
    else:
        check("数据库索引脚本", False, f"仅包含 {index_count} 个索引定义，预期至少 6 个")

# 7. 检查测试脚本
try:
    with open("tests/automated_tenant_isolation_test.py", 'r', encoding='utf-8') as f:
        test_content = f.read()
except Exception:
    check("自动化测试脚本", False, "文件不存在")
else:
    if "test_cross_tenant_download" in test_content:
        check("自动化测试脚本", True)
    else:
        check("自动化测试脚本", False, "缺少测试用例")

# ==================== 输出结果 ====================

print("\n" + "=" * 80)
print("📊 验证结果汇总")
print("=" * 80 + "\n")

passed_count = sum(1 for c in checks if c["passed"])
total_count = len(checks)
pass_rate = (passed_count / total_count * 100) if total_count > 0 else 0

for i, check_item in enumerate(checks, 1):
    status_icon = "✅" if check_item["passed"] else "❌"
    print(f"{i}. {status_icon} {check_item['name']}")
    if check_item["details"]:
        print(f"   {check_item['details']}")

print("\n" + "─" * 80)
print(f"总计: {passed_count}/{total_count} 通过 ({pass_rate:.1f}%)")
print("─" * 80 + "\n")

if pass_rate == 100:
    print("🎉 所有验证通过！租户隔离修复完整。")
    sys.exit(0)
else:
    print("⚠️  部分验证失败，请检查上述问题。")
    sys.exit(1)
