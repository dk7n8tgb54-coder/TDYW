#!/usr/bin/env python3
"""
文档管理模块租户隔离自动化测试脚本
快速创建测试数据并验证租户隔离
"""

import requests
import json
import time
import sys
from typing import Dict, Optional

# ==================== 配置 ====================
BASE_URL = "http://localhost:8000"
TEST_FILE_NAME = "tenant_test_file.txt"
TEST_FILE_CONTENT = "This is a test file for tenant isolation testing."
TEST_FOLDER_NAME = "tenant_test_folder"

# ==================== 测试数据 ====================
tenant_a = {
    "username": "tenant_a",
    "password": "123456",
    "token": None,
    "file_id": None,
    "folder_id": None
}

tenant_b = {
    "username": "tenant_b",
    "password": "123456",
    "token": None,
    "file_id": None,
    "folder_id": None
}

test_results = []

# ==================== 工具函数 ====================

def log(message: str, level: str = "INFO"):
    """输出日志"""
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] [{level}] {message}")

def login(user_data: Dict) -> bool:
    """登录并保存 token"""
    try:
        resp = requests.post(
            f"{BASE_URL}/api/account/login/",
            json={
                "username": user_data["username"],
                "password": user_data["password"]
            },
            timeout=10
        )
        if resp.status_code == 200:
            result = resp.json()
            if result.get("token"):
                user_data["token"] = result["token"]
                log(f"✅ {user_data['username']} 登录成功", "SUCCESS")
                return True
        else:
            log(f"❌ {user_data['username']} 登录失败: {result}", "ERROR")
            return False
    except Exception as e:
        log(f"❌ {user_data['username']} 登录异常: {e}", "ERROR")
        return False

def create_file(user_data: Dict, is_public: bool = False) -> Optional[int]:
    """创建测试文件"""
    try:
        from io import StringIO
        files = {
            'file': (TEST_FILE_NAME, StringIO(TEST_FILE_CONTENT), 'text/plain')
        }
        data = {
            'is_public': 'true' if is_public else 'false',
            'folder_id': ''
        }

        resp = requests.post(
            f"{BASE_URL}/api/document/upload/",
            headers={"x-token": user_data["token"]},
            files=files,
            data=data,
            timeout=30
        )

        if resp.status_code == 200:
            log(f"✅ {user_data['username']} 创建文件成功 (is_public={is_public})", "SUCCESS")
            # 获取文件ID（通过查询列表）
            return get_file_id(user_data, TEST_FILE_NAME, is_public)
        else:
            log(f"❌ {user_data['username']} 创建文件失败: {resp.text}", "ERROR")
            return None
    except Exception as e:
        log(f"❌ {user_data['username']} 创建文件异常: {e}", "ERROR")
        return None

def get_file_id(user_data: Dict, file_name: str, is_public: bool) -> Optional[int]:
    """获取文件ID"""
    try:
        resp = requests.get(
            f"{BASE_URL}/api/document/folder/",
            params={"all": "true", "is_public": is_public},
            headers={"x-token": user_data["token"]},
            timeout=10
        )
        if resp.status_code == 200:
            result = resp.json()
            if "files" in result:
                for file in result["files"]:
                    if file["name"] == file_name:
                        return file["id"]
        return None
    except Exception as e:
        log(f"❌ 获取文件ID异常: {e}", "ERROR")
        return None

def create_folder(user_data: Dict, is_public: bool = False) -> Optional[int]:
    """创建测试文件夹"""
    try:
        resp = requests.post(
            f"{BASE_URL}/api/document/folder/",
            headers={
                "x-token": user_data["token"],
                "Content-Type": "application/json"
            },
            json={
                "name": TEST_FOLDER_NAME,
                "is_public": is_public
            },
            timeout=10
        )

        if resp.status_code == 200:
            result = resp.json()
            folder_id = result.get("id")
            log(f"✅ {user_data['username']} 创建文件夹成功 ID={folder_id} (is_public={is_public})", "SUCCESS")
            return folder_id
        else:
            log(f"❌ {user_data['username']} 创建文件夹失败: {resp.text}", "ERROR")
            return None
    except Exception as e:
        log(f"❌ {user_data['username']} 创建文件夹异常: {e}", "ERROR")
        return None

