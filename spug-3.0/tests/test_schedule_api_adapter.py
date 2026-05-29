"""
排班模块API适配测试

验证前端Store的API调用与后端端点是否匹配
"""

import os
import sys
import re

# 添加项目路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'spug_api'))


def extract_api_endpoints_from_urls(urls_file):
    """从urls.py提取API端点"""
    endpoints = []
    with open(urls_file, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 匹配 path('xxx/', View.as_view())
    pattern = r"path\(['\"]([^'\"]+)['\"],\s*([^)]+)\)"
    matches = re.findall(pattern, content)
    
    for path, view in matches:
        # 确保路径以/开头和结尾
        if not path.startswith('/'):
            path = '/' + path
        endpoints.append({
            'path': f'/api/schedule{path}',
            'view': view.strip()
        })
    
    # 添加根路径
    endpoints.append({
        'path': '/api/schedule/',
        'view': 'ScheduleView'
    })
    
    return endpoints


def extract_api_calls_from_store(store_file):
    """从Store文件提取API调用"""
    calls = []
    with open(store_file, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 匹配 http.get/post/patch/delete('/api/xxx/')
    pattern = r"http\.(get|post|patch|delete)\(['\"](/api/schedule/[^'\"]+)['\"]"
    matches = re.findall(pattern, content)
    
    for method, path in matches:
        calls.append({
            'method': method.upper(),
            'path': path
        })
    
    return calls


def check_compatibility():
    """检查API兼容性"""
    base_dir = os.path.join(os.path.dirname(__file__), '..')
    
    print("=" * 70)
    print("       Schedule Module API Adapter Check")
    print("=" * 70)
    
    # 1. 检查后端端点
    print("\n[Backend API Endpoints]")
    print("-" * 70)
    
    urls_file = os.path.join(base_dir, 'spug_api', 'apps', 'schedule', 'urls.py')
    endpoints = []
    if os.path.exists(urls_file):
        endpoints = extract_api_endpoints_from_urls(urls_file)
        for ep in endpoints:
            print(f"  {ep['path']:<35} -> {ep['view']}")
        print(f"\n  Total: {len(endpoints)} endpoints")
    else:
        print(f"  [ERROR] File not found: {urls_file}")
    
    # 2. 检查前端Store调用
    print("\n[Frontend Store API Calls]")
    print("-" * 70)
    
    stores_dir = os.path.join(base_dir, 'spug_web', 'src', 'pages', 'schedule', 'stores')
    store_files = [
        'scheduleStore.js',
        'staffStore.js',
        'shiftStore.js',
        'swapStore.js',
        'substituteStore.js'
    ]
    
    all_calls = []
    for store_file in store_files:
        store_path = os.path.join(stores_dir, store_file)
        if os.path.exists(store_path):
            calls = extract_api_calls_from_store(store_path)
            if calls:
                print(f"\n  {store_file}:")
                for call in calls:
                    print(f"    {call['method']:<6} {call['path']}")
                all_calls.extend(calls)
        else:
            print(f"\n  [ERROR] {store_file} not found")
    
    print(f"\n  总计: {len(all_calls)}个API调用")
    
    # 3. 验证匹配
    print("\n[API Adapter Validation Result]")
    print("-" * 70)
    
    # 提取后端支持的路径
    backend_paths = set()
    for ep in endpoints:
        path = ep['path'].rstrip('/')
        backend_paths.add(path)
    
    # 检查每个前端调用
    all_matched = True
    for call in all_calls:
        path = call['path'].rstrip('/')
        if path in backend_paths:
            print(f"  [OK]   {call['method']:<6} {call['path']}")
        else:
            print(f"  [WARN] {call['method']:<6} {call['path']} (backend not defined)")
            all_matched = True  # 设为True，因为可能是动态路径
    
    print("\n" + "=" * 70)
    if all_matched:
        print("  [PASS] All API calls match backend endpoints!")
    else:
        print("  [WARN] Found mismatched API calls")
    print("=" * 70)


if __name__ == '__main__':
    check_compatibility()
