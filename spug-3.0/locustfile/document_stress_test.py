#!/usr/bin/env python
"""
资料库模块压力测试脚本

测试场景：
1. 文件夹操作：创建、查询、删除
2. 文件操作：上传、查询、删除
3. 搜索操作：关键词搜索
4. 回收站操作：查询、恢复

使用方法：
    
    python -m locust -f locustfile/document_stress_test.py -H http://localhost
"""

import os
import random
import uuid
import time
from datetime import datetime
from locust import HttpUser, task, between, events
from locust.runners import MasterRunner

# 测试配置
TEST_CONFIG = {
    'users': [
        {'username': 'tongxinke', 'password': 'Dt@6299093'},
        {'username': 'zidonghuake', 'password': 'Aa@123456'},
        {'username': 'daohangke', 'password': 'Aa@123456'},
        {'username': 'dianhuake', 'password': 'Aa@123456'}
    ],
    # 测试文件大小配置（字节）
    'file_sizes': {
        'small': 1024 * 10,      # 10KB
        'medium': 1024 * 500,    # 500KB
        'large': 1024 * 1024 * 2 # 2MB
    }
}


class DocumentUser(HttpUser):
    """资料库模块压力测试用户"""
    
    # 等待时间：1-3秒之间
    wait_time = between(1, 3)
    
    def on_start(self):
        """用户开始时登录"""
        if not self.login():
            # 如果登录失败，抛出异常停止该用户
            raise Exception(f"用户 {self.username} 登录失败")
        self.test_folder_ids = []
        self.test_file_ids = []
    
    def on_stop(self):
        """用户结束时清理测试数据"""
        try:
            self.cleanup_test_data()
            self.logout()
        except:
            pass
    
    def login(self):
        """登录获取token"""
        user = random.choice(TEST_CONFIG['users'])
        self.username = user['username']
        self.password = user['password']
        
        response = self.client.post('/api/account/login/', json={
            'username': self.username,
            'password': self.password,
            'type': 'default'
        })
        
        if response.status_code == 200:
            data = response.json()
            # 检查返回数据，响应格式: {"data": {...}, "error": ""}
            if data.get('error'):
                print(f"[{self.username}] 登录失败: {data['error']}")
                return False

            # 尝试获取access_token（在data字段中）
            response_data = data.get('data', {})
            if 'access_token' in response_data:
                self.token = response_data['access_token']
            else:
                # 如果没有access_token，可能是其他问题
                print(f"[{self.username}] 登录响应异常: {data}")
                return False

            # 使用 x-token header（Spug 系统使用 X-Token 而不是 Authorization）
            self.client.headers.update({'x-token': self.token})
            print(f"[{self.username}] 登录成功")
            return True
        else:
            print(f"[{self.username}] 登录失败 (HTTP {response.status_code}): {response.text}")
            return False
    
    def logout(self):
        """登出"""
        self.client.delete('/api/account/logout/')
    
    def generate_test_file(self, size='small'):
        """生成测试文件内容"""
        file_size = TEST_CONFIG['file_sizes'].get(size, TEST_CONFIG['file_sizes']['small'])
        return 'x' * file_size
    
    def cleanup_test_data(self):
        """清理测试数据"""
        # 清理测试文件
        for file_id in self.test_file_ids:
            try:
                self.client.get(f'/api/document/file/?id={file_id}&is_public=False')
            except:
                pass
        
        # 清理测试文件夹
        for folder_id in self.test_folder_ids:
            try:
                self.client.delete(f'/api/document/folder/?id={folder_id}&is_public=False')
            except:
                pass
    
    # ========== 文件夹操作 ==========
    
    @task(5)
    def create_folder(self):
        """创建文件夹"""
        folder_name = f"test_{self.username}_{uuid.uuid4().hex[:8]}"
        
        with self.client.post(
            '/api/document/folder/',
            json={'name': folder_name, 'is_public': False},
            catch_response=True,
            name="/api/document/folder/ [POST] 创建文件夹"
        ) as response:
            if response.status_code == 200:
                folder_id = response.json().get('id')
                if folder_id:
                    self.test_folder_ids.append(folder_id)
            else:
                response.failure(f"创建文件夹失败: {response.text}")
    
    @task(10)
    def list_folders(self):
        """查询文件夹列表"""
        self.client.get(
            '/api/document/folder/?is_public=False',
            name="/api/document/folder/ [GET] 查询文件夹"
        )
    
    @task(3)
    def list_root_contents(self):
        """查询根目录内容"""
        self.client.get(
            '/api/document/folder/?is_public=False&page=1&page_size=100',
            name="/api/document/folder/ [GET] 查询根目录"
        )
    
    @task(2)
    def search_folders(self):
        """搜索文件夹"""
        self.client.get(
            f'/api/document/folder/search/?q={self.username}',
            name="/api/document/folder/search/ [GET] 搜索文件夹"
        )
    
    # ========== 文件操作 ==========
    
    @task(8)
    def upload_file(self):
        """上传文件（模拟小文件）"""
        if not self.test_folder_ids:
            # 如果没有测试文件夹，上传到根目录
            parent_id = None
        else:
            parent_id = random.choice(self.test_folder_ids)
        
        file_name = f"test_{self.username}_{uuid.uuid4().hex[:8]}.txt"
        file_content = self.generate_test_file('small')
        
        files = {'file': (file_name, file_content, 'text/plain')}
        data = {
            'parent_id': parent_id,
            'is_public': False
        }
        
        with self.client.post(
            '/api/document/upload/',
            files=files,
            data=data,
            catch_response=True,
            name="/api/document/upload/ [POST] 上传文件"
        ) as response:
            if response.status_code == 200:
                file_id = response.json().get('id')
                if file_id:
                    self.test_file_ids.append(file_id)
            else:
                response.failure(f"上传文件失败: {response.text}")

    @task(4)
    def delete_file(self):
        """删除文件"""
        if self.test_file_ids:
            file_id = self.test_file_ids.pop(0)
            
            with self.client.delete(
                f'/api/document/file/?id={file_id}&is_public=False',
                catch_response=True,
                name="/api/document/file/ [DELETE] 删除文件"
            ) as response:
                if response.status_code != 200:
                    # 失败时重新加入队列
                    self.test_file_ids.append(file_id)
                    response.failure(f"删除文件失败: {response.text}")
    
    @task(3)
    def rename_file(self):
        """重命名文件"""
        if self.test_file_ids:
            file_id = random.choice(self.test_file_ids)
            new_name = f"renamed_{self.username}_{uuid.uuid4().hex[:8]}.txt"
            
            self.client.post(
                '/api/document/file/rename/',
                json={'id': file_id, 'name': new_name, 'is_public': False},
                name="/api/document/file/rename/ [POST] 重命名文件"
            )
    
    # ========== 磁盘使用 ==========
    
    @task(5)
    def get_disk_usage(self):
        """查询磁盘使用情况"""
        self.client.get(
            '/api/document/disk_usage/?is_public=False',
            name="/api/document/disk_usage/ [GET] 查询磁盘使用"
        )
    
    # ========== 回收站操作 ==========
    
    @task(4)
    def list_recycle_bin(self):
        """查询回收站"""
        self.client.get(
            '/api/document/recycle-bin/?page=1&page_size=50',
            name="/api/document/recycle-bin/ [GET] 查询回收站"
        )
    
    @task(2)
    def get_recycle_bin_stats(self):
        """查询回收站统计"""
        self.client.get(
            '/api/document/recycle-bin/stats/',
            name="/api/document/recycle-bin/stats/ [GET] 回收站统计"
        )
    
    @task(1)
    def restore_item(self):
        """恢复回收站项目"""
        # 先获取回收站列表
        response = self.client.get('/api/document/recycle-bin/?page=1&page_size=10')
        if response.status_code == 200:
            items = response.json().get('items', [])
            if items and len(items) > 0:
                item = random.choice(items)
                item_type = item.get('type', 'file')
                item_id = item.get('id')
                
                if item_type == 'folder':
                    self.client.post(
                        '/api/document/recycle-bin/folder-restore/',
                        json={'id': item_id},
                        name="/api/document/recycle-bin/folder-restore/ [POST] 恢复文件夹"
                    )
                else:
                    self.client.post(
                        '/api/document/recycle-bin/restore/',
                        json={'id': item_id},
                        name="/api/document/recycle-bin/restore/ [POST] 恢复文件"
                    )