def download_file(attacker_data: Dict, file_id: int, is_public: bool) -> bool:
    """尝试下载文件（测试越权访问）"""
    try:
        resp = requests.get(
            f"{BASE_URL}/api/document/download/",
            params={"id": file_id, "is_public": is_public},
            headers={"x-token": attacker_data["token"]},
            timeout=10
        )
        # 返回200表示可以下载（漏洞），404表示文件不存在（安全）
        return resp.status_code == 200
    except Exception as e:
        log(f"❌ 下载请求异常: {e}", "ERROR")
        return False

def delete_file(attacker_data: Dict, file_id: int, is_public: bool) -> bool:
    """尝试删除文件（测试越权访问）"""
    try:
        resp = requests.delete(
            f"{BASE_URL}/api/document/file/",
            params={"id": file_id, "is_public": is_public},
            headers={"x-token": attacker_data["token"]},
            timeout=10
        )
        # 返回200表示可以删除（漏洞），404表示文件不存在（安全）
        return resp.status_code == 200
    except Exception as e:
        log(f"❌ 删除请求异常: {e}", "ERROR")
        return False

def delete_folder(attacker_data: Dict, folder_id: int, is_public: bool) -> bool:
    """尝试删除文件夹（测试越权访问）"""
    try:
        resp = requests.delete(
            f"{BASE_URL}/api/document/folder/",
            params={"id": folder_id, "is_public": is_public},
            headers={"x-token": attacker_data["token"]},
            timeout=10
        )
        # 返回200表示可以删除（漏洞），404表示文件夹不存在（安全）
        return resp.status_code == 200
    except Exception as e:
        log(f"❌ 删除文件夹请求异常: {e}", "ERROR")
        return False

def record_test(test_name: str, passed: bool, details: str = ""):
    """记录测试结果"""
    status = "✅ 通过" if passed else "❌ 失败"
    test_results.append({
        "name": test_name,
        "passed": passed,
        "details": details
    })
    log(f"{status} | {test_name} | {details}", "PASS" if passed else "FAIL")

def cleanup():
    """清理测试数据"""
    log("🧹 开始清理测试数据...", "INFO")

    if tenant_a["file_id"]:
        delete_file(tenant_a, tenant_a["file_id"], False)
    if tenant_a["folder_id"]:
        delete_folder(tenant_a, tenant_a["folder_id"], False)
    if tenant_b["file_id"]:
        delete_file(tenant_b, tenant_b["file_id"], False)
    if tenant_b["folder_id"]:
        delete_folder(tenant_b, tenant_b["folder_id"], False)

    log("🧹 清理完成", "INFO")

# ==================== 测试用例 ====================

def test_cross_tenant_download():
    """测试1：跨租户下载文件"""
    if not tenant_a["file_id"]:
        log("⏭️  跳过测试1：缺少测试文件", "WARN")
        return

    is_vulnerable = download_file(tenant_b, tenant_a["file_id"], False)
    passed = not is_vulnerable  # 应该下载失败

    record_test(
        "测试1：跨租户下载文件",
        passed,
        f"租户B尝试下载租户A的文件(#{tenant_a['file_id']}) - "
        f"{'🔴 漏洞存在！' if is_vulnerable else '✅ 租户隔离正常'}"
    )

def test_cross_tenant_delete_file():
    """测试2：跨租户删除文件"""
    if not tenant_a["file_id"]:
        log("⏭️  跳过测试2：缺少测试文件", "WARN")
        return

    is_vulnerable = delete_file(tenant_b, tenant_a["file_id"], False)
    passed = not is_vulnerable

    record_test(
        "测试2：跨租户删除文件",
        passed,
        f"租户B尝试删除租户A的文件(#{tenant_a['file_id']}) - "
        f"{'🔴 漏洞存在！' if is_vulnerable else '✅ 租户隔离正常'}"
    )

def test_cross_tenant_delete_folder():
    """测试3：跨租户删除文件夹"""
    if not tenant_a["folder_id"]:
        log("⏭️  跳过测试3：缺少测试文件夹", "WARN")
        return

    is_vulnerable = delete_folder(tenant_b, tenant_a["folder_id"], False)
    passed = not is_vulnerable

    record_test(
        "测试3：跨租户删除文件夹",
        passed,
        f"租户B尝试删除租户A的文件夹(#{tenant_a['folder_id']}) - "
        f"{'🔴 漏洞存在！' if is_vulnerable else '✅ 租户隔离正常'}"
    )

