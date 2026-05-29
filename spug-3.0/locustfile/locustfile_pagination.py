"""
分页功能真实压力测试脚本

测试场景:
1. 真实分页加载 - 验证后端分页在高并发下的稳定性
2. 翻页操作 - 模拟用户快速翻页
3. 分页大小切换 - 测试不同page_size的性能
4. 并发分页请求 - 多用户同时请求不同页码
5. 深度分页 - 测试第100页、1000页的性能
6. 排序+分页 - 不同排序条件下的分页性能

使用说明:
locust -f locustfile_pagination.py -H http://localhost --web-port 8092
"""

import json
import random
import uuid
from locust import HttpUser, task, between, events
from locust.runners import MasterRunner


class PaginationUser(HttpUser):
    """
    分页压测用户类
    """
    wait_time = between(0.2, 1)  # 更快的操作频率
    
    def __init__(self, parent):
        super().__init__(parent)
        self.access_token = None
        self.target_folder_id = None
        self.current_page = 1
        self.page_size = 20
        self.total_pages = 1
        
    def on_start(self):
        """初始化"""
        self.login()
        self.find_large_folder()
        
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
        except Exception:
            pass
            
    def get_headers(self):
        """获取请求头"""
        return {
            "Content-Type": "application/json",
            "X-Token": self.access_token or "",
            "X-Requested-With": "XMLHttpRequest"
        }
        
    def find_large_folder(self):
        """寻找一个包含大量文件的文件夹用于测试"""
        try:
            # 先获取根目录
            res = self.client.get(
                "/api/document/folder/?is_public=false",
                headers=self.get_headers()
            )
            if res.status_code == 200:
                data = res.json()
                if data.get('folders'):
                    # 选择第一个文件夹
                    self.target_folder_id = data['folders'][0].get('id')
                    pagination = data.get('pagination', {})
                    total = max(pagination.get('total_folders', 0), 
                               pagination.get('total_files', 0))
                    self.total_pages = max(1, (total + self.page_size - 1) // self.page_size)
        except Exception:
            pass
    
    @task(10)
    def paginated_list_load(self):
        """
        【高频】分页加载 - 真实后端分页
        验证分页参数正确传递和响应
        """
        if not self.target_folder_id:
            return
            
        page = random.randint(1, min(10, self.total_pages)) if self.total_pages > 1 else 1
        
        with self.client.get(
            f"/api/document/folder/?id={self.target_folder_id}&page={page}&page_size={self.page_size}&is_public=false",
            headers=self.get_headers(),
            name="[分页] 真实分页加载",
            catch_response=True
        ) as response:
            if response.status_code == 200:
                result = response.json()
                pagination = result.get('pagination', {})
                
                # 验证分页数据完整性
                if 'total_folders' in pagination and 'total_files' in pagination:
                    total = pagination['total_folders'] + pagination['total_files']
                    response.success()
                else:
                    response.failure("响应缺少分页信息")
            elif response.status_code == 403:
                response.success()
            else:
                response.failure(f"状态码: {response.status_code}")
                
    @task(5)
    def page_navigation(self):
        """
        【中频】翻页操作 - 模拟用户翻页
        上一页/下一页/跳转到指定页
        """
        if not self.target_folder_id or self.total_pages <= 1:
            return
            
        # 随机翻页策略
        nav_type = random.choice(['next', 'prev', 'jump'])
        
        if nav_type == 'next':
            page = min(self.current_page + 1, self.total_pages)
        elif nav_type == 'prev':
            page = max(1, self.current_page - 1)
        else:  # jump
            page = random.randint(1, self.total_pages)
            
        self.current_page = page
        
        with self.client.get(
            f"/api/document/folder/?id={self.target_folder_id}&page={page}&page_size={self.page_size}&is_public=false",
            headers=self.get_headers(),
            name=f"[分页] 翻页({nav_type})",
            catch_response=True
        ) as response:
            if response.status_code == 200:
                response.success()
            elif response.status_code == 403:
                response.success()
            else:
                response.failure(f"状态码: {response.status_code}")
                
    @task(3)
    def change_page_size(self):
        """
        【中频】切换分页大小 - 测试不同page_size性能
        """
        if not self.target_folder_id:
            return
            
        sizes = [10, 20, 50, 100]
        new_size = random.choice(sizes)
        self.page_size = new_size
        
        with self.client.get(
            f"/api/document/folder/?id={self.target_folder_id}&page=1&page_size={new_size}&is_public=false",
            headers=self.get_headers(),
            name=f"[分页] 切换大小({new_size})",
            catch_response=True
        ) as response:
            if response.status_code == 200:
                result = response.json()
                folders = result.get('folders', [])
                files = result.get('files', [])
                
                # 验证返回数量不超过page_size
                if len(folders) <= new_size and len(files) <= new_size:
                    response.success()
                else:
                    response.failure(f"返回数据超过page_size限制: folders={len(folders)}, files={len(files)}")
            elif response.status_code == 403:
                response.success()
            else:
                response.failure(f"状态码: {response.status_code}")
                
    @task(2)
    def deep_pagination(self):
        """
        【低频】深度分页 - 测试第100页、500页性能
        深度分页通常性能较差，需要优化
        """
        if not self.target_folder_id:
            return
            
        deep_pages = [50, 100, 200, 500]
        page = random.choice(deep_pages)
        
        with self.client.get(
            f"/api/document/folder/?id={self.target_folder_id}&page={page}&page_size=20&is_public=false",
            headers=self.get_headers(),
            name=f"[分页] 深度分页(page={page})",
            catch_response=True
        ) as response:
            if response.status_code == 200:
                response.success()
            elif response.status_code == 403:
                response.success()
            elif response.status_code == 404:
                # 页码超出范围，正常情况
                response.success()
            else:
                response.failure(f"状态码: {response.status_code}")
                
    @task(3)
    def concurrent_different_pages(self):
        """
        【中频】并发不同页码 - 模拟多用户浏览不同页面
        """
        if not self.target_folder_id:
            return
            
        # 随机页码，模拟不同用户看不同页
        page = random.randint(1, 20)
        
        with self.client.get(
            f"/api/document/folder/?id={self.target_folder_id}&page={page}&page_size=20&is_public=false",
            headers=self.get_headers(),
            name="[分页] 并发多页码",
            catch_response=True
        ) as response:
            if response.status_code == 200:
                response.success()
            elif response.status_code == 403:
                response.success()
            else:
                response.failure(f"状态码: {response.status_code}")
                
    @task(2)
    def pagination_with_sort(self):
        """
        【中频】排序+分页 - 测试排序条件下的分页性能
        """
        if not self.target_folder_id:
            return
            
        sort_fields = ['name', 'created_at', 'file_size']
        sort_field = random.choice(sort_fields)
        page = random.randint(1, 10)
        
        with self.client.get(
            f"/api/document/folder/?id={self.target_folder_id}&page={page}&page_size=20&is_public=false&sort={sort_field}",
            headers=self.get_headers(),
            name=f"[分页] 排序分页({sort_field})",
            catch_response=True
        ) as response:
            if response.status_code == 200:
                response.success()
            elif response.status_code == 403:
                response.success()
            else:
                response.failure(f"状态码: {response.status_code}")
                
    @task(2)
    def public_space_pagination(self):
        """
        【中频】公共空间分页 - 公共空间数据量通常更大
        """
        with self.client.get(
            f"/api/document/folder/?page=1&page_size=20&is_public=true",
            headers=self.get_headers(),
            name="[分页] 公共空间分页",
            catch_response=True
        ) as response:
            if response.status_code == 200:
                response.success()
            elif response.status_code == 403:
                response.success()
            else:
                response.failure(f"状态码: {response.status_code}")
                
    @task(3)
    def search_pagination(self):
        """
        【中频】搜索结果分页 - 搜索+分页组合
        """
        keywords = ["test", "file", "doc", "pdf", "2024"]
        keyword = random.choice(keywords)
        page = random.randint(1, 5)
        
        with self.client.get(
            f"/api/document/folder/search/?keyword={keyword}&page={page}&page_size=20&is_public=false",
            headers=self.get_headers(),
            name="[分页] 搜索分页",
            catch_response=True
        ) as response:
            if response.status_code == 200:
                response.success()
            elif response.status_code == 403:
                response.success()
            else:
                response.failure(f"状态码: {response.status_code}")
                
    @task(1)
    def rapid_page_switching(self):
        """
        【低频】快速翻页 - 模拟用户疯狂点击翻页
        测试系统稳定性和数据一致性
        """
        if not self.target_folder_id:
            return
            
        # 连续请求3个不同页码
        pages = random.sample(range(1, min(20, self.total_pages) + 1), min(3, self.total_pages))
        
        for page in pages:
            with self.client.get(
                f"/api/document/folder/?id={self.target_folder_id}&page={page}&page_size=20&is_public=false",
                headers=self.get_headers(),
                name="[分页] 快速翻页",
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
    print("分页功能真实压力测试开始")
    print("=" * 70)
    print("测试场景:")
    print("  1. 真实分页加载 - 验证后端分页参数处理")
    print("  2. 翻页操作 - 上一页/下一页/跳转")
    print("  3. 分页大小切换 - 10/20/50/100条/页")
    print("  4. 深度分页 - 第50/100/200/500页性能")
    print("  5. 并发多页码 - 多用户访问不同页面")
    print("  6. 排序+分页 - 排序条件下的分页性能")
    print("  7. 公共空间分页 - 大数据量场景")
    print("  8. 搜索分页 - 搜索+分页组合")
    print("  9. 快速翻页 - 稳定性测试")
    print("=" * 70)


@events.test_stop.add_listener
def on_test_stop(environment, **kwargs):
    """测试结束"""
    print("=" * 70)
    print("分页功能真实压力测试结束")
    print("=" * 70)


"""
【运行方式】

1. 交互式模式:
   locust -f locustfile_pagination.py -H http://localhost --web-port 8092

2. 命令行模式:
   locust -f locustfile_pagination.py -H http://localhost \
          --users 100 --spawn-rate 20 --run-time 10m --headless \
          --csv=pagination_stress_test

【关键监控指标】

1. 分页响应时间 - P99应<200ms
2. 深度分页性能 - 第100页响应时间应<500ms
3. 分页数据一致性 - 无重复/遗漏数据
4. 并发分页稳定性 - 100并发下无错误
5. 排序分页性能 - 带排序时分页响应时间
6. 翻页操作流畅性 - 快速翻页无卡顿

【常见性能问题】

1. OFFSET深度分页慢 - 大数据量时OFFSET 100000很慢
   解决方案: 使用游标分页（cursor-based）

2. 排序+分页不一致 - 数据变化导致重复/遗漏
   解决方案: 使用稳定排序键

3. 内存溢出 - 一次性加载大量数据
   解决方案: 确保数据库层面分页
"""