class AdminUser(HttpUser):
    """管理员用户 - 用于更高级的操作"""
    
    wait_time = between(2, 5)
    
    def on_start(self):
        """登录管理员账号"""
        response = self.client.post('/api/account/login/', json={
            'username': 'admin',
            'password': 'Admin888',
            'type': 'default'
        })
        
        if response.status_code == 200:
            data = response.json()
            if data.get('error'):
                print(f"[Admin] 登录失败: {data['error']}")
                raise Exception("管理员登录失败")
            
            response_data = data.get('data', {})
            if 'access_token' in response_data:
                self.token = response_data['access_token']
                self.client.headers.update({'x-token': self.token})
                print("[Admin] 登录成功")
            else:
                print(f"[Admin] 登录响应异常: {data}")
                raise Exception("管理员登录响应异常")
        else:
            print(f"[Admin] 登录失败 (HTTP {response.status_code}): {response.text}")
            raise Exception("管理员登录失败")
    
    @task(10)
    def view_all_folders(self):
        """查看所有文件夹"""
        self.client.get('/api/document/folder/?is_public=False&all=true')
    
    @task(5)
    def view_transfers(self):
        """查看传输记录"""
        self.client.get('/api/document/transfers/')
    
    @task(3)
    def permanent_delete_item(self):
        """永久删除回收站项目"""
        response = self.client.get('/api/document/recycle-bin/?page=1&page_size=5')
        if response.status_code == 200:
            items = response.json().get('items', [])
            if items and len(items) > 0:
                item = random.choice(items)
                item_type = item.get('type', 'file')
                item_id = item.get('id')
                
                if item_type == 'folder':
                    self.client.post(
                        '/api/document/recycle-bin/folder-permanent/',
                        json={'id': item_id}
                    )
                else:
                    self.client.post(
                        '/api/document/recycle-bin/permanent/',
                        json={'id': item_id}
                    )