def test_public_space_permission():
    """测试4：公共空间权限校验"""
    # 租户A创建公共文件
    public_file_id = create_file(tenant_a, is_public=True)
    if not public_file_id:
        log("⏭️  跳过测试4：无法创建公共文件", "WARN")
        return

    # 租户B尝试删除租户A的公共文件（应该失败）
    is_vulnerable = delete_file(tenant_b, public_file_id, is_public=True)
    passed = not is_vulnerable

    # 清理公共文件
    delete_file(tenant_a, public_file_id, is_public=True)

    record_test(
        "测试4：公共空间权限校验",
        passed,
        f"租户B尝试删除租户A的公共文件(#{public_file_id}) - "
        f"{'🔴 权限校验失败！' if is_vulnerable else '✅ 权限校验正常'}"
    )

# ==================== 主程序 ====================

def main():
    """主测试流程"""
    log("=" * 80, "INFO")
    log("🚀 开始文档管理模块租户隔离测试", "INFO")
    log("=" * 80, "INFO")

    # 步骤1：登录
    log("\n📝 步骤1：登录测试账号", "INFO")
    if not login(tenant_a) or not login(tenant_b):
        log("❌ 登录失败，测试终止", "ERROR")
        sys.exit(1)

    # 步骤2：创建测试数据
    log("\n📝 步骤2：创建测试数据", "INFO")
    tenant_a["file_id"] = create_file(tenant_a, is_public=False)
    tenant_a["folder_id"] = create_folder(tenant_a, is_public=False)

    if not tenant_a["file_id"] or not tenant_a["folder_id"]:
        log("❌ 测试数据创建失败，测试终止", "ERROR")
        cleanup()
        sys.exit(1)

    time.sleep(1)  # 等待数据提交

    # 步骤3：执行安全测试
    log("\n📝 步骤3：执行安全测试", "INFO")
    test_cross_tenant_download()
    test_cross_tenant_delete_file()
    test_cross_tenant_delete_folder()
    test_public_space_permission()

    # 步骤4：输出测试结果
    log("\n📊 测试结果汇总", "INFO")
    log("=" * 80, "INFO")
    passed_count = sum(1 for t in test_results if t["passed"])
    total_count = len(test_results)
    pass_rate = (passed_count / total_count * 100) if total_count > 0 else 0

    print("\n┌─────────────────────────────────────────────────────────────────────┐")
    print("│                    租户隔离测试报告                          │")
    print("├─────────────────────────────────────────────────────────────┤")
    print(f"│ 总测试数: {total_count:<50} │")
    print(f"│ 通过数:   {passed_count:<50} │")
    print(f"│ 失败数:   {total_count - passed_count:<50} │")
    print(f"│ 通过率:   {pass_rate:.1f}%{'':^47} │")
    print("└─────────────────────────────────────────────────────────────┘\n")

    for i, test in enumerate(test_results, 1):
        status_icon = "✅" if test["passed"] else "❌"
        print(f"{i}. {status_icon} {test['name']}")
        if test["details"]:
            print(f"   详情: {test['details']}")

    # 步骤5：清理测试数据
    log("\n📝 步骤4：清理测试数据", "INFO")
    cleanup()

    # 步骤6：判断测试结果
    log("\n🏁 测试完成", "INFO")
    if all(t["passed"] for t in test_results):
        log("✅ 所有测试通过！租户隔离工作正常。", "SUCCESS")
        sys.exit(0)
    else:
        failed_tests = [t["name"] for t in test_results if not t["passed"]]
        log(f"❌ 以下测试失败: {', '.join(failed_tests)}", "ERROR")
        log("⚠️  请检查租户过滤逻辑是否正确实现！", "WARN")
        sys.exit(1)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("\n⚠️  测试被用户中断", "WARN")
        cleanup()
        sys.exit(1)
    except Exception as e:
        log(f"\n❌ 测试异常: {e}", "ERROR")
        import traceback
        traceback.print_exc()
        cleanup()
        sys.exit(1)
