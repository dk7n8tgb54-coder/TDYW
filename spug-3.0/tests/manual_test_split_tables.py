# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""
文档管理分表改造 - 手动API测试脚本
使用Postman/ApiPost或curl测试所有接口
"""
import requests
import json
import os
import hashlib

# ==================== 配置 ====================
BASE_URL = 'http://localhost:8000/api'  # 修改为你的API地址
ADMIN_TOKEN = 'your_admin_token_here'  # 修改为管理员token
USER1_TOKEN = 'your_user1_token_here'  # 修改为user1的token
USER2_TOKEN = 'your_user2_token_here'  # 修改为user2的token

# ==================== 工具函数 ====================
def make_headers(token):
    return {
        'X-Token': token,
        'X-Forwarded-For': '127.0.0.1',
        'Content-Type': 'application/json'
    }

def print_result(test_name, response):
    """打印测试结果"""
    print(f"\n{'=' * 60}")
    print(f"测试: {test_name}")
    print(f"{'=' * 60}")
    print(f"状态码: {response.status_code}")
    print(f"响应: {json.dumps(response.json(), ensure_ascii=False, indent=2)}")
    return response.json()

# ==================== 测试用例 ====================
def test_01_folder_create_private():
    """测试1: 创建私有文件夹"""
    print("\n【测试1】创建私有文件夹")
    response = requests.post(
        f'{BASE_URL}/document/folder/',
        headers=make_headers(USER1_TOKEN),
        json={
            'name': '私有文件夹1',
            'parent_id': None,
            'is_public': False
        }
    )
    data = print_result("创建私有文件夹", response)
    assert response.status_code == 200, "创建私有文件夹失败"
    assert data.get('error') is None, f"创建私有文件夹错误: {data.get('error')}"
    return data.get('data', {}).get('id')

def test_02_folder_create_public():
    """测试2: 创建公共文件夹"""
    print("\n【测试2】创建公共文件夹")
    response = requests.post(
        f'{BASE_URL}/document/folder/',
        headers=make_headers(USER1_TOKEN),
        json={
            'name': '公共文件夹1',
            'parent_id': None,
            'is_public': True
        }
    )
    data = print_result("创建公共文件夹", response)
    assert response.status_code == 200, "创建公共文件夹失败"
    assert data.get('error') is None, f"创建公共文件夹错误: {data.get('error')}"
    return data.get('data', {}).get('id')

def test_03_folder_list_private():
    """测试3: 获取私有文件夹列表"""
    print("\n【测试3】获取私有文件夹列表")
    response = requests.get(
        f'{BASE_URL}/document/folder/',
        headers=make_headers(USER1_TOKEN),
        params={'is_public': False}
    )
    data = print_result("获取私有文件夹列表", response)
    assert response.status_code == 200, "获取私有文件夹列表失败"
    return data.get('data', {}).get('folders', [])

def test_04_folder_list_public():
    """测试4: 获取公共文件夹列表"""
    print("\n【测试4】获取公共文件夹列表")
    response = requests.get(
        f'{BASE_URL}/document/folder/',
        headers=make_headers(USER1_TOKEN),
        params={'is_public': True}
    )
    data = print_result("获取公共文件夹列表", response)
    assert response.status_code == 200, "获取公共文件夹列表失败"
    return data.get('data', {}).get('folders', [])

def test_05_folder_isolation():
    """测试5: 验证文件夹空间隔离"""
    print("\n【测试5】验证文件夹空间隔离")
    print("user1的私有文件夹，user2不应该能看到")

    # user1 创建私有文件夹
    response1 = requests.post(
        f'{BASE_URL}/document/folder/',
        headers=make_headers(USER1_TOKEN),
        json={
            'name': 'user1私有',
            'parent_id': None,
            'is_public': False
        }
    )
    folder_id = response1.json().get('data', {}).get('id')

    # user2 尝试获取私有文件夹列表
    response2 = requests.get(
        f'{BASE_URL}/document/folder/',
        headers=make_headers(USER2_TOKEN),
        params={'is_public': False}
    )
    data2 = print_result("user2获取私有文件夹列表", response2)
    folder_ids = [f['id'] for f in data2.get('data', {}).get('folders', [])]
    assert folder_id not in folder_ids, "空间隔离失败: user2看到了user1的私有文件夹"

def test_06_folder_permission():
    """测试6: 测试公共文件夹权限"""
    print("\n【测试6】测试公共文件夹权限")

    # user1 创建公共文件夹
    response = requests.post(
        f'{BASE_URL}/document/folder/',
        headers=make_headers(USER1_TOKEN),
        json={
            'name': '要删除的公共文件夹',
            'parent_id': None,
            'is_public': True
        }
    )
    folder_id = response.json().get('data', {}).get('id')

    # user2 尝试删除user1的公共文件夹（应该失败）
    response = requests.delete(
        f'{BASE_URL}/document/folder/',
        headers=make_headers(USER2_TOKEN),
        params={'id': folder_id, 'is_public': True}
    )
    data = print_result("user2尝试删除公共文件夹", response)
    assert response.status_code == 200
    assert data.get('error') is not None, "权限校验失败: user2应该无法删除user1的公共文件夹"
    assert '无权限' in data.get('error', ''), "错误信息不正确"

    # 管理员删除公共文件夹（应该成功）
    response = requests.delete(
        f'{BASE_URL}/document/folder/',
        headers=make_headers(ADMIN_TOKEN),
        params={'id': folder_id, 'is_public': True}
    )
    data = print_result("管理员删除公共文件夹", response)
    assert response.status_code == 200
    assert data.get('error') is None, "管理员删除失败"

def test_07_file_upload_private():
    """测试7: 上传文件到私有空间"""
    print("\n【测试7】上传文件到私有空间")

    # 创建测试文件
    test_file_path = 'test_private.txt'
    with open(test_file_path, 'w', encoding='utf-8') as f:
        f.write('这是私有文件内容')

    files = {'file': open(test_file_path, 'rb', encoding=None)}
    data = {
        'folder_id': '',
        'is_public': 'false'
    }

    response = requests.post(
        f'{BASE_URL}/document/upload/',
        headers={'X-Token': USER1_TOKEN, 'X-Forwarded-For': '127.0.0.1'},
        files=files,
        data=data
    )

    # 清理测试文件
    os.remove(test_file_path)

    result = print_result("上传文件到私有空间", response)
    assert response.status_code == 200, "上传文件失败"
    assert result.get('error') is None, f"上传文件错误: {result.get('error')}"

def test_08_file_upload_public():
    """测试8: 上传文件到公共空间"""
    print("\n【测试8】上传文件到公共空间")

    # 创建测试文件
    test_file_path = 'test_public.txt'
    with open(test_file_path, 'w', encoding='utf-8') as f:
        f.write('这是公共文件内容')

    files = {'file': open(test_file_path, 'rb', encoding=None)}
    data = {
        'folder_id': '',
        'is_public': 'true'
    }

    response = requests.post(
        f'{BASE_URL}/document/upload/',
        headers={'X-Token': USER1_TOKEN, 'X-Forwarded-For': '127.0.0.1'},
        files=files,
        data=data
    )

    # 清理测试文件
    os.remove(test_file_path)

    result = print_result("上传文件到公共空间", response)
    assert response.status_code == 200, "上传文件失败"
    assert result.get('error') is None, f"上传文件错误: {result.get('error')}"

def test_09_quick_upload_check():
    """测试9: 秒传检查"""
    print("\n【测试9】秒传检查")

    # 创建测试文件并计算MD5
    test_file_path = 'test_quick.txt'
    content = b'Quick upload test content'
    with open(test_file_path, 'wb') as f:
        f.write(content)

    file_md5 = hashlib.md5(content).hexdigest()
    file_size = len(content)

    # 私有空间秒传检查
    response = requests.post(
        f'{BASE_URL}/document/check_file/',
        headers=make_headers(USER1_TOKEN),
        json={
            'file_hash': file_md5,
            'file_size': file_size,
            'is_public': False
        }
    )
    print_result("私有空间秒传检查", response)
    assert response.status_code == 200

    # 公共空间秒传检查
    response = requests.post(
        f'{BASE_URL}/document/check_file/',
        headers=make_headers(USER1_TOKEN),
        json={
            'file_hash': file_md5,
            'file_size': file_size,
            'is_public': True
        }
    )
    print_result("公共空间秒传检查", response)
    assert response.status_code == 200

    # 清理测试文件
    os.remove(test_file_path)

def test_10_path_traversal():
    """测试10: 路径遍历攻击防护"""
    print("\n【测试10】路径遍历攻击防护")

    # 尝试创建包含路径遍历的文件夹
    response = requests.post(
        f'{BASE_URL}/document/folder/',
        headers=make_headers(USER1_TOKEN),
        json={
            'name': '../../../etc/passwd',
            'parent_id': None,
            'is_public': False
        }
    )
    data = print_result("路径遍历攻击防护测试", response)
    assert response.status_code == 200
    assert data.get('error') is not None, "路径遍历防护失败: 应该拒绝非法文件名"

    # 尝试创建包含脚本标签的文件夹
    response = requests.post(
        f'{BASE_URL}/document/folder/',
        headers=make_headers(USER1_TOKEN),
        json={
            'name': 'test<script>alert(1)</script>',
            'parent_id': None,
            'is_public': False
        }
    )
    data = print_result("XSS攻击防护测试", response)
    assert response.status_code == 200
    assert data.get('error') is not None, "XSS防护失败: 应该拒绝非法文件名"

def test_11_file_operations():
    """测试11: 文件操作（移动/重命名/删除）"""
    print("\n【测试11】文件操作")

    # 先上传一个文件
    test_file_path = 'test_operations.txt'
    with open(test_file_path, 'w', encoding='utf-8') as f:
        f.write('测试文件操作')

    files = {'file': open(test_file_path, 'rb', encoding=None)}
    data = {'folder_id': '', 'is_public': 'false'}
    response = requests.post(
        f'{BASE_URL}/document/upload/',
        headers={'X-Token': USER1_TOKEN, 'X-Forwarded-For': '127.0.0.1'},
        files=files,
        data=data
    )
    os.remove(test_file_path)

    # 获取文件列表，找到文件ID
    response = requests.get(
        f'{BASE_URL}/document/folder/',
        headers=make_headers(USER1_TOKEN),
        params={'is_public': False}
    )
    files_data = response.json().get('data', {}).get('files', [])
    if files_data:
        file_id = files_data[0]['id']

        # 重命名文件
        response = requests.post(
            f'{BASE_URL}/document/file/rename/',
            headers=make_headers(USER1_TOKEN),
            json={
                'id': file_id,
                'name': '重命名后的文件.txt',
                'is_public': False
            }
        )
        print_result("重命名文件", response)
        assert response.status_code == 200

def test_12_disk_usage():
    """测试12: 磁盘使用率"""
    print("\n【测试12】磁盘使用率")

    # 私有空间磁盘使用率
    response = requests.get(
        f'{BASE_URL}/document/disk_usage/',
        headers=make_headers(USER1_TOKEN),
        params={'is_public': False}
    )
    data = print_result("私有空间磁盘使用率", response)
    assert response.status_code == 200
    assert data.get('data', {}).get('is_public') == False

    # 公共空间磁盘使用率
    response = requests.get(
        f'{BASE_URL}/document/disk_usage/',
        headers=make_headers(USER1_TOKEN),
        params={'is_public': True}
    )
    data = print_result("公共空间磁盘使用率", response)
    assert response.status_code == 200
    assert data.get('data', {}).get('is_public') == True

def test_13_folder_tree():
    """测试13: 文件夹树形结构"""
    print("\n【测试13】文件夹树形结构")

    # 创建多层文件夹结构
    response1 = requests.post(
        f'{BASE_URL}/document/folder/',
        headers=make_headers(USER1_TOKEN),
        json={
            'name': '根文件夹',
            'parent_id': None,
            'is_public': False
        }
    )
    root_id = response1.json().get('data', {}).get('id')

    response2 = requests.post(
        f'{BASE_URL}/document/folder/',
        headers=make_headers(USER1_TOKEN),
        json={
            'name': '子文件夹1',
            'parent_id': root_id,
            'is_public': False
        }
    )

    response3 = requests.post(
        f'{BASE_URL}/document/folder/',
        headers=make_headers(USER1_TOKEN),
        json={
            'name': '子文件夹2',
            'parent_id': root_id,
            'is_public': False
        }
    )

    # 获取所有文件夹（用于构建树）
    response = requests.get(
        f'{BASE_URL}/document/folder/',
        headers=make_headers(USER1_TOKEN),
        params={'all': True, 'is_public': False}
    )
    data = print_result("获取文件夹树", response)
    assert response.status_code == 200
    folders = data.get('data', [])
    assert len(folders) >= 3, "文件夹树获取失败"

def test_14_large_file_name():
    """测试14: 长文件名边界测试"""
    print("\n【测试14】长文件名边界测试")

    # 创建255字符文件名
    long_name = 'a' * 255
    response = requests.post(
        f'{BASE_URL}/document/folder/',
        headers=make_headers(USER1_TOKEN),
        json={
            'name': long_name,
            'parent_id': None,
            'is_public': False
        }
    )
    data = print_result("长文件名测试", response)
    assert response.status_code == 200

    # 创建256字符文件名（应该失败）
    too_long_name = 'b' * 256
    response = requests.post(
        f'{BASE_URL}/document/folder/',
        headers=make_headers(USER1_TOKEN),
        json={
            'name': too_long_name,
            'parent_id': None,
            'is_public': False
        }
    )
    data = print_result("过长文件名测试", response)
    assert data.get('error') is not None, "应该拒绝过长的文件名"

def test_15_special_characters():
    """测试15: 特殊字符处理"""
    print("\n【测试15】特殊字符处理")

    # 测试合法的特殊字符
    legal_names = [
        '测试文件名.txt',
        'test-file.txt',
        'test_file.txt',
        'test file.txt',
        '文件名(1).txt',
        '文件名[1].txt'
    ]

    for name in legal_names:
        response = requests.post(
            f'{BASE_URL}/document/folder/',
            headers=make_headers(USER1_TOKEN),
            json={
                'name': name,
                'parent_id': None,
                'is_public': False
            }
        )
        assert response.status_code == 200, f"合法文件名被拒绝: {name}"

    print("✓ 合法特殊字符测试通过")

    # 测试非法的特殊字符
    illegal_names = [
        'test/file.txt',
        'test\\file.txt',
        'test:file.txt',
        'test*file.txt',
        'test?file.txt',
        'test"file.txt',
        'test<file.txt',
        'test>file.txt',
        'test|file.txt'
    ]

    for name in illegal_names:
        response = requests.post(
            f'{BASE_URL}/document/folder/',
            headers=make_headers(USER1_TOKEN),
            json={
                'name': name,
                'parent_id': None,
                'is_public': False
            }
        )
        data = response.json()
        assert data.get('error') is not None, f"非法文件名未被拒绝: {name}"

    print("✓ 非法特殊字符测试通过")

# ==================== 主测试流程 ====================
def run_all_tests():
    """运行所有测试"""
    print("=" * 60)
    print("文档管理分表改造 - 手动API测试")
    print("=" * 60)
    print(f"API地址: {BASE_URL}")
    print("=" * 60)

    tests = [
        ("创建私有文件夹", test_01_folder_create_private),
        ("创建公共文件夹", test_02_folder_create_public),
        ("获取私有文件夹列表", test_03_folder_list_private),
        ("获取公共文件夹列表", test_04_folder_list_public),
        ("验证文件夹空间隔离", test_05_folder_isolation),
        ("测试公共文件夹权限", test_06_folder_permission),
        ("上传文件到私有空间", test_07_file_upload_private),
        ("上传文件到公共空间", test_08_file_upload_public),
        ("秒传检查", test_09_quick_upload_check),
        ("路径遍历攻击防护", test_10_path_traversal),
        ("文件操作", test_11_file_operations),
        ("磁盘使用率", test_12_disk_usage),
        ("文件夹树形结构", test_13_folder_tree),
        ("长文件名边界测试", test_14_large_file_name),
        ("特殊字符处理", test_15_special_characters),
    ]

    passed = 0
    failed = 0
    errors = []

    for test_name, test_func in tests:
        try:
            test_func()
            print(f"✅ {test_name} - 通过")
            passed += 1
        except Exception as e:
            print(f"❌ {test_name} - 失败: {str(e)}")
            failed += 1
            errors.append((test_name, str(e)))

    print("\n" + "=" * 60)
    print("测试总结")
    print("=" * 60)
    print(f"通过: {passed}/{len(tests)}")
    print(f"失败: {failed}/{len(tests)}")
    print("=" * 60)

    if errors:
        print("\n失败详情:")
        for test_name, error in errors:
            print(f"  - {test_name}: {error}")

    print("=" * 60)

    return failed == 0

if __name__ == '__main__':
    import sys

    # 检查配置
    if ADMIN_TOKEN == 'your_admin_token_here':
        print("⚠️  警告: 请先修改脚本中的token配置!")
        print("  - ADMIN_TOKEN")
        print("  - USER1_TOKEN")
        print("  - USER2_TOKEN")
        sys.exit(1)

    success = run_all_tests()
    sys.exit(0 if success else 1)