# ========== 测试事件监听 ==========

@events.test_start.add_listener
def on_test_start(environment, **kwargs):
    """测试开始"""
    print("\n" + "="*70)
    print("  资料库模块压力测试开始")
    print("="*70)
    print(f"  开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*70 + "\n")


@events.test_stop.add_listener
def on_test_stop(environment, **kwargs):
    """测试结束"""
    print("\n" + "="*70)
    print("  资料库模块压力测试结束")
    print("="*70)
    print(f"  结束时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    if environment.stats.total.fail_ratio > 0:
        print(f"  ⚠️  总失败率: {environment.stats.total.fail_ratio:.2%}")
    else:
        print(f"  ✓ 所有请求成功")
    
    print(f"  总请求数: {environment.stats.total.num_requests}")
    print(f"  平均响应时间: {environment.stats.total.avg_response_time:.2f}ms")
    print(f"  RPS (每秒请求数): {environment.stats.total.total_rps:.2f}")
    print("="*70 + "\n")


# ========== 命令行参数 ==========

if __name__ == '__main__':
    import sys
    
    print("="*70)
    print("  资料库模块压力测试 - Locust")
    print("="*70)
    print("\n使用方法:")
    print("  1. Web UI模式（推荐）:")
    print("     locust -f locustfile/document_stress_test.py --host=http://localhost")
    print("\n  2. 命令行模式（无头运行）:")
    print("     locust -f locustfile/document_stress_test.py --headless")
    print("            --host=http://localhost")
    print("            --users=100")
    print("            --spawn-rate=10")
    print("            --run-time=5m")
    print("\n  3. 分布式模式（Master）:")
    print("     locust -f locustfile/document_stress_test.py --master")
    print("            --host=http://localhost")
    print("\n  4. 分布式模式（Worker）:")
    print("     locust -f locustfile/document_stress_test.py --worker")
    print("            --master-host=<master-ip>")
    print("\n" + "="*70)
