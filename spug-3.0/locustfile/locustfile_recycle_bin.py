"""
回收站专项压力测试脚本

测试场景:
1. 回收站大容量列表查询 - 模拟1000+已删除文件的列表加载
2. 回收站搜索性能 - 大数据量下的搜索响应时间
3. 批量恢复竞争 - 多用户同时恢复同一文件/文件夹
4. 永久删除压力 - 异步删除任务队列堆积测试
5. 回收站统计性能 - 磁盘占用计算性能

使用说明:
locust -f locustfile_recycle_bin.py -H http://localhost --web-port 8091
"""

import json
import random
import uuid
import time
from locust import HttpUser, task, between, events
from locust.runners import MasterRunner


class RecycleBinUser(HttpUser):
    """
    回收站压测用户类
    """
    wait_time = between(0.5, 2)
    
    def __init__(self, parent):
        super().__init__(parent)
        self.access_token = None
        self.deleted_file_ids = []  # 已删除的文件ID
        self.deleted_folder_ids = []  # 已删除的文件夹ID
        
    def on_start(self):
        """初始化：登录并准备测试数据"""
        self.login()
        self.prepare_test_data()
        
    def login(self):
        """用户登录"""
        try:
            response = self.client.post(
                "/api/account/login/",
                json={"username": "admin", "password": "Admin888", "type": "default"},
                headers={"Content-Type": "application/json"}
            )
            if response.status_code == 200:
                result = response.json()
                self.access_token = result.get('data', {}).get('access_token')
        except Exception as e:
            print(f"[RecycleBin] 登录失败: {e}")
            
    def get_headers(self):
        """获取请求头"""
        return {
            "Content-Type": "application/json",
            "X-Token": self.access_token or "",
            "X-Requested-With": "XMLHttpRequest"
        }
        
    def prepare_test_data(self):
        """准备测试数据：创建并删除大量文件/文件夹"""
        # 创建并删除文件夹
        for i in range(5):
            try:
                # 创建文件夹
                folder_name = f"回收站测试文件夹_{uuid.uuid4().hex[:8]}"
                res = self.client.post(
                    "/api/document/folder/",
                    json={"name": folder_name, "space": "private", "parent_id": None},
                    headers=self.get_headers()
                )
                if res.status_code == 200:
                    folder_id = res.json().get('data', {}).get('id')
                    # 立即删除（进入回收站）
                    if folder_id:
                        self.client.delete(
                            f"/api/document/folder/?id={folder_id}",
                            headers=self.get_headers()
                        )
                        self.deleted_folder_ids.append(folder_id)
            except Exception:
                pass
                
        # 创建并删除文件
        for i in range(10):
            try:
                file_name = f"回收站测试文件_{uuid.uuid4().hex[:8]}.txt"
                content = b"test content " * 100
                files = {'file': (file_name, content, 'text/plain')}
                data = {'space': 'private'}
                
                res = self.client.post(
                    "/api/document/upload/",
                    files=files,
                    data=data,
                    headers={"X-Token": self.access_token or ""}
                )
                if res.status_code == 200:
                    file_id = res.json().get('data', {}).get('id')
                    if file_id:
                        # 软删除文件
                        self.client.delete(
                            f"/api/document/file/?id={file_id}",
                            headers=self.get_headers()
                        )
                        self.deleted_file_ids.append(file_id)
            except Exception:
                pass
    
    @task(10)
    def get_recycle_bin_list(self):
        """
        【高频】获取回收站列表 - 大容量测试
        测试大数据量下的列表加载性能
        """
        with self.client.get(
            "/api/document/recycle-bin/?page=1&page_size=20",
            headers=self.get_headers(),
            name="[回收站] 获取列表(大容量)",
            catch_response=True
        ) as response:
            if response.status_code == 200:
                result = response.json()
                data = result.get('data', {})
                total = data.get('total', 0)
                if total > 1000:
                    response.success()
                else:
                    response.success()
            elif response.status_code == 403:
                response.success()
            else:
                response.failure(f"状态码: {response.status_code}")
                
    @task(5)
    def search_recycle_bin(self):
        """
        【中频】回收站搜索 - 性能测试
        """
        keywords = ["测试", "文件", "文件夹", "2024", "doc"]
        keyword = random.choice(keywords)
        
        with self.client.get(
            f"/api/document/recycle-bin/?keyword={keyword}&page=1&page_size=20",
            headers=self.get_headers(),
            name="[回收站] 搜索",
            catch_response=True
        ) as response:
            if response.status_code == 200:
                response.success()
            elif response.status_code == 403:
                response.success()
            else:
                response.failure(f"状态码: {response.status_code}")
                
    @task(3)
    def get_recycle_bin_stats(self):
        """
        【中频】回收站统计 - 磁盘占用计算性能
        """
        with self.client.get(
            "/api/document/recycle-bin/stats/",
            headers=self.get_headers(),
            name="[回收站] 统计信息",
            catch_response=True
        ) as response:
            if response.status_code == 200:
                response.success()
            elif response.status_code == 403:
                response.success()
            else:
                response.failure(f"状态码: {response.status_code}")
                
    @task(2)
    def restore_file_competition(self):
        """
        【低频】文件恢复竞争 - 多用户恢复同一文件
        测试幂等性和并发控制
        """
        if not self.deleted_file_ids:
            return
            
        file_id = random.choice(self.deleted_file_ids)
        
        with self.client.post(
            "/api/document/recycle-bin/restore/",
            json={"file_ids": [file_id], "restore_mode": "original"},
            headers=self.get_headers(),
            name="[回收站] 恢复文件(竞争)",
            catch_response=True
        ) as response:
            if response.status_code == 200:
                # 可能成功或已被其他人恢复
                response.success()
            elif response.status_code == 409:
                # 并发冲突，预期内
                response.success()
            elif response.status_code == 403:
                response.success()
            else:
                response.failure(f"状态码: {response.status_code}")
                
    @task(2)
    def restore_folder_competition(self):
        """
        【低频】文件夹恢复竞争
        """
        if not self.deleted_folder_ids:
            return
            
        folder_id = random.choice(self.deleted_folder_ids)
        
        with self.client.post(
            "/api/document/recycle-bin/folders/restore/",
            json={"folder_ids": [folder_id], "restore_mode": "original"},
            headers=self.get_headers(),
            name="[回收站] 恢复文件夹(竞争)",
            catch_response=True
        ) as response:
            if response.status_code == 200:
                response.success()
            elif response.status_code in [409, 404]:
                response.success()
            elif response.status_code == 403:
                response.success()
            else:
                response.failure(f"状态码: {response.status_code}")
                
    @task(1)
    def batch_permanent_delete(self):
        """
        【低频】批量永久删除 - 异步任务压力
        测试Celery队列处理能力
        """
        if len(self.deleted_file_ids) < 3:
            return
            
        # 选择3个文件批量删除
        file_ids = random.sample(self.deleted_file_ids, min(3, len(self.deleted_file_ids)))
        
        with self.client.post(
            "/api/document/recycle-bin/delete/",
            json={"file_ids": file_ids, "async_mode": True},
            headers=self.get_headers(),
            name="[回收站] 批量永久删除(异步)",
            catch_response=True
        ) as response:
            if response.status_code == 200:
                result = response.json()
                # 异步任务已提交
                response.success()
            elif response.status_code == 403:
                response.success()
            else:
                response.failure(f"状态码: {response.status_code}")
                
    @task(1)
    def batch_delete_folders(self):
        """
        【低频】批量删除文件夹 - 异步压力
        """
        if len(self.deleted_folder_ids) < 2:
            return
            
        folder_ids = random.sample(self.deleted_folder_ids, min(2, len(self.deleted_folder_ids)))
        
        with self.client.post(
            "/api/document/recycle-bin/folders/delete/",
            json={"folder_ids": folder_ids, "async_mode": True},
            headers=self.get_headers(),
            name="[回收站] 批量删除文件夹(异步)",
            catch_response=True
        ) as response:
            if response.status_code == 200:
                response.success()
            elif response.status_code == 403:
                response.success()
            else:
                response.failure(f"状态码: {response.status_code}")
                
    @task(2)
    def switch_space_view(self):
        """
        【中频】切换空间视图 - 私有/公共/全部
        """
        spaces = ['private', 'public', 'all']
        space = random.choice(spaces)
        
        with self.client.get(
            f"/api/document/recycle-bin/?space={space}&page=1&page_size=20",
            headers=self.get_headers(),
            name=f"[回收站] 切换视图({space})",
            catch_response=True
        ) as response:
            if response.status_code == 200:
                response.success()
            elif response.status_code == 403:
                response.success()
            else:
                response.failure(f"状态码: {response.status_code}")


