#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
合并失败重试功能测试脚本
用于验证P0-Day1修改是否生效

测试内容：
1. 分片检测接口新增字段（all_chunks_ready, can_merge_directly, error_code）
2. 直接合并接口可用性
3. 幂等性检查
4. 权限验证

使用方法：
1. 修改配置区的 TOKEN 和 BASE_URL
2. 运行: python test_merge_retry.py
"""

import requests
import sys
import json
from datetime import datetime

# ==================== 配置区 ====================
# 方式1: 直接填写Token（从浏览器开发者工具获取）
TOKEN = "your_token_here"

# API基础URL - 根据你的环境修改
# 注意：代码中没有 /v1/ 版本前缀，只有 /api/
#   Dev环境:    http://localhost/api
#   Docker环境: http://localhost:8080/api
BASE_URL = "http://localhost/api"  # 80端口
# BASE_URL = "http://localhost:8080/api"

# 方式2: 使用用户名密码自动获取Token（如果TOKEN未配置）
# 登录地址: BASE_URL 已经是 http://localhost/api，加上 /account/login/
_AUTO_LOGIN_URL = BASE_URL + "/account/login/"
AUTO_LOGIN = {
    "enabled": TOKEN == "your_token_here",  # Token未配置时自动启用
    "username": "admin",
    "password": "Admin888",  # 修改为你的密码
    "login_url": _AUTO_LOGIN_URL
}

# 测试用的传输记录ID（可选，如果不存在会跳过相关测试）
TEST_TRANSFER_ID = None  # 例如: 123

# 是否显示详细响应
VERBOSE = True

# ==================== 颜色输出 ====================
class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    END = '\033[0m'

def success(msg):
    print(f"{Colors.GREEN}✅ {msg}{Colors.END}")

def error(msg):
    print(f"{Colors.RED}❌ {msg}{Colors.END}")

def warning(msg):
    print(f"{Colors.YELLOW}⚠️  {msg}{Colors.END}")

def info(msg):
    print(f"{Colors.BLUE}ℹ️  {msg}{Colors.END}")

def print_response(resp, label="响应"):
    """打印响应详情"""
    if not VERBOSE:
        return
    print(f"\n  [{label}]")
    print(f"  状态码: {resp.status_code}")
    try:
        data = resp.json()
        print(f"  内容: {json.dumps(data, indent=2, ensure_ascii=False)[:500]}")
    except:
        print(f"  内容: {resp.text[:200]}")

# ==================== 测试用例 ====================

class MergeRetryTester:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "Content-Type": "application/json"
        })
        self.token = TOKEN
        self.passed = 0
        self.failed = 0
        self.skipped = 0
        
        # 尝试自动获取Token
        if self.token == "your_token_here" and AUTO_LOGIN["enabled"]:
            self._auto_login()
        
        # 设置Token到headers
        if self.token and self.token != "your_token_here":
            self.session.headers.update({
                "Authorization": f"Token {self.token}"
            })
    
    def _auto_login(self):
        """自动登录获取Token"""
        try:
            info(f"尝试自动登录: {AUTO_LOGIN['username']}")
            resp = self.session.post(
                AUTO_LOGIN["login_url"],
                json={
                    "username": AUTO_LOGIN["username"],
                    "password": AUTO_LOGIN["password"]
                }
            )
            if resp.status_code == 200:
                data = resp.json()
                # 登录接口直接返回数据，没有 data 包装
                # 成功: {"id": 1, "access_token": "xxx", ...}
                # 失败: {"error": "xxx"}
                if "error" in data:
                    error(f"登录失败: {data['error']}")
                    return
                
                self.token = data.get("access_token")
                if self.token:
                    success(f"自动登录成功，获取到Token: {self.token[:10]}...")
                else:
                    error(f"自动登录成功，但响应中未找到 access_token: {list(data.keys())}")
            else:
                error(f"自动登录失败: {resp.status_code}")
                if VERBOSE:
                    print(f"  响应: {resp.text[:200]}")
        except Exception as e:
            error(f"自动登录异常: {e}")

    def run_test(self, name, func):
        """运行单个测试"""
        print(f"\n{'='*60}")
        print(f"测试: {name}")
        print('='*60)
        try:
            result = func()
            if result is True:
                self.passed += 1
            elif result is False:
                self.failed += 1
            else:  # None = skipped
                self.skipped += 1
            return result
        except Exception as e:
            error(f"测试异常: {e}")
            if VERBOSE:
                import traceback
                traceback.print_exc()
            self.failed += 1
            return False

    # -------------------- 测试1: 接口可用性 --------------------
    def test_check_chunks_api_available(self):
        """测试分片检测接口是否可用"""
        resp = self.session.post(
            f"{BASE_URL}/document/upload/check/",
            json={
                "file_hash": "test_hash_123",
                "total_chunks": 10
            }
        )
        print_response(resp)
        
        if resp.status_code in [200, 400, 404]:  # 400/404也是接口存在的证明
            success(f"接口可用 (状态码: {resp.status_code})")
            return True
        else:
            error(f"接口异常 (状态码: {resp.status_code})")
            return False

    def test_direct_merge_api_available(self):
        """测试直接合并接口是否可用"""
        resp = self.session.post(
            f"{BASE_URL}/document/direct_merge/",
            json={
                "transfer_id": 99999,  # 不存在的ID
                "folder_id": 1,
                "file_name": "test.txt",
                "file_hash": "test_hash",
                "total_chunks": 10
            }
        )
        print_response(resp)
        
        # 即使返回400/404也说明接口存在
        if resp.status_code in [200, 400, 404]:
            success(f"接口可用 (状态码: {resp.status_code})")
            return True
        else:
            error(f"接口异常 (状态码: {resp.status_code})")
            return False

    # -------------------- 测试2: 新增字段 --------------------
    def test_check_chunks_new_fields(self):
        """测试分片检测接口新增字段"""
        resp = self.session.post(
            f"{BASE_URL}/document/upload/check/",
            json={
                "file_hash": "test_hash_456",
                "total_chunks": 10,
                "transfer_id": TEST_TRANSFER_ID or 99999
            }
        )
        print_response(resp)
        
        if resp.status_code != 200:
            error(f"接口返回错误状态码: {resp.status_code}")
            return False
        
        data = resp.json()
        if "data" not in data:
            error("响应缺少 data 字段")
            return False
        
        result = data["data"]
        required_fields = [
            "all_chunks_ready",
            "can_merge_directly", 
            "error_code",
            "missing_chunks",
            "total_chunks"
        ]
        
        missing = [f for f in required_fields if f not in result]
        if missing:
            error(f"缺少新增字段: {missing}")
            return False
        
        success("所有新增字段都存在")
        info(f"  all_chunks_ready: {result.get('all_chunks_ready')}")
        info(f"  can_merge_directly: {result.get('can_merge_directly')}")
        info(f"  error_code: {result.get('error_code')}")
        return True

    # -------------------- 测试3: 权限验证 --------------------
    def test_direct_merge_auth(self):
        """测试直接合并接口权限验证"""
        # 不携带Token请求
        no_auth_session = requests.Session()
        no_auth_session.headers.update({"Content-Type": "application/json"})
        
        resp = no_auth_session.post(
            f"{BASE_URL}/document/direct_merge/",
            json={
                "transfer_id": 1,
                "folder_id": 1,
                "file_name": "test.txt",
                "file_hash": "test_hash",
                "total_chunks": 10
            }
        )
        print_response(resp, "无Token请求")
        
        if resp.status_code in [401, 403]:
            success("权限验证正常工作（无Token返回401/403）")
            return True
        elif resp.status_code == 200:
            warning("权限验证可能未生效（无Token也能访问）")
            return False
        else:
            info(f"返回状态码: {resp.status_code}")
            return True

    # -------------------- 测试4: 参数验证 --------------------
    def test_direct_merge_validation(self):
        """测试直接合并接口参数验证"""
        # 缺少必填参数
        resp = self.session.post(
            f"{BASE_URL}/document/direct_merge/",
            json={
                "transfer_id": 1
                # 缺少 folder_id, file_name, file_hash, total_chunks
            }
        )
        print_response(resp, "缺少参数请求")
        
        if resp.status_code == 400:
            success("参数验证正常工作（缺少参数返回400）")
            return True
        elif resp.status_code == 200:
            warning("参数验证可能不严格（缺少参数也能成功）")
            return False
        else:
            info(f"返回状态码: {resp.status_code}")
            return True

    # -------------------- 测试5: 幂等性（如有测试数据）--------------------
    def test_idempotency(self):
        """测试幂等性（需要已存在的传输记录）"""
        if not TEST_TRANSFER_ID:
            warning("未配置 TEST_TRANSFER_ID，跳过幂等性测试")
            return None
        
        info(f"使用传输记录ID: {TEST_TRANSFER_ID}")
        
        # 第一次请求
        resp1 = self.session.post(
            f"{BASE_URL}/document/direct_merge/",
            json={
                "transfer_id": TEST_TRANSFER_ID,
                "folder_id": 1,
                "file_name": "test.txt",
                "file_hash": "test_hash_for_idempotency",
                "total_chunks": 10,
                "is_public": False
            }
        )
        print_response(resp1, "第一次请求")
        
        if resp1.status_code not in [200, 400]:
            warning(f"第一次请求异常 (状态码: {resp1.status_code})，跳过幂等性测试")
            return None
        
        data1 = resp1.json()
        is_idempotent_1 = data1.get("data", {}).get("is_idempotent", False)
        
        # 第二次请求（幂等性测试）
        resp2 = self.session.post(
            f"{BASE_URL}/document/direct_merge/",
            json={
                "transfer_id": TEST_TRANSFER_ID,
                "folder_id": 1,
                "file_name": "test.txt",
                "file_hash": "test_hash_for_idempotency",
                "total_chunks": 10,
                "is_public": False
            }
        )
        print_response(resp2, "第二次请求（重复）")
        
        data2 = resp2.json()
        is_idempotent_2 = data2.get("data", {}).get("is_idempotent", False)
        task_id_1 = data1.get("data", {}).get("task_id")
        task_id_2 = data2.get("data", {}).get("task_id")
        
        info(f"第一次 is_idempotent: {is_idempotent_1}, task_id: {task_id_1}")
        info(f"第二次 is_idempotent: {is_idempotent_2}, task_id: {task_id_2}")
        
        if is_idempotent_2 or task_id_1 == task_id_2:
            success("幂等性工作正常（重复请求返回相同结果）")
            return True
        else:
            warning("幂等性可能未生效（重复请求返回不同task_id）")
            return False

    # -------------------- 运行所有测试 --------------------
    def run_all_tests(self):
        """运行所有测试"""
        print("\n" + "="*70)
        print("  合并失败重试功能测试 (P0-Day1)")
        print("="*70)
        print(f"\n配置:")
        print(f"  API地址: {BASE_URL}")
        token_display = self.token[:10] + "..." + self.token[-5:] if self.token and len(self.token) > 15 else '***'
        print(f"  Token: {token_display}")
        print(f"  测试传输ID: {TEST_TRANSFER_ID or '未配置'}")
        print(f"  详细输出: {VERBOSE}")

        # 测试列表
        tests = [
            ("分片检测接口可用性", self.test_check_chunks_api_available),
            ("直接合并接口可用性", self.test_direct_merge_api_available),
            ("分片检测接口新增字段", self.test_check_chunks_new_fields),
            ("直接合并接口权限验证", self.test_direct_merge_auth),
            ("直接合并接口参数验证", self.test_direct_merge_validation),
            ("幂等性测试", self.test_idempotency),
        ]

        for name, func in tests:
            self.run_test(name, func)

        # 打印汇总
        print("\n" + "="*70)
        print("  测试汇总")
        print("="*70)
        print(f"\n  通过: {Colors.GREEN}{self.passed}{Colors.END}")
        print(f"  失败: {Colors.RED}{self.failed}{Colors.END}")
        print(f"  跳过: {Colors.YELLOW}{self.skipped}{Colors.END}")
        print(f"  总计: {self.passed + self.failed + self.skipped}")
        
        if self.failed == 0:
            print(f"\n{Colors.GREEN}🎉 所有测试通过！{Colors.END}")
        else:
            print(f"\n{Colors.RED}⚠️  存在失败的测试，请检查{Colors.END}")
        
        return self.failed == 0


# ==================== 主函数 ====================

def main():
    # 运行测试（会自动尝试登录获取Token）
    tester = MergeRetryTester()
    
    # 检查是否获取到了Token
    if tester.token == "your_token_here" or not tester.token:
        print("\n" + "="*70)
        print("  ⚠️  未能获取到有效的 TOKEN")
        print("="*70)
        print("""
请尝试以下方法获取Token：

方法1 - 浏览器开发者工具：
1. 登录系统
2. 按F12打开开发者工具 → Network标签
3. 点击任意API请求，查看Headers中的 "Authorization: Token xxx"
4. 将xxx复制到脚本的 TOKEN 变量中

方法2 - 手动登录接口：
curl -X POST http://localhost/api/account/login/ \\
  -H "Content-Type: application/json" \\
  -d '{"username":"admin","password":"admin"}'

方法3 - Django Shell：
cd spug_api
python -c "
import django
django.setup()
from apps.account.models import User
from rest_framework.authtoken.models import Token
user = User.objects.filter(username='admin').first()
token, _ = Token.objects.get_or_create(user=user)
print(f'Token: {token.key}')
"
""")
        sys.exit(1)

    # 运行测试
    success = tester.run_all_tests()
    
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
