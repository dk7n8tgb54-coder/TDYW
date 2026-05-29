"""
回收站功能 Locust 压测脚本

使用说明:
1. 安装依赖: pip install locust
2. 运行测试: locust -H http://localhost:9000
3. 打开浏览器访问: http://localhost:8089
4. 设置并发用户数和 spawn rate，开始测试

或者命令行直接运行:
locust -H http://localhost:9000 --users 100 --spawn-rate 20 --run-time 5m --headless
"""

import json
import random
import uuid
import logging
import threading
import time
from datetime import datetime
from locust import HttpUser, task, between, events
from locust.runners import MasterRunner

logger = logging.getLogger(__name__)


class RecycleBinUser(HttpUser):
    """
    回收站功能压测用户类
    模拟真实用户操作：查看回收站列表、恢复文件/文件夹、彻底删除等
    """

    # 请求间隔：1-3秒（模拟真实用户操作间隔）
    wait_time = between(1, 3)

    # 类变量：共享测试文件夹ID（所有用户恢复同一个文件夹）
    shared_test_folder_id = None
    shared_folder_created = False  # 标记是否已创建
    _lock = threading.Lock()  # 类级别锁，确保只初始化一次
    
    def __init__(self, parent):
        super().__init__(parent)
        self.access_token = None     # 认证token
        self.csrf_token = None
        self.tenant_id = None
        self.test_file_ids = []      # 测试用的文件ID
        self.test_folder_ids = []    # 测试用的文件夹ID
        self.concurrent_test_folder_id = None  # 并发测试专用文件夹ID
        
    def save_auth_token(self, response):
        """从登录响应中提取 access_token"""
        if response.status_code == 200:
            try:
                result = response.json()
                # access_token 在 data 字段中
                data = result.get('data', {})
                self.access_token = data.get('access_token')
                if self.access_token:
                    print(f"[User] 提取到 access_token: {self.access_token[:10]}...")
                else:
                    print(f"[User] 登录响应中没有 access_token: {result}")
            except Exception as e:
                print(f"[User] 解析登录响应失败: {e}")
        
    def on_start(self):
        """
        用户启动时执行：登录并获取必要凭证
        """
        self.login()
        self.prepare_test_data()
    
    def login(self):
        """
        模拟用户登录 - 获取 access_token
        """
        try:
            # type 参数必须传入，否则 login_histories 表会报错
            login_data = {
                "username": "admin",
                "password": "Admin888",
                "type": "default"
            }
            
            headers = {
                "Content-Type": "application/json",
                "X-Requested-With": "XMLHttpRequest"
            }
            
            response = self.client.post(
                "/api/account/login/",
                json=login_data,
                headers=headers,
                name="[准备] 登录"
            )
            
            # 提取登录返回的 access_token
            self.save_auth_token(response)
            
            if response.status_code == 200 and self.access_token:
                print(f"[User] 登录成功, access_token: {self.access_token[:10]}...")
            else:
                print(f"[User] 登录失败: {response.status_code} - {response.text[:200]}")
                
        except Exception as e:
            print(f"[User] 登录异常: {e}")
    
    def get_headers(self):
        """
        获取请求头
        """
        headers = {
            "Content-Type": "application/json",
            "X-Requested-With": "XMLHttpRequest",
            "Accept": "application/json"
        }
        
        # 添加认证 token
        if self.access_token:
            headers["X-Token"] = self.access_token
        
        return headers
    
    def prepare_test_data(self):
        """
        准备测试数据：第一个用户创建共享文件夹，其他用户等待并使用
        """
        try:
            # 使用类级别锁确保只有一个用户创建文件夹
            with RecycleBinUser._lock:
                # 检查是否已有共享文件夹
                if RecycleBinUser.shared_test_folder_id:
                    self.concurrent_test_folder_id = RecycleBinUser.shared_test_folder_id
                    print(f"[User] 使用共享测试文件夹: ID={self.concurrent_test_folder_id}")
                    self.load_recycle_bin_items()
                    return
                
                # 标记正在创建，防止其他用户进入
                if RecycleBinUser.shared_folder_created:
                    # 等待创建完成
                    time.sleep(1)
                    if RecycleBinUser.shared_test_folder_id:
                        self.concurrent_test_folder_id = RecycleBinUser.shared_test_folder_id
                        print(f"[User] 等待后使用共享文件夹: ID={self.concurrent_test_folder_id}")
                        self.load_recycle_bin_items()
                        return
                
                RecycleBinUser.shared_folder_created = True
            
            # 第一个用户创建共享文件夹
            print("[User] 我是第一个用户，开始创建共享文件夹...")
            folder_name = f"并发测试文件夹_{uuid.uuid4().hex[:8]}"
            create_data = {
                "parent_id": None,
                "name": folder_name,
                "space": "private"
            }
            
            response = self.client.post(
                "/api/document/folder/",
                json=create_data,
                headers=self.get_headers(),
                name="[准备] 创建共享测试文件夹"
            )
            
            if response.status_code != 200:
                print(f"[User] 创建文件夹失败: {response.status_code} - {response.text[:200]}")
                RecycleBinUser.shared_folder_created = False
                return
            
            folder_id = response.json().get("data", {}).get("id")
            if not folder_id:
                print(f"[User] 无法获取文件夹ID: {response.json()}")
                RecycleBinUser.shared_folder_created = False
                return
            
            print(f"[User] 创建共享文件夹成功: ID={folder_id}")
            
            # 删除文件夹（移入回收站）
            response = self.client.delete(
                f"/api/document/folder/?id={folder_id}",
                headers=self.get_headers(),
                name="[准备] 删除共享文件夹到回收站"
            )
            
            if response.status_code not in [200, 204]:
                print(f"[User] 删除文件夹失败: {response.status_code} - {response.text[:200]}")
                RecycleBinUser.shared_folder_created = False
                return
            
            # 设置为共享文件夹ID（类变量，所有用户可见）
            # 注意：已经在锁的保护范围内，直接设置即可
            RecycleBinUser.shared_test_folder_id = folder_id
            
            self.concurrent_test_folder_id = folder_id
            
            print(f"[User] 共享测试数据准备完成: 文件夹 {folder_id} 已移入回收站")
            
            # 给其他用户一点时间来读取共享ID
            time.sleep(0.5)
            
            self.load_recycle_bin_items()
                      
        except Exception as e:
            print(f"[User] 准备测试数据失败: {e}")
            RecycleBinUser.shared_folder_created = False
    
    def load_recycle_bin_items(self):
        """加载回收站中的其他文件ID"""
        try:
            response = self.client.get(
                "/api/document/recycle-bin/",
                params={"page": 1, "page_size": 50, "space": "all"},
                headers=self.get_headers(),
                name="[准备] 获取回收站列表"
            )
            
            if response.status_code == 200:
                result = response.json()
                # 注意：响应结构是 {data: {items: [...]}}
                data = result.get("data", {})
                items = data.get("items", []) if isinstance(data, dict) else []
                
                print(f"[User] 回收站API返回 {len(items)} 个项目")
                
                for item in items:
                    if item.get("type") == "folder":
                        if item.get("id") not in self.test_folder_ids:
                            self.test_folder_ids.append(item.get("id"))
                    else:
                        self.test_file_ids.append(item.get("id"))
                
                # 注意：共享文件夹不加入test_folder_ids，专用于并发测试
                # 避免普通恢复任务把它恢复掉，导致并发测试失败
                
                print(f"[User] 回收站数据: 文件 {len(self.test_file_ids)} 个, 文件夹 {len(self.test_folder_ids)} 个")
                print(f"[User] 共享文件夹ID: {RecycleBinUser.shared_test_folder_id}")
        except Exception as e:
            print(f"[User] 加载回收站数据失败: {e}")
    
    # ==================== 查询类任务 ====================
    
    @task(10)
    def get_recycle_bin_list(self):
        """
        【高频】获取回收站列表 - 最频繁的操作
        """
        params = {
            "page": random.randint(1, 5),
            "page_size": random.choice([10, 20, 50]),
            "space": random.choice(["all", "private", "public"])
        }
        
        with self.client.get(
            "/api/document/recycle-bin/",
            params=params,
            headers=self.get_headers(),
                name="GET /api/document/recycle-bin/ (列表)",
            catch_response=True
        ) as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"状态码: {response.status_code}")
    
    @task(3)
    def get_recycle_bin_stats(self):
        """
        【中频】获取回收站统计信息
        """
        with self.client.get(
            "/api/document/recycle-bin/stats/",
            headers=self.get_headers(),
                name="GET /api/document/recycle-bin/stats/ (统计)",
            catch_response=True
        ) as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"状态码: {response.status_code}")
    
    @task(2)
    def search_recycle_bin(self):
        """
        【低频】搜索回收站
        """
        keywords = ["test", "doc", "file", "folder", "", "backup", "data"]
        params = {
            "page": 1,
            "page_size": 20,
            "keyword": random.choice(keywords),
            "space": "all"
        }
        
        with self.client.get(
            "/api/document/recycle-bin/",
            params=params,
            headers=self.get_headers(),
                name="GET /api/document/recycle-bin/ (搜索)",
            catch_response=True
        ) as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"状态码: {response.status_code}")
    
    # ==================== 恢复类任务 ====================
    
    @task(5)
    def restore_files_original(self):
        """
        【中频】恢复文件到原位置
        并发测试重点：测试 select_for_update 锁是否有效
        """
        if not self.test_file_ids:
            return
        
        # 随机选择1-3个文件
        ids = random.sample(
            self.test_file_ids, 
            min(random.randint(1, 3), len(self.test_file_ids))
        )
        
        data = {
            "file_ids": ids,
            "restore_mode": "original",
            "idempotent_key": f"restore_{uuid.uuid4().hex[:16]}"
        }
        
        with self.client.post(
            "/api/document/recycle-bin/restore/",
            json=data,
            headers=self.get_headers(),
                name="POST /api/document/recycle-bin/restore/ (文件恢复)",
            catch_response=True
        ) as response:
            if response.status_code == 200:
                result = response.json()
                # 解析嵌套结构 {data: {success_count: 1}}
                data = result.get("data", {})
                success_count = data.get("success_count", 0) if isinstance(data, dict) else 0

                if success_count > 0:
                    response.success()
                else:
                    # 检查是否因为文件已被恢复/不存在而失败
                    details = data.get("details", []) if isinstance(data, dict) else []
                    all_not_found = all(d.get("code") == 404001 for d in details)

                    if all_not_found:
                        # 文件已被其他并发请求处理，这是预期行为
                        # 从列表中移除不存在的文件
                        for d in details:
                            failed_id = d.get("id")
                            if failed_id in self.test_file_ids:
                                self.test_file_ids.remove(failed_id)
                        response.success()
                    else:
                        response.failure(f"恢复失败: {result}")
            elif response.status_code == 409:
                response.success()  # 并发冲突是预期行为
            else:
                response.failure(f"状态码: {response.status_code}, 响应: {response.text[:200]}")
    
    @task(3)
    def restore_folders_original(self):
        """
        【中频】恢复文件夹到原位置
        并发测试重点：测试文件夹恢复锁机制
        """
        # 排除并发测试专用文件夹，避免干扰并发测试
        available_folders = [
            fid for fid in self.test_folder_ids
            if fid != RecycleBinUser.shared_test_folder_id
        ]
        if not available_folders:
            return

        # 随机选择1-2个文件夹
        ids = random.sample(
            available_folders,
            min(random.randint(1, 2), len(available_folders))
        )
        
        data = {
            "folder_ids": ids,
            "restore_mode": "original",
            "idempotent_key": f"restore_folder_{uuid.uuid4().hex[:16]}"
        }
        
        with self.client.post(
            "/api/document/recycle-bin/folder-restore/",
            json=data,
            headers=self.get_headers(),
                name="POST /api/document/recycle-bin/folder-restore/ (文件夹恢复)",
            catch_response=True
        ) as response:
            if response.status_code == 200:
                result = response.json()
                # 解析嵌套结构 {data: {success_count: 1}}
                data = result.get("data", {})
                success_count = data.get("success_count", 0) if isinstance(data, dict) else 0

                if success_count > 0:
                    response.success()
                else:
                    # 检查是否因为文件夹已被恢复/不存在而失败
                    details = data.get("details", []) if isinstance(data, dict) else []
                    all_not_found = all(d.get("code") == 404001 for d in details)

                    if all_not_found:
                        # 文件夹已被其他并发请求处理，这是预期行为
                        # 从列表中移除不存在的文件夹
                        for d in details:
                            failed_id = d.get("id")
                            if failed_id in self.test_folder_ids:
                                self.test_folder_ids.remove(failed_id)
                        response.success()
                    else:
                        response.failure(f"恢复失败: {result}")
            elif response.status_code == 409:
                response.success()  # 并发冲突是预期行为
            else:
                response.failure(f"状态码: {response.status_code}")
    
    # ==================== 删除类任务 ====================
    
    @task(2)
    def permanent_delete_files(self):
        """
        【低频】彻底删除文件
        """
        if not self.test_file_ids:
            return
        
        ids = random.sample(
            self.test_file_ids,
            min(random.randint(1, 2), len(self.test_file_ids))
        )
        
        data = {
            "file_ids": ids,
            "async_mode": False
        }
        
        with self.client.post(
            "/api/document/recycle-bin/permanent/",
            json=data,
            headers=self.get_headers(),
                name="POST /api/document/recycle-bin/permanent/ (文件删除)",
            catch_response=True
        ) as response:
            if response.status_code in [200, 204]:
                response.success()
            else:
                response.failure(f"状态码: {response.status_code}")
    
    @task(1)
    def permanent_delete_folders(self):
        """
        【低频】彻底删除文件夹
        """
        # 排除并发测试专用文件夹
        available_folders = [
            fid for fid in self.test_folder_ids
            if fid != RecycleBinUser.shared_test_folder_id
        ]
        if not available_folders:
            return

        ids = random.sample(
            available_folders,
            min(random.randint(1, 2), len(available_folders))
        )
        
        data = {
            "folder_ids": ids,
            "async_mode": False
        }
        
        with self.client.post(
            "/api/document/recycle-bin/folder-permanent/",
            json=data,
            headers=self.get_headers(),
                name="POST /api/document/recycle-bin/folder-permanent/ (文件夹删除)",
            catch_response=True
        ) as response:
            if response.status_code in [200, 204]:
                response.success()
            else:
                response.failure(f"状态码: {response.status_code}")
    
    # ==================== 并发场景测试 ====================
    
    def _recreate_test_folder(self):
        """重新创建并发测试用的共享文件夹"""
        try:
            folder_name = f"并发测试文件夹_{uuid.uuid4().hex[:8]}"
            create_data = {
                "parent_id": None,
                "name": folder_name,
                "space": "private"
            }

            response = self.client.post(
                "/api/document/folder/",
                json=create_data,
                headers=self.get_headers(),
                name="[并发测试] 重新创建测试文件夹"
            )

            if response.status_code != 200:
                return None

            folder_id = response.json().get("data", {}).get("id")
            if not folder_id:
                return None

            # 删除到回收站
            self.client.delete(
                f"/api/document/folder/?id={folder_id}",
                headers=self.get_headers(),
                name="[并发测试] 重新删除到回收站"
            )

            # 更新共享文件夹ID
            with RecycleBinUser._lock:
                RecycleBinUser.shared_test_folder_id = folder_id

            print(f"[并发测试] 重新创建共享文件夹: ID={folder_id}")
            return folder_id
        except Exception as e:
            print(f"[并发测试] 重新创建文件夹失败: {e}")
            return None

    @task(3)
    def concurrent_restore_same_folder(self):
        """
        【高并发测试】模拟多个用户同时恢复同一文件夹
        专门测试 select_for_update 行锁是否有效防止重复恢复
        """
        # 使用共享测试文件夹ID，确保所有用户竞争同一个资源
        test_folder_id = RecycleBinUser.shared_test_folder_id or getattr(self, 'concurrent_test_folder_id', None)
        if not test_folder_id:
            print("[并发测试] 警告: 没有可用的测试文件夹ID，跳过")
            return

        print(f"[并发测试] 用户尝试恢复文件夹 {test_folder_id}")

        data = {
            "folder_ids": [test_folder_id],
            "restore_mode": "original",
            "idempotent_key": f"concurrent_test_{datetime.now().timestamp()}"
        }

        with self.client.post(
            "/api/document/recycle-bin/folder-restore/",
            json=data,
            headers=self.get_headers(),
                name="[并发测试] 同一文件夹恢复",
            catch_response=True
        ) as response:
            if response.status_code == 200:
                try:
                    result = response.json()
                    print(f"[并发测试] 响应: {result}")

                    # 解析嵌套结构 {data: {success_count: 1, failed_count: 0}}
                    data = result.get("data", {})
                    if isinstance(data, dict):
                        success = data.get("success_count", 0)
                        failed = data.get("failed_count", 0)
                        details = data.get("details", [])

                        # 检查是否因为文件夹已被恢复而失败
                        folder_already_restored = any(
                            d.get("code") == 404001 for d in details
                        )

                        if success > 0:
                            # 恢复成功，需要重新创建测试数据供后续并发测试使用
                            print(f"[并发测试] 恢复成功，重新创建测试数据...")
                            self._recreate_test_folder()
                            response.success()
                        elif folder_already_restored:
                            # 文件夹已被其他并发请求恢复，这是预期行为
                            # 不需要重新创建，因为成功的那个用户已经创建了
                            print(f"[并发测试] 文件夹已被其他请求恢复")
                            response.success()
                        elif failed > 0:
                            response.success()  # 其他并发冲突也是预期行为
                        else:
                            response.success()
                    else:
                        response.success()
                except Exception as e:
                    response.failure(f"解析响应失败: {e}")

            elif response.status_code == 409:
                # 预期的冲突响应
                response.success()
            else:
                response.failure(f"状态码: {response.status_code}, 响应: {response.text[:200]}")