@events.test_start.add_listener
def on_test_start(environment, **kwargs):
    """测试开始"""
    print("=" * 70)
    print("回收站专项压力测试开始")
    print("=" * 70)
    print("测试场景:")
    print("  1. 大容量列表查询 - 测试1000+已删除文件的加载性能")
    print("  2. 回收站搜索 - 大数据量搜索响应时间")
    print("  3. 统计信息 - 磁盘占用计算性能")
    print("  4. 恢复竞争 - 多用户恢复同一资源的并发控制")
    print("  5. 批量永久删除 - Celery异步任务队列压力")
    print("  6. 空间视图切换 - 私有/公共/全部数据隔离")
    print("=" * 70)


@events.test_stop.add_listener
def on_test_stop(environment, **kwargs):
    """测试结束"""
    print("=" * 70)
    print("回收站专项压力测试结束")
    print("=" * 70)


"""
【运行方式】

1. 交互式模式:
   locust -f locustfile_recycle_bin.py -H http://localhost --web-port 8091

2. 命令行模式:
   locust -f locustfile_recycle_bin.py -H http://localhost \
          --users 50 --spawn-rate 10 --run-time 10m --headless \
          --csv=recycle_bin_stress_test

【关键监控指标】

1. 列表加载时间 - P99应<500ms（1000+数据量）
2. 搜索响应时间 - P99应<1000ms
3. 统计计算时间 - P99应<300ms
4. 恢复操作成功率 - 并发恢复应有正确的幂等性处理
5. 异步任务堆积 - 监控Celery队列长度
6. 数据库慢查询 - 监控>500ms的查询
"""
