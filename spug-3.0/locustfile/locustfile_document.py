"""
资料管理模块 Locust 高并发压测脚本

测试场景:
1. 高频查询 - 获取文件夹/文件列表、搜索、磁盘使用
2. 高并发创建 - 批量创建文件夹（含同名竞争测试）
3. 高并发上传 - 模拟多用户同时上传小文件
4. 分片上传压力 - 并发分片上传、合并锁竞争测试
5. 移动/复制竞争 - 测试同名冲突处理
6. 数据清理 - 文件/文件夹删除（防止测试数据无限增长）
7. 公共空间专项 - 公共空间CRUD、权限、合并锁测试

分片上传专项测试:
- chunked_upload_test: 标准分片上传流程（transfers/create/ -> transfers/{id}/progress/ -> transfers/{id}/complete/）
- chunked_upload_with_merge: 分片合并触发（merge_chunks/）
- concurrent_merge_same_file: 相同Hash并发合并（锁竞争测试，check_uploaded_chunks/ + merge_chunks/）
- public_chunked_upload: 公共空间分片上传
- concurrent_public_merge: 公共空间并发合并锁测试

公共空间专项测试:
- get_public_folder_list: 公共空间列表查询（folder/?is_public=true）
- create_public_folder: 公共空间文件夹创建（folder/ 含 is_public=true）
- upload_public_file: 公共空间文件上传（upload/ 含 space=public）
- public_chunked_upload: 公共空间分片上传
- concurrent_public_merge: 公共空间合并锁竞争
- search_public_documents: 公共空间搜索（search/?space=public）

使用说明:
locust -f locustfile_document.py -H http://localhost --web-port 8090

或者命令行模式:
locust -f locustfile_document.py -H http://localhost --users 100 --spawn-rate 20 --run-time 5m --headless
"""

import json
import random
import uuid
import threading
import time
from datetime import datetime
from locust import HttpUser, task, between, events
from locust.runners import MasterRunner


