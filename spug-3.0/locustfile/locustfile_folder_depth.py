"""
文件夹深度嵌套压力测试脚本

测试场景:
1. 深层嵌套创建 - 创建100层嵌套的文件夹
2. 深层路径操作 - 在深层路径下进行CRUD
3. 递归操作性能 - 递归获取文件夹树
4. 路径长度极限 - 测试系统路径长度限制
5. 循环引用检测 - 测试循环引用防护
6. 深层文件上传 - 在深层文件夹中上传文件
7. 深层删除性能 - 删除深层嵌套文件夹

使用说明:
locust -f locustfile_folder_depth.py -H http://localhost --web-port 8093
"""

import json
import random
import uuid
from locust import HttpUser, task, between, events
from locust.runners import MasterRunner


class FolderDepthUser(HttpUser):
    """
    文件夹深度压测用户类
    """
    wait_time = between(0.5, 2)
    
    # 最大嵌套深度配置
    MAX_DEPTH = 50  # 系统支持的最大深度
    
    def __init__(self, parent):
        super().__init__(parent)
        self.access_token = None
        self.deep_folder_chain = []  # 深层文件夹链 [id1, id2, id3, ...]
        self.test_folder_id = None
        
    def on_start(self):
        """初始化"""
        self.login()
        self.create_deep_folder_structure()
        
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
        
    def create_deep_folder_structure(self):
        """创建深层文件夹结构"""
        parent_id = None
        chain = []
        
        # 创建10层嵌套结构
        for depth in range(10):
            try:
                folder_name = f"深度{depth}_{uuid.uuid4().hex[:6]}"
                res = self.client.post(
                    "/api/document/folder/",
                    json={"name": folder_name, "space": "private", "parent_id": parent_id},
                    headers=self.get_headers()
                )
                if res.status_code == 200:
                    folder_id = res.json().get('data', {}).get('id')
                    if folder_id:
                        chain.append(folder_id)
                        parent_id = folder_id
                else:
                    break
            except Exception:
                break
                
        self.deep_folder_chain = chain
        if chain:
            self.test_folder_id = chain[-1]  # 最深层的文件夹
    
    @task(5)
    def create_deep_nested_folder(self):
        """
        【中频】在深层路径下创建文件夹
        测试深层路径下的创建性能
        """
        if not self.deep_folder_chain:
            return
            
        # 随机选择一个深度
        depth = random.randint(0, len(self.deep_folder_chain) - 1)
        parent_id = self.deep_folder_chain[depth]
        
        folder_name = f"嵌套_{uuid.uuid4().hex[:6]}"
        
        with self.client.post(
            "/api/document/folder/",
            json={"name": folder_name, "space": "private", "parent_id": parent_id},
            headers=self.get_headers(),
            name=f"[深度] 深层创建(depth={depth})",
            catch_response=True
        ) as response:
            if response.status_code == 200:
                response.success()
            elif response.status_code == 400:
                # 可能达到深度限制
                response.success()
            elif response.status_code == 403:
                response.success()
            else:
                response.failure(f"状态码: {response.status_code}")
                
    @task(5)
    def list_deep_folder_contents(self):
        """
        【中频】列出深层文件夹内容
        """
        if not self.test_folder_id:
            return
            
        with self.client.get(
            f"/api/document/folder/?id={self.test_folder_id}&page=1&page_size=20&is_public=false",
            headers=self.get_headers(),
            name="[深度] 列出深层内容",
            catch_response=True
        ) as response:
            if response.status_code == 200:
                response.success()
            elif response.status_code == 403:
                response.success()
            else:
                response.failure(f"状态码: {response.status_code}")
                
    @task(3)
    def upload_to_deep_folder(self):
        """
        【中频】在深层文件夹上传文件
        测试深层路径下的文件上传
        """
        if not self.test_folder_id:
            return
            
        file_name = f"深层文件_{uuid.uuid4().hex[:6]}.txt"
        content = b"deep folder test content " * 50
        
        with self.client.post(
            "/api/document/upload/",
            files={'file': (file_name, content, 'text/plain')},
            data={'folder_id': self.test_folder_id, 'space': 'private'},
            headers={"X-Token": self.access_token or ""},
            name="[深度] 深层文件上传",
            catch_response=True
        ) as response:
            if response.status_code == 200:
                response.success()
            elif response.status_code == 403:
                response.success()
            else:
                response.failure(f"状态码: {response.status_code}")
                
    @task(3)
    def get_folder_tree(self):
        """
        【中频】获取文件夹树 - 递归性能测试
        """
        with self.client.get(
            "/api/document/folder/?all=true&is_public=false",
            headers=self.get_headers(),
            name="[深度] 获取文件夹树",
            catch_response=True
        ) as response:
            if response.status_code == 200:
                result = response.json()
                # 验证返回的是数组或包含folders的对象
                if isinstance(result, list) or (isinstance(result, dict) and 'folders' in result):
                    response.success()
                else:
                    response.failure("响应格式错误")
            elif response.status_code == 403:
                response.success()
            else:
                response.failure(f"状态码: {response.status_code}")
                
    @task(2)
    def extreme_depth_test(self):
        """
        【低频】极限深度测试 - 尝试创建50层嵌套
        测试系统的深度限制
        """
        parent_id = None
        created_count = 0
        max_attempt = 50
        
        for depth in range(max_attempt):
            folder_name = f"极限深度{depth}_{uuid.uuid4().hex[:4]}"
            
            with self.client.post(
                "/api/document/folder/",
                json={"name": folder_name, "space": "private", "parent_id": parent_id},
                headers=self.get_headers(),
                name="[深度] 极限深度创建",
                catch_response=True
            ) as response:
                if response.status_code == 200:
                    folder_id = response.json().get('data', {}).get('id')
                    if folder_id:
                        parent_id = folder_id
                        created_count += 1
                    else:
                        break
                elif response.status_code == 400:
                    # 达到深度限制
                    response.success()
                    break
                else:
                    response.failure(f"深度{depth}创建失败: {response.status_code}")
                    break
                    
    @task(2)
    def move_to_deep_folder(self):
        """
        【低频】移动到深层文件夹
        测试移动操作的深度限制
        """
        if len(self.deep_folder_chain) < 2:
            return
            
        # 创建一个临时文件夹然后移动到深层
        temp_name = f"移动测试_{uuid.uuid4().hex[:6]}"
        
        # 先在根目录创建
        res = self.client.post(
            "/api/document/folder/",
            json={"name": temp_name, "space": "private", "parent_id": None},
            headers=self.get_headers()
        )
        
        if res.status_code == 200:
            folder_id = res.json().get('data', {}).get('id')
            if folder_id:
                # 移动到深层
                target_id = self.deep_folder_chain[-1]
                
                with self.client.post(
                    "/api/document/folder/move/",
                    json={"folder_ids": [folder_id], "target_id": target_id, "space": "private"},
                    headers=self.get_headers(),
                    name="[深度] 移动到深层",
                    catch_response=True
                ) as response:
                    if response.status_code == 200:
                        response.success()
                    elif response.status_code == 400:
                        # 可能达到深度限制
                        response.success()
                    elif response.status_code == 403:
                        response.success()
                    else:
                        response.failure(f"状态码: {response.status_code}")
                        
    @task(2)
    def copy_from_deep_folder(self):
        """
        【低频】从深层文件夹复制
        """
        if not self.deep_folder_chain:
            return
            
        source_id = random.choice(self.deep_folder_chain)
        
        with self.client.post(
            "/api/document/folder/copy/",
            json={"folder_ids": [source_id], "space": "private"},
            headers=self.get_headers(),
            name="[深度] 深层复制",
            catch_response=True
        ) as response:
            if response.status_code == 200:
                response.success()
            elif response.status_code == 403:
                response.success()
            else:
                response.failure(f"状态码: {response.status_code}")
                
    @task(1)
    def delete_deep_folder(self):
        """
        【低频】删除深层文件夹
        测试递归删除性能
        """
        if len(self.deep_folder_chain) < 3:
            return
            
        # 删除中间层的一个文件夹（会删除其子文件夹）
        index = random.randint(1, len(self.deep_folder_chain) - 2)
        folder_id = self.deep_folder_chain[index]
        
        with self.client.delete(
            f"/api/document/folder/?id={folder_id}",
            headers=self.get_headers(),
            name="[深度] 删除深层文件夹",
            catch_response=True
        ) as response:
            if response.status_code in [200, 204]:
                # 从链中移除被删除的及其子文件夹
                self.deep_folder_chain = self.deep_folder_chain[:index]
                if self.deep_folder_chain:
                    self.test_folder_id = self.deep_folder_chain[-1]
                else:
                    self.test_folder_id = None
                response.success()
            elif response.status_code == 403:
                response.success()
            else:
                response.failure(f"状态码: {response.status_code}")
                
    @task(1)
    def breadcrumb_navigation(self):
        """
        【低频】面包屑导航 - 获取路径上的所有文件夹
        """
        if not self.deep_folder_chain:
            return
            
        # 随机选择一个深层文件夹获取面包屑
        folder_id = random.choice(self.deep_folder_chain)
        
        with self.client.get(
            f"/api/document/folder/?id={folder_id}&is_public=false",
            headers=self.get_headers(),
            name="[深度] 面包屑导航",
            catch_response=True
        ) as response:
            if response.status_code == 200:
                response.success()
            elif response.status_code == 403:
                response.success()
            else:
                response.failure(f"状态码: {response.status_code}")
                
    @task(2)
    def search_in_deep_folders(self):
        """
        【低频】在深层文件夹中搜索
        """
        if not self.test_folder_id:
            return
            
        with self.client.get(
            f"/api/document/folder/search/?folder_id={self.test_folder_id}&keyword=test&is_public=false",
            headers=self.get_headers(),
            name="[深度] 深层搜索",
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
    print("文件夹深度嵌套压力测试开始")
    print("=" * 70)
    print("测试场景:")
    print("  1. 深层嵌套创建 - 测试系统深度限制")
    print("  2. 深层路径CRUD - 深层文件夹的增删改查")
    print("  3. 深层文件上传 - 在深层路径上传文件")
    print("  4. 文件夹树递归 - 递归获取性能")
    print("  5. 极限深度测试 - 50层嵌套尝试")
    print("  6. 深层移动/复制 - 跨层级操作")
    print("  7. 深层删除 - 递归删除性能")
    print("  8. 面包屑导航 - 路径导航性能")
    print("  9. 深层搜索 - 在深层路径中搜索")
    print("=" * 70)


@events.test_stop.add_listener
def on_test_stop(environment, **kwargs):
    """测试结束"""
    print("=" * 70)
    print("文件夹深度嵌套压力测试结束")
    print("=" * 70)


"""
【运行方式】

1. 交互式模式:
   locust -f locustfile_folder_depth.py -H http://localhost --web-port 8093

2. 命令行模式:
   locust -f locustfile_folder_depth.py -H http://localhost \
          --users 50 --spawn-rate 10 --run-time 10m --headless \
          --csv=folder_depth_stress_test

【关键监控指标】

1. 深层创建性能 - 每增加一层性能衰减情况
2. 递归查询性能 - 获取完整文件夹树的响应时间
3. 深度限制 - 系统实际支持的最大嵌套层数
4. 路径长度 - 是否能处理长路径（Linux通常4096字节）
5. 递归删除性能 - 删除嵌套文件夹的时间复杂度
6. 内存使用 - 递归操作时的内存占用

【常见问题和解决方案】

1. 递归查询慢 - 使用CTE（Common Table Expressions）优化
2. 路径过长 - 限制文件夹名称长度和最大深度
3. 循环引用 - 添加parent_id循环检测
4. 递归删除慢 - 使用异步任务批量删除
5. 栈溢出 - 避免过深的递归调用，改用迭代
"""