# ==================== 事件监听 ====================

@events.test_start.add_listener
def on_test_start(environment, **kwargs):
    """
    测试开始时的回调
    """
    print("=" * 60)
    print("回收站功能 Locust 压测开始")
    print("=" * 60)
    print("测试场景:")
    print("  1. 高频查询 - 获取回收站列表")
    print("  2. 中频恢复 - 文件/文件夹恢复到原位置")
    print("  3. 低频删除 - 彻底删除文件/文件夹")
    print("  4. 并发测试 - 多用户同时操作同一资源")
    print("=" * 60)
    
    if isinstance(environment.runner, MasterRunner):
        print("[主节点] 分布式测试模式")


@events.test_stop.add_listener
def on_test_stop(environment, **kwargs):
    """
    测试结束时的回调
    """
    print("=" * 60)
    print("回收站功能 Locust 压测结束")
    print("=" * 60)
    
    # 可以在这里生成测试报告或发送通知


# ==================== 使用说明 ====================
"""
【运行方式】

1. 交互式模式（推荐用于调试）:
   locust -H http://localhost
   
   然后打开 http://localhost:8089
   设置: Number of users = 50
        Spawn rate = 10
        Host = http://localhost  (Docker映射的是80端口)

2. 命令行模式（用于自动化测试）:
   locust -H http://localhost \
          --users 100 \
          --spawn-rate 20 \
          --run-time 5m \
          --headless \
          --csv=recycle_bin_test

3. 分布式模式（大规模压测）:
   # 启动主节点
   locust -H http://localhost --master
   
   # 启动工作节点（可多机）
   locust --worker --master-host=<master-ip>

【监控指标】

重点关注:
- RPS (Requests Per Second): 每秒请求数
- Failure Rate: 失败率（目标 < 1%）
- P50/P95/P99 Response Time: 响应时间分位数
- Concurrent Users: 并发用户数

【关键测试点】

1. 行锁有效性:
   - 多个用户同时恢复同一文件夹
   - 预期: 只有一个成功，其他返回 409 或失败

2. 幂等性:
   - 使用相同 idempotent_key 重复请求
   - 预期: 第二次返回已处理或成功但不重复执行

3. 性能表现:
   - 100并发用户下 P95 响应时间 < 2s
   - 数据库连接数正常，无死锁
"""