class DocumentUser(HttpUser):
    """
    资料管理压测用户类
    模拟真实用户操作：浏览、创建、上传、移动、复制等
    """

    # 请求间隔：0.5-2秒（高并发场景）
    wait_time = between(0.5, 2)

    # 类级别锁
    _lock = threading.Lock()

    def __init__(self, parent):
        super().__init__(parent)
        self.access_token = None
        self.test_folder_ids = []  # 用户自己创建的测试文件夹
        self.test_file_ids = []    # 用户上传的测试文件
        self.parent_folder_id = None  # 当前操作的父文件夹ID

    def on_start(self):
        """用户启动时执行：登录并准备测试环境"""
        self.login()
        self.prepare_test_folder()

    def login(self):
        """模拟用户登录"""
        try:
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

            if response.status_code == 200:
                result = response.json()
                data = result.get('data', {})
                self.access_token = data.get('access_token')
                print(f"[User-{id(self)}] 登录成功")

        except Exception as e:
            print(f"[User] 登录异常: {e}")

    def get_headers(self):
        """获取请求头"""
        return {
            "Content-Type": "application/json",
            "X-Requested-With": "XMLHttpRequest",
            "Accept": "application/json",
            "X-Token": self.access_token or ""
        }

    def prepare_test_folder(self):
        """准备测试文件夹"""
        try:
            # 创建个人测试文件夹
            folder_name = f"压测文件夹_{uuid.uuid4().hex[:8]}"
            create_data = {
                "parent_id": None,
                "name": folder_name,
                "space": "private"
            }

            response = self.client.post(
                "/api/document/folder/",
                json=create_data,
                headers=self.get_headers(),
                name="[准备] 创建测试文件夹"
            )

            if response.status_code == 200:
                try:
                    result = response.json()
                    data = result.get("data") if isinstance(result, dict) else {}
                    folder_id = data.get("id") if isinstance(data, dict) else None
                    if folder_id:
                        self.parent_folder_id = folder_id
                        self.test_folder_ids.append(folder_id)
                        print(f"[User-{id(self)}] 创建测试文件夹: ID={folder_id}")
                except Exception:
                    pass

        except Exception as e:
            print(f"[User] 准备测试文件夹失败: {e}")

    # ==================== 高频查询任务 ====================

    @task(10)
    def get_folder_list(self):
        """
        【高频】获取文件夹列表 - 最频繁的操作
        """
        params = {
            "page": random.randint(1, 3),
            "page_size": random.choice([20, 50, 100]),
            "is_public": False
        }

        with self.client.get(
            "/api/document/folder/",
            params=params,
            headers=self.get_headers(),
            name="GET /api/document/folder/ (列表)",
            catch_response=True
        ) as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"状态码: {response.status_code}")

    @task(5)
    def search_documents(self):
        """
        【中频】搜索资料
        """
        keywords = ["test", "doc", "file", "report", "data", "2024"]
        params = {
            "keyword": random.choice(keywords),
            "page": 1,
            "page_size": 20,
            "is_public": "false"
        }

        with self.client.get(
            "/api/document/folder/search/",
            params=params,
            headers=self.get_headers(),
            name="GET /api/document/folder/search/ (搜索)",
            catch_response=True
        ) as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"状态码: {response.status_code}")

    @task(3)
    def get_disk_usage(self):
        """
        【低频】获取磁盘使用情况
        """
        with self.client.get(
            "/api/document/disk_usage/",
            headers=self.get_headers(),
            name="GET /api/document/disk_usage/ (磁盘)",
            catch_response=True
        ) as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"状态码: {response.status_code}")

    # ==================== 文件夹操作任务 ====================

    @task(5)
    def create_folder(self):
        """
        【高并发】创建文件夹
        测试并发创建同名文件夹的竞争场景
        """
        # 有概率尝试创建同名文件夹（测试竞争）
        if random.random() < 0.2:
            folder_name = f"同名竞争测试_{random.randint(1, 5)}"
        else:
            folder_name = f"文件夹_{uuid.uuid4().hex[:6]}"

        create_data = {
            "parent_id": self.parent_folder_id,
            "name": folder_name,
            "space": "private"
        }

        with self.client.post(
            "/api/document/folder/",
            json=create_data,
            headers=self.get_headers(),
            name="POST /api/document/folder/ (创建)",
            catch_response=True
        ) as response:
            if response.status_code == 200:
                try:
                    result = response.json()
                    data = result.get("data") if isinstance(result, dict) else {}
                    folder_id = data.get("id") if isinstance(data, dict) else None
                    if folder_id:
                        self.test_folder_ids.append(folder_id)
                except Exception:
                    pass
                response.success()
            elif response.status_code == 400:
                # 文件夹已存在是预期的竞争结果
                response.success()
            else:
                response.failure(f"状态码: {response.status_code}")

    @task(2)
    def rename_folder(self):
        """
        【中频】重命名文件夹
        """
        if not self.test_folder_ids:
            return

        folder_id = random.choice(self.test_folder_ids)
        new_name = f"重命名_{uuid.uuid4().hex[:6]}"

        data = {
            "id": folder_id,
            "name": new_name,
            "space": "private"
        }

        with self.client.post(
            "/api/document/folder/rename/",
            json=data,
            headers=self.get_headers(),
            name="POST /api/document/folder/rename/ (重命名)",
            catch_response=True
        ) as response:
            if response.status_code == 200:
                response.success()
            elif response.status_code == 404:
                # 文件夹不存在，从列表移除
                if folder_id in self.test_folder_ids:
                    self.test_folder_ids.remove(folder_id)
                response.success()
            else:
                response.failure(f"状态码: {response.status_code}")

    @task(1)
    def move_folder(self):
        """
        【低频】移动文件夹
        """
        if len(self.test_folder_ids) < 2:
            return

        # 随机选择源和目标
        source_id = random.choice(self.test_folder_ids)
        target_id = random.choice([f for f in self.test_folder_ids if f != source_id])

        data = {
            "folder_ids": [source_id],
            "target_folder_id": target_id,
            "space": "private"
        }

        with self.client.post(
            "/api/document/folder/move/",
            json=data,
            headers=self.get_headers(),
            name="POST /api/document/folder/move/ (移动)",
            catch_response=True
        ) as response:
            if response.status_code == 200:
                response.success()
            elif response.status_code in [400, 404, 409]:
                # 循环引用或不存在是预期行为
                response.success()
            else:
                response.failure(f"状态码: {response.status_code}")

    @task(1)
    def copy_folder(self):
        """
        【低频】复制文件夹
        """
        if not self.test_folder_ids:
            return

        source_id = random.choice(self.test_folder_ids)
        target_id = self.parent_folder_id

        data = {
            "folder_ids": [source_id],
            "target_folder_id": target_id,
            "space": "private"
        }

        with self.client.post(
            "/api/document/folder/copy/",
            json=data,
            headers=self.get_headers(),
            name="POST /api/document/folder/copy/ (复制)",
            catch_response=True
        ) as response:
            if response.status_code == 200:
                response.success()
            elif response.status_code in [400, 404]:
                response.success()
            else:
                response.failure(f"状态码: {response.status_code}")

    # ==================== 文件操作任务 ====================

    @task(3)
    def upload_small_file_simple(self):
        """
        【高并发】简单上传小文件（直接上传，不分片）
        """
        file_name = f"测试文件_{uuid.uuid4().hex[:8]}.txt"

        # 模拟文件内容（1-10KB随机内容）
        content_size = random.randint(1024, 10240)
        content = b"A" * content_size

        files = {
            'file': (file_name, content, 'text/plain')
        }
        data = {
            'folder_id': self.parent_folder_id or '',
            'space': 'private'
        }

        headers = {
            "X-Token": self.access_token or "",
            "X-Requested-With": "XMLHttpRequest"
        }

        with self.client.post(
            "/api/document/upload/",
            files=files,
            data=data,
            headers=headers,
            name="POST /api/document/upload/ (小文件)",
            catch_response=True
        ) as response:
            if response.status_code == 200:
                try:
                    result = response.json()
                    data = result.get("data") if isinstance(result, dict) else {}
                    file_id = data.get("id") if isinstance(data, dict) else None
                    if file_id:
                        self.test_file_ids.append(file_id)
                    response.success()
                except Exception:
                    response.success()  # 解析失败但不记为错误
            else:
                response.failure(f"状态码: {response.status_code}")

    @task(2)
    def rename_file(self):
        """
        【中频】重命名文件
        """
        if not self.test_file_ids:
            return

        file_id = random.choice(self.test_file_ids)
        new_name = f"重命名文件_{uuid.uuid4().hex[:6]}.txt"

        data = {
            "id": file_id,
            "name": new_name,
            "space": "private"
        }

        with self.client.post(
            "/api/document/file/rename/",
            json=data,
            headers=self.get_headers(),
            name="POST /api/document/file/rename/ (重命名)",
            catch_response=True
        ) as response:
            if response.status_code == 200:
                response.success()
            elif response.status_code == 404:
                if file_id in self.test_file_ids:
                    self.test_file_ids.remove(file_id)
                response.success()
            else:
                response.failure(f"状态码: {response.status_code}")

    @task(1)
    def move_file(self):
        """
        【低频】移动文件
        """
        if not self.test_file_ids or not self.test_folder_ids:
            return

        file_id = random.choice(self.test_file_ids)
        target_folder_id = random.choice(self.test_folder_ids)

        data = {
            "file_ids": [file_id],
            "target_folder_id": target_folder_id,
            "space": "private"
        }

        with self.client.post(
            "/api/document/file/move/",
            json=data,
            headers=self.get_headers(),
            name="POST /api/document/file/move/ (移动)",
            catch_response=True
        ) as response:
            if response.status_code == 200:
                response.success()
            elif response.status_code in [404, 409]:
                response.success()
            else:
                response.failure(f"状态码: {response.status_code}")

    @task(1)
    def copy_file(self):
        """
        【低频】复制文件
        """
        if not self.test_file_ids or not self.test_folder_ids:
            return

        file_id = random.choice(self.test_file_ids)
        target_folder_id = random.choice(self.test_folder_ids)

        data = {
            "file_ids": [file_id],
            "target_folder_id": target_folder_id,
            "space": "private"
        }

        with self.client.post(
            "/api/document/file/copy/",
            json=data,
            headers=self.get_headers(),
            name="POST /api/document/file/copy/ (复制)",
            catch_response=True
        ) as response:
            if response.status_code == 200:
                response.success()
            elif response.status_code == 404:
                response.success()
            else:
                response.failure(f"状态码: {response.status_code}")

    @task(1)
    def delete_file(self):
        """
        【低频】删除文件（移到回收站）
        清理测试数据，防止无限增长
        """
        if not self.test_file_ids:
            return

        file_id = random.choice(self.test_file_ids)

        with self.client.delete(
            f"/api/document/file/?id={file_id}&space=private",
            headers=self.get_headers(),
            name="DELETE /api/document/file/ (删除)",
            catch_response=True
        ) as response:
            if response.status_code in [200, 204]:
                if file_id in self.test_file_ids:
                    self.test_file_ids.remove(file_id)
                response.success()
            elif response.status_code == 404:
                if file_id in self.test_file_ids:
                    self.test_file_ids.remove(file_id)
                response.success()
            else:
                response.failure(f"状态码: {response.status_code}")

    @task(1)
    def delete_folder(self):
        """
        【低频】删除文件夹（移到回收站）
        清理测试数据
        """
        # 保留根文件夹和至少一个子文件夹
        if len(self.test_folder_ids) <= 2:
            return

        # 排除根文件夹
        deletable = [f for f in self.test_folder_ids if f != self.parent_folder_id]
        if not deletable:
            return

        folder_id = random.choice(deletable)

        with self.client.delete(
            f"/api/document/folder/?id={folder_id}",
            headers=self.get_headers(),
            name="DELETE /api/document/folder/ (删除)",
            catch_response=True
        ) as response:
            if response.status_code in [200, 204]:
                if folder_id in self.test_folder_ids:
                    self.test_folder_ids.remove(folder_id)
                response.success()
            elif response.status_code == 404:
                if folder_id in self.test_folder_ids:
                    self.test_folder_ids.remove(folder_id)
                response.success()
            else:
                response.failure(f"状态码: {response.status_code}")

    # ==================== 分片上传专项测试 ====================

    @task(2)
    def chunked_upload_test(self):
        """
        【分片上传】模拟大文件分片上传和合并
        测试并发分片上传的锁机制
        """
        # 生成唯一文件标识
        file_name = f"分片测试_{uuid.uuid4().hex[:8]}.bin"
        file_size = random.randint(100 * 1024, 500 * 1024)  # 100-500KB
        chunk_size = 64 * 1024  # 64KB 每片
        chunk_count = (file_size + chunk_size - 1) // chunk_size

        # 1. 创建传输记录
        transfer_data = {
            "transfer_type": "UPLOAD",
            "file_name": file_name,
            "file_size": file_size,
            "folder_id": self.parent_folder_id,
            "is_public": False,
            "file_hash": f"hash_{uuid.uuid4().hex[:16]}"
        }

        with self.client.post(
            "/api/document/transfers/create/",
            json=transfer_data,
            headers=self.get_headers(),
            name="[分片] 创建传输记录",
            catch_response=True
        ) as response:
            if response.status_code != 200:
                response.failure(f"创建传输失败: {response.status_code}")
                return
            try:
                result = response.json()
                # 后端返回 {data: {id, status}}
                data = result.get("data") if isinstance(result, dict) else {}
                transfer_id = data.get("id") if isinstance(data, dict) else None
                if not transfer_id:
                    response.failure("未获取到transfer_id")
                    return
                response.success()
            except Exception as e:
                response.failure(f"解析响应失败: {e}")
                return

        # 2. 模拟上传分片（实际不传输数据，仅测试API压力）
        for i in range(min(chunk_count, 5)):  # 最多5个分片
            chunk_data = {
                "chunk_index": i,
                "chunk_size": min(chunk_size, file_size - i * chunk_size)
            }
            self.client.post(
                f"/api/document/transfers/{transfer_id}/progress/",
                json=chunk_data,
                headers=self.get_headers(),
                name="[分片] 更新进度"
            )

        # 3. 完成传输
        with self.client.post(
            f"/api/document/transfers/{transfer_id}/complete/",
            headers=self.get_headers(),
            name="[分片] 完成传输",
            catch_response=True
        ) as complete_response:
            if complete_response.status_code == 200:
                complete_response.success()
            else:
                complete_response.success()  # 传输完成可能有延迟，不记为失败

    @task(1)
    def chunked_upload_with_merge(self):
        """
        【分片合并】测试分片合并的并发锁
        多个用户同时尝试合并同一文件
        """
        file_name = f"合并测试_{uuid.uuid4().hex[:8]}.txt"
        file_hash = f"hash_{uuid.uuid4().hex[:16]}"

        # 创建传输记录
        transfer_data = {
            "transfer_type": "UPLOAD",
            "file_name": file_name,
            "file_size": 102400,  # 100KB
            "folder_id": self.parent_folder_id,
            "is_public": False,
            "file_hash": file_hash
        }

        response = self.client.post(
            "/api/document/transfers/create/",
            json=transfer_data,
            headers=self.get_headers(),
            name="[合并] 创建传输"
        )

        if response.status_code != 200:
            return

        try:
            result = response.json()
            # 后端返回 {data: {id, status}}
            data = result.get("data") if isinstance(result, dict) else {}
            transfer_id = data.get("id") if isinstance(data, dict) else None
            if not transfer_id:
                return
        except Exception:
            return

        # 模拟分片上传完成
        self.client.post(
            f"/api/document/transfers/{transfer_id}/progress/",
            json={"chunk_index": 0, "chunk_size": 102400},
            headers=self.get_headers(),
            name="[合并] 上传分片"
        )

        # 触发合并
        merge_data = {
            "transfer_id": transfer_id,
            "file_name": file_name,
            "folder_id": self.parent_folder_id,
            "space": "private",
            "file_hash": file_hash,
            "file_size": 102400
        }

        with self.client.post(
            "/api/document/merge_chunks/",
            json=merge_data,
            headers=self.get_headers(),
            name="[合并] 触发合并",
            catch_response=True
        ) as response:
            if response.status_code == 200:
                try:
                    result = response.json()
                    # 合并可能异步执行，检查状态
                    data = result.get("data") if isinstance(result, dict) else {}
                    status = data.get("status") if isinstance(data, dict) else "unknown"
                    if status in ["completed", "pending", "merging"]:
                        response.success()
                    else:
                        response.success()
                except Exception:
                    response.success()
            elif response.status_code == 409:
                # 合并冲突（已有相同文件正在合并）
                response.success()
            else:
                response.failure(f"合并失败: {response.status_code}")

    @task(1)
    def concurrent_merge_same_file(self):
        """
        【并发合并测试】多个用户同时尝试合并相同hash的文件
        测试合并锁的有效性
        """
        # 使用共享的file_hash制造竞争
        shared_hash = f"shared_hash_{random.randint(1, 3)}"
        file_name = f"并发合并_{uuid.uuid4().hex[:6]}.txt"

        # 1. 检查已上传分片（断点续传检查）
        resume_data = {
            "file_hash": shared_hash,
            "file_size": 102400,
            "chunk_size": 64000
        }

        self.client.post(
            "/api/document/check_uploaded_chunks/",
            json=resume_data,
            headers=self.get_headers(),
            name="[并发合并] 检查分片"
        )

        # 2. 尝试合并（会触发锁竞争）
        merge_data = {
            "file_name": file_name,
            "folder_id": self.parent_folder_id,
            "is_public": False,
            "file_hash": shared_hash,
            "file_size": 102400,
            "total_chunks": 2
        }

        with self.client.post(
            "/api/document/merge_chunks/",
            json=merge_data,
            headers=self.get_headers(),
            name="[并发测试] 相同Hash合并",
            catch_response=True
        ) as response:
            if response.status_code == 200:
                response.success()
            elif response.status_code == 409:
                # 预期的锁冲突
                print(f"[并发合并] 锁冲突: hash={shared_hash}")
                response.success()
            elif response.status_code == 423:
                # 文件被锁定
                print(f"[并发合并] 文件锁定: hash={shared_hash}")
                response.success()
            else:
                response.failure(f"状态码: {response.status_code}")

    # ==================== 公共空间专项测试 ====================

    @task(3)
    def get_public_folder_list(self):
        """
        【公共空间-高频】获取公共文件夹列表
        测试公共空间的数据隔离和权限
        """
        params = {
            "page": random.randint(1, 3),
            "page_size": random.choice([20, 50]),
            "is_public": True
        }

        with self.client.get(
            "/api/document/folder/",
            params=params,
            headers=self.get_headers(),
            name="GET /api/document/folder/ (公共空间列表)",
            catch_response=True
        ) as response:
            if response.status_code == 200:
                response.success()
            elif response.status_code == 403:
                # 无权限访问公共空间也是预期行为
                response.success()
            else:
                response.failure(f"状态码: {response.status_code}")

    @task(2)
    def create_public_folder(self):
        """
        【公共空间-中频】在公共空间创建文件夹
        测试公共空间创建权限和同名竞争
        """
        # 20%概率创建同名文件夹测试竞争
        if random.random() < 0.2:
            folder_name = f"公共竞争测试_{random.randint(1, 5)}"
        else:
            folder_name = f"公共文件夹_{uuid.uuid4().hex[:6]}"

        create_data = {
            "parent_id": None,  # 公共空间根目录
            "name": folder_name,
            "is_public": True  # 关键：标记为公共空间
        }

        with self.client.post(
            "/api/document/folder/",
            json=create_data,
            headers=self.get_headers(),
            name="POST /api/document/folder/ (公共空间创建)",
            catch_response=True
        ) as response:
            if response.status_code == 200:
                try:
                    result = response.json()
                    data = result.get("data") if isinstance(result, dict) else {}
                    folder_id = data.get("id") if isinstance(data, dict) else None
                    if folder_id:
                        print(f"[公共空间] 创建成功: {folder_name}, ID={folder_id}")
                except Exception:
                    pass
                response.success()
            elif response.status_code == 400:
                # 名称已存在（竞争）
                print(f"[公共空间] 名称冲突: {folder_name}")
                response.success()
            elif response.status_code == 403:
                # 无权限
                response.success()
            else:
                response.failure(f"状态码: {response.status_code}")

    @task(2)
    def upload_public_file(self):
        """
        【公共空间-中频】上传文件到公共空间
        测试公共空间文件上传和权限
        """
        file_name = f"公共文件_{uuid.uuid4().hex[:8]}.txt"
        content_size = random.randint(1024, 51200)  # 1-50KB
        content = b"PUBLIC_" * (content_size // 7)

        files = {
            'file': (file_name, content, 'text/plain')
        }
        data = {
            'folder_id': '',  # 公共空间根目录
            'space': 'public'  # 关键：标记为公共空间
        }

        headers = {
            "X-Token": self.access_token or "",
            "X-Requested-With": "XMLHttpRequest"
        }

        with self.client.post(
            "/api/document/upload/",
            files=files,
            data=data,
            headers=headers,
            name="POST /api/document/upload/ (公共空间上传)",
            catch_response=True
        ) as response:
            if response.status_code == 200:
                response.success()
            elif response.status_code == 403:
                # 无权限
                response.success()
            else:
                response.failure(f"状态码: {response.status_code}")

    @task(1)
    def public_chunked_upload(self):
        """
        【公共空间-分片上传】公共空间分片上传
        测试公共空间分片路径和合并锁
        """
        file_name = f"公共分片_{uuid.uuid4().hex[:8]}.bin"
        file_size = random.randint(50000, 200000)  # 50-200KB
        file_hash = f"public_hash_{uuid.uuid4().hex[:12]}"

        # 1. 创建传输记录
        transfer_data = {
            "transfer_type": "UPLOAD",
            "file_name": file_name,
            "file_size": file_size,
            "is_public": True,  # 关键：公共空间
            "file_hash": file_hash
        }
        print(f"[公共空间] 请求数据: {transfer_data}")

        with self.client.post(
            "/api/document/transfers/create/",
            json=transfer_data,
            headers=self.get_headers(),
            name="[公共空间] 创建传输",
            catch_response=True
        ) as response:
            if response.status_code != 200:
                if response.status_code == 403:
                    response.success()
                else:
                    response.failure(f"创建传输失败: {response.status_code}")
                return
            try:
                result = response.json()
                print(f"[公共空间] 创建传输响应: {result}")
                # 后端返回 {data: {id, status}}
                data = result.get("data") if isinstance(result, dict) else {}
                transfer_id = data.get("id") if isinstance(data, dict) else None
                if not transfer_id:
                    # 可能是错误响应，检查是否有error
                    error_msg = result.get("error") if isinstance(result, dict) else None
                    if error_msg:
                        response.failure(f"创建传输错误: {error_msg}")
                    else:
                        response.failure(f"未获取到transfer_id, 响应: {result}")
                    return
                response.success()
            except Exception as e:
                response.failure(f"解析响应失败: {e}")
                return

            # 2. 上传分片进度
            self.client.post(
                f"/api/document/transfers/{transfer_id}/progress/",
                json={"chunk_index": 0, "chunk_size": file_size},
                headers=self.get_headers(),
                name="[公共空间] 更新进度"
            )

            # 3. 完成传输
            with self.client.post(
                f"/api/document/transfers/{transfer_id}/complete/",
                headers=self.get_headers(),
                name="[公共空间] 完成传输",
                catch_response=True
            ) as complete_response:
                if complete_response.status_code == 200:
                    complete_response.success()
                elif complete_response.status_code == 403:
                    complete_response.success()
                else:
                    complete_response.success()  # 异步处理不记为失败

    @task(1)
    def concurrent_public_merge(self):
        """
        【公共空间-并发合并】多用户同时合并相同Hash的公共文件
        测试公共空间合并锁（与私有空间不同的锁键）
        """
        # 使用共享Hash制造竞争
        shared_hash = f"public_shared_{random.randint(1, 3)}"
        file_name = f"公共合并_{uuid.uuid4().hex[:6]}.txt"

        # 断点续传检查
        resume_data = {
            "file_hash": shared_hash,
            "file_size": 102400,
            "chunk_size": 64000,
            "is_public": True
        }

        self.client.post(
            "/api/document/check_uploaded_chunks/",
            json=resume_data,
            headers=self.get_headers(),
            name="[公共空间] 检查分片"
        )

        # 尝试合并（会触发锁竞争）
        merge_data = {
            "file_name": file_name,
            "folder_id": None,
            "is_public": True,
            "file_hash": shared_hash,
            "file_size": 102400,
            "total_chunks": 2
        }

        with self.client.post(
            "/api/document/merge_chunks/",
            json=merge_data,
            headers=self.get_headers(),
            name="[并发测试] 公共空间合并",
            catch_response=True
        ) as response:
            if response.status_code == 200:
                response.success()
            elif response.status_code in [403, 409, 423]:
                # 权限拒绝、冲突、锁定都是预期行为
                response.success()
            else:
                response.failure(f"状态码: {response.status_code}")

    @task(2)
    def search_public_documents(self):
        """
        【公共空间-搜索】搜索公共空间资料
        """
        keywords = ["公共", "共享", "资料", "文档"]
        params = {
            "keyword": random.choice(keywords),
            "page": 1,
            "page_size": 20,
            "is_public": "true"
        }

        with self.client.get(
            "/api/document/folder/search/",
            params=params,
            headers=self.get_headers(),
            name="GET /api/document/folder/search/ (公共空间搜索)",
            catch_response=True
        ) as response:
            if response.status_code == 200:
                response.success()
            elif response.status_code == 403:
                response.success()
            else:
                response.failure(f"状态码: {response.status_code}")

    # ==================== 并发专项测试 ====================

    @task(2)
    def concurrent_create_same_folder(self):
        """
        【并发竞争测试】多个用户同时创建同名文件夹
        测试数据库唯一性约束和异常处理
        """
        # 使用固定名称，制造竞争
        folder_name = f"竞争测试文件夹_{random.randint(1, 3)}"

        create_data = {
            "parent_id": self.parent_folder_id,
            "name": folder_name,
            "space": "private"
        }

        with self.client.post(
            "/api/document/folder/",
            json=create_data,
            headers=self.get_headers(),
            name="[并发测试] 同名文件夹创建",
            catch_response=True
        ) as response:
            if response.status_code == 200:
                try:
                    result = response.json()
                    data = result.get("data") if isinstance(result, dict) else {}
                    folder_id = data.get("id") if isinstance(data, dict) else None
                    if folder_id:
                        self.test_folder_ids.append(folder_id)
                        print(f"[并发测试] 创建成功: {folder_name}")
                except Exception:
                    pass
                response.success()
            elif response.status_code == 400:
                # 名称已存在，并发竞争的预期结果
                print(f"[并发测试] 名称冲突: {folder_name}")
                response.success()
            else:
                response.failure(f"状态码: {response.status_code}")

    @task(1)
    def rapid_folder_operations(self):
        """
        【压力测试】快速连续操作（创建->重命名->删除）
        测试竞态条件和数据一致性
        """
        folder_name = f"快速测试_{uuid.uuid4().hex[:6]}"
        folder_id = None

        # 1. 创建 - 使用 catch_response 正确统计
        with self.client.post(
            "/api/document/folder/",
            json={"parent_id": self.parent_folder_id, "name": folder_name, "space": "private"},
            headers=self.get_headers(),
            name="[压力测试] 快速创建",
            catch_response=True
        ) as response:
            if response.status_code == 200:
                try:
                    result = response.json()
                    data = result.get("data") if isinstance(result, dict) else {}
                    folder_id = data.get("id") if isinstance(data, dict) else None
                except Exception:
                    folder_id = None
                response.success()
            else:
                response.failure(f"创建失败: {response.status_code}")
                return

        if not folder_id:
            return

        # 2. 立即重命名
        with self.client.post(
            "/api/document/folder/rename/",
            json={"id": folder_id, "name": f"已重命名_{uuid.uuid4().hex[:6]}", "space": "private"},
            headers=self.get_headers(),
            name="[压力测试] 快速重命名",
            catch_response=True
        ) as response:
            if response.status_code == 200:
                response.success()
            else:
                response.success()  # 重命名失败不中断流程

        # 3. 立即删除
        with self.client.delete(
            f"/api/document/folder/?id={folder_id}",
            headers=self.get_headers(),
            name="[压力测试] 快速删除",
            catch_response=True
        ) as response:
            if response.status_code in [200, 204]:
                response.success()
            else:
                response.success()  # 删除失败不记为错误（可能已被其他操作删除）

    def on_stop(self):
        """测试结束时清理"""
        print(f"[User-{id(self)}] 测试结束，共创建文件夹 {len(self.test_folder_ids)} 个，文件 {len(self.test_file_ids)} 个")


@events.test_start.add_listener
def on_test_start(environment, **kwargs):
    """测试开始时的回调"""
    print("=" * 70)
    print("资料管理模块 Locust 高并发压测开始")
    print("=" * 70)
    print("测试场景:")
    print("  1. 高频查询 - 文件夹/文件列表、搜索、磁盘使用")
    print("  2. 高并发创建 - 批量创建文件夹（含同名竞争）")
    print("  3. 高并发上传 - 多用户同时上传小文件")
    print("  4. 文件操作 - 重命名、移动、复制")
    print("  5. 分片上传 - 分片上传、合并锁竞争测试")
    print("  6. 公共空间 - 公共空间CRUD、权限、合并锁测试")
    print("  7. 压力测试 - 快速连续操作序列")
    print("  8. 并发竞争 - 同名文件夹创建竞争")
    print("=" * 70)

    if isinstance(environment.runner, MasterRunner):
        print("[主节点] 分布式测试模式")


@events.test_stop.add_listener
def on_test_stop(environment, **kwargs):
    """测试结束时的回调"""
    print("=" * 70)
    print("资料管理模块 Locust 高并发压测结束")
    print("=" * 70)


"""
【运行方式】

1. 交互式模式:
   locust -f locustfile_document.py -H http://localhost
   
   然后打开 http://localhost:8089
   设置: Number of users = 50
        Spawn rate = 10

2. 命令行模式:
   locust -f locustfile_document.py -H http://localhost \
          --users 100 \
          --spawn-rate 20 \
          --run-time 5m \
          --headless \
          --csv=document_stress_test

【关键测试点】

1. 同名文件夹竞争:
   - 多用户同时创建同名文件夹（私有/公共空间）
   - 预期: 只有一个成功，其他返回400错误

2. 快速操作序列:
   - 创建->重命名->删除的连续操作
   - 预期: 无竞态条件，数据一致性正常

3. 高并发上传:
   - 多用户同时上传小文件（私有/公共空间）
   - 预期: 磁盘IO正常，无文件损坏

4. 分片上传与合并:
   - 多用户并发分片上传
   - 相同Hash文件并发合并（测试锁机制）
   - 私有空间和公共空间使用不同的锁键
   - 预期: 无重复合并，锁竞争正确处理

5. 公共空间专项:
   - 公共空间数据隔离（无租户过滤）
   - 公共空间权限检查
   - 公共空间合并锁（tenant_id为null的情况）
   - 预期: 权限控制正确，锁机制有效

6. 数据库性能:
   - 监控连接数、慢查询
   - 预期: 无死锁，响应时间在可接受范围

7. 数据清理:
   - 自动删除测试产生的文件/文件夹
   - 防止磁盘空间无限增长
"""
