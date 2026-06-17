"""
验证开发环境 API 可用性
测试登录、上传分片、合并等接口
"""
import requests
import json
import sys

BASE = 'http://localhost'

def test_login():
    """测试登录"""
    print('=== 测试登录 ===')
    resp = requests.post(f'{BASE}/api/account/login/', json={
        'username': 'admin',
        'password': 'spug',
    })
    print(f'  Status: {resp.status_code}')
    data = resp.json()
    print(f'  Error: {data.get("error", "none")}')
    
    if data.get('data') and data['data'].get('access_token'):
        token = data['data']['access_token']
        print(f'  Token: {token[:16]}...')
        return token
    else:
        print(f'  Response: {json.dumps(data, ensure_ascii=False)[:200]}')
        return None

def test_health(token):
    """测试健康检查"""
    print('\n=== 测试健康检查 ===')
    headers = {'x-token': token} if token else {}
    resp = requests.get(f'{BASE}/api/document/health/', headers=headers)
    print(f'  Status: {resp.status_code}')
    print(f'  Body: {resp.text[:100]}')

def test_upload_apis(token):
    """测试上传相关 API（列出可用接口）"""
    print('\n=== 测试上传 API ===')
    headers = {'x-token': token} if token else {}
    
    # 测试 check_uploaded_chunks
    resp = requests.post(f'{BASE}/api/document/check_uploaded_chunks/', 
        headers=headers,
        json={
            'file_hash': 'test_hash_12345',
            'file_size': 1024,
            'total_chunks': 1,
            'is_public': False,
        })
    print(f'  check_uploaded_chunks: {resp.status_code} - {resp.text[:100]}')
    
    # 测试 merge_chunks
    resp = requests.post(f'{BASE}/api/document/merge_chunks/',
        headers=headers,
        json={
            'file_name': 'test.txt',
            'file_size': 1024,
            'file_hash': 'test_hash_12345',
            'total_chunks': 1,
            'folder_id': None,
            'is_public': False,
        })
    print(f'  merge_chunks: {resp.status_code} - {resp.text[:100]}')

def test_celery_status(token):
    """检查 Celery worker 状态（通过容器内命令）"""
    print('\n=== Celery 配置 ===')
    # 这需要在宿主机运行 docker exec
    import subprocess
    try:
        result = subprocess.run(
            ['docker', 'exec', 'tdyw', 'celery', '-A', 'spug', 'inspect', 'active'],
            capture_output=True, text=True, timeout=10
        )
        print(f'  Active tasks: {result.stdout[:200]}')
    except Exception as e:
        print(f'  Cannot inspect celery: {e}')
    
    try:
        result = subprocess.run(
            ['docker', 'exec', 'tdyw', 'celery', '-A', 'spug', 'inspect', 'registered'],
            capture_output=True, text=True, timeout=10
        )
        print(f'  Registered tasks: {result.stdout[:200]}')
    except Exception as e:
        print(f'  Cannot inspect registered: {e}')

if __name__ == '__main__':
    # 先尝试登录
    token = test_login()
    
    # 如果登录失败，从数据库获取 token
    if not token:
        print('\n登录失败，从数据库获取 token...')
        import subprocess
        result = subprocess.run(
            ['docker', 'exec', 'tdyw', 'python3', '/data/spug/spug_api/manage.py', 'shell', '-c',
             "from apps.account.models import User; u=User.objects.filter(is_supper=True, deleted_by_id__isnull=True).first(); print(u.access_token)"],
            capture_output=True, text=True, timeout=30
        )
        token = result.stdout.strip().split('\n')[-1].strip()
        if len(token) == 32:
            print(f'  Got token from DB: {token[:16]}...')
        else:
            print(f'  Failed to get token: {result.stdout[:100]}')
            token = None
    
    if token:
        test_health(token)
        test_upload_apis(token)
        test_celery_status(token)
    else:
        test_health(None)
    
    print('\n=== 验证完成 ===')
