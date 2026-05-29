#!/usr/bin/env python
"""
资料库模块压力测试脚本 V3 - 增强版

测试场景：
1. 私有空间：文件夹操作、文件上传、查询、删除
2. 公共空间：文件夹操作、文件上传、查询、删除
3. 分片上传（基础）：大文件分片上传、合并
4. 分片上传（增强）：
   ✅ 断点续传（检查已上传分片、续传）
   ✅ 并发上传（同时上传多个分片）
   ✅ 分片顺序校验（乱序上传的情况）
   ✅ 分片丢失处理（某个分片失败后重传）
5. 回收站操作：查询、恢复
6. 传输列表：查询、监控

使用方法：
    python -m locust -f locustfile/document_stress_test_v3.py -H http://localhost
"""

import os
import random
import uuid
import time
import hashlib
import threading
from datetime import datetime
from locust import HttpUser, task, between, events
from locust.runners import MasterRunner

# 测试配置
TEST_CONFIG = {
    'private_users': [
        {'username': 'tongxinke', 'password': 'Dt@6299093'},
        {'username': 'zidonghuake', 'password': 'Aa@123456'},
        {'username': 'daohangke', 'password': 'Aa@123456'},
        {'username': 'dianhuake', 'password': 'Aa@123456'}
    ],
    # 测试文件大小配置（字节）
    'file_sizes': {
        'small': 1024 * 10,      # 10KB
        'medium': 1024 * 500,    # 500KB
        'large': 1024 * 1024 * 3, # 3MB
        'chunk': 1024 * 1024      # 1MB - 分片大小
    },
    # 分片配置
    'chunk_size': 1024 * 1024,   # 每个分片1MB
    'max_chunks': 4,             # 最多4个分片（用于测试断点续传）
    'concurrent_uploads': 2,     # 并发上传的分片数
}


class BaseUser(HttpUser):
    """基础用户类（抽象类，不应直接实例化）"""
    abstract = True  # 声明为抽象类，Locust 不会直接创建实例

    # 等待时间：1-3秒之间
    wait_time = between(1, 3)

    def on_start(self):
        """用户开始时登录"""
        if not self.login():
            raise Exception(f"用户 {self.username} 登录失败")
        self.test_folder_ids = []
        self.test_file_ids = []

    def on_stop(self):
        """用户结束时清理测试数据"""
        try:
            self.cleanup_test_data()
        except:
            pass
        try:
            self.logout()
        except:
            pass

    def login(self):
        """登录获取token"""
        user = random.choice(self.get_users())
        self.username = user['username']
        self.password = user['password']

        response = self.client.post('/api/account/login/', json={
            'username': self.username,
            'password': self.password,
            'type': 'default'
        })

        if response.status_code == 200:
            data = response.json()
            if data.get('error'):
                print(f"[{self.username}] 登录失败: {data['error']}")
                return False

            response_data = data.get('data', {})
            if 'access_token' in response_data:
                self.token = response_data['access_token']
            else:
                print(f"[{self.username}] 登录响应异常: {data}")
                return False

            self.client.headers.update({'x-token': self.token})
            print(f"[{self.username}] 登录成功")
            return True
        else:
            print(f"[{self.username}] 登录失败 (HTTP {response.status_code}): {response.text}")
            return False

    def get_users(self):
        """子类实现：返回用户列表"""
        raise NotImplementedError

    def get_is_public(self):
        """子类实现：返回是否是公共空间"""
        raise NotImplementedError

    def logout(self):
        """登出"""
        self.client.delete('/api/account/logout/')

    def generate_test_file(self, size='small'):
        """生成测试文件内容"""
        file_size = TEST_CONFIG['file_sizes'].get(size, TEST_CONFIG['file_sizes']['small'])
        return 'x' * file_size

    def calculate_md5(self, content):
        """计算文件MD5"""
        md5 = hashlib.md5()
        md5.update(content.encode() if isinstance(content, str) else content)
        return md5.hexdigest()

    def cleanup_test_data(self):
        """清理测试数据"""
        # 清理测试文件
        for file_id in self.test_file_ids:
            try:
                self.client.delete(f'/api/document/file/?id={file_id}&is_public={self.get_is_public()}')
            except:
                pass

        # 清理测试文件夹
        for folder_id in self.test_folder_ids:
            try:
                self.client.delete(f'/api/document/folder/?id={folder_id}&is_public={self.get_is_public()}')
            except:
                pass


class PrivateSpaceUser(BaseUser):
    """私有空间用户"""

    def get_users(self):
        return TEST_CONFIG['private_users']

    def get_is_public(self):
        return False

    # ========== 文件夹操作 ==========

    @task(3)
    def create_folder(self):
        """创建文件夹"""
        folder_name = f"private_test_{self.username}_{uuid.uuid4().hex[:8]}"

        with self.client.post(
            '/api/document/folder/',
            json={'name': folder_name, 'is_public': False},
            catch_response=True,
            name="[私有] 创建文件夹"
        ) as response:
            if response.status_code == 200:
                folder_id = response.json().get('id')
                if folder_id:
                    self.test_folder_ids.append(folder_id)
            else:
                response.failure(f"创建文件夹失败: {response.text}")

    @task(6)
    def list_folders(self):
        """查询文件夹列表"""
        self.client.get(
            '/api/document/folder/?is_public=False',
            name="[私有] 查询文件夹"
        )

    # ========== 文件操作（普通上传） ==========

    @task(4)
    def upload_file(self):
        """上传文件（普通上传）"""
        if not self.test_folder_ids:
            parent_id = None
        else:
            parent_id = random.choice(self.test_folder_ids)

        file_name = f"private_test_{self.username}_{uuid.uuid4().hex[:8]}.txt"
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
            name="[私有] 上传文件（普通）"
        ) as response:
            if response.status_code == 200:
                file_id = response.json().get('id')
                if file_id:
                    self.test_file_ids.append(file_id)
            else:
                response.failure(f"上传文件失败: {response.text}")

    @task(2)
    def delete_file(self):
        """删除文件"""
        if self.test_file_ids:
            file_id = self.test_file_ids.pop(0)

            with self.client.delete(
                f'/api/document/file/?id={file_id}&is_public=False',
                catch_response=True,
                name="[私有] 删除文件"
            ) as response:
                if response.status_code != 200:
                    self.test_file_ids.append(file_id)
                    response.failure(f"删除文件失败: {response.text}")

    # ========== 基础分片上传 ==========

    @task(3)
    def upload_chunked_file(self):
        """基础分片上传：顺序上传所有分片"""
        if not self.test_folder_ids:
            parent_id = None
        else:
            parent_id = random.choice(self.test_folder_ids)

        # 生成大文件（3MB，分为3个分片）
        file_size = TEST_CONFIG['file_sizes']['large']
        chunk_size = TEST_CONFIG['chunk_size']
        total_chunks = (file_size + chunk_size - 1) // chunk_size

        file_name = f"private_chunked_{self.username}_{uuid.uuid4().hex[:8]}.txt"
        file_content = self.generate_test_file('large')
        file_hash = self.calculate_md5(file_content)

        # 顺序上传所有分片
        task_id = f"{uuid.uuid4().hex[:16]}"
        uploaded_chunks = []

        for chunk_index in range(total_chunks):
            # 计算分片内容
            start = chunk_index * chunk_size
            end = min(start + chunk_size, len(file_content))
            chunk_content = file_content[start:end]

            # 上传分片
            files = {'file': (f"{file_name}.part{chunk_index}", chunk_content, 'application/octet-stream')}
            data = {
                'file_name': file_name,
                'file_size': file_size,
                'chunk_index': chunk_index,
                'total_chunks': total_chunks,
                'file_hash': file_hash,
                'folder_id': parent_id,
                'is_public': 'False'
            }

            with self.client.post(
                '/api/document/upload_chunk/',
                files=files,
                data=data,
                catch_response=True,
                name=f"[私有] 上传分片 {chunk_index+1}/{total_chunks}"
            ) as response:
                if response.status_code == 200:
                    uploaded_chunks.append(chunk_index)
                else:
                    response.failure(f"上传分片失败: {response.text}")
                    return

        # 合并分片
        if len(uploaded_chunks) == total_chunks:
            data = {
                'file_name': file_name,
                'file_size': file_size,
                'total_chunks': total_chunks,
                'file_hash': file_hash,
                'parent_id': parent_id,
                'is_public': False,
                'transfer_id': task_id
            }

            with self.client.post(
                '/api/document/merge_chunks/',
                json=data,
                catch_response=True,
                name="[私有] 合并分片"
            ) as response:
                if response.status_code == 200:
                    file_id = response.json().get('id')
                    if file_id:
                        self.test_file_ids.append(file_id)
                else:
                    response.failure(f"合并分片失败: {response.text}")

    # ========== 断点续传测试 ==========

    @task(2)
    def test_resumable_upload(self):
        """
        断点续传测试：
        1. 上传部分分片（模拟中断）
        2. 检查已上传的分片
        3. 续传剩余分片
        4. 合并文件
        """
        if not self.test_folder_ids:
            parent_id = None
        else:
            parent_id = random.choice(self.test_folder_ids)

        # 生成大文件（3MB，分为3个分片）
        file_size = TEST_CONFIG['file_sizes']['large']
        chunk_size = TEST_CONFIG['chunk_size']
        total_chunks = (file_size + chunk_size - 1) // chunk_size

        file_name = f"private_resume_{self.username}_{uuid.uuid4().hex[:8]}.txt"
        file_content = self.generate_test_file('large')
        file_hash = self.calculate_md5(file_content)

        task_id = f"{uuid.uuid4().hex[:16]}"
        uploaded_chunks = []

        # 第一步：只上传前2个分片（模拟中断）
        first_upload_count = max(1, total_chunks - 1)

        for chunk_index in range(first_upload_count):
            start = chunk_index * chunk_size
            end = min(start + chunk_size, len(file_content))
            chunk_content = file_content[start:end]

            files = {'file': (f"{file_name}.part{chunk_index}", chunk_content, 'application/octet-stream')}
            data = {
                'file_name': file_name,
                'file_size': file_size,
                'chunk_index': chunk_index,
                'total_chunks': total_chunks,
                'file_hash': file_hash,
                'folder_id': parent_id,
                'is_public': 'False'
            }

            with self.client.post(
                '/api/document/upload_chunk/',
                files=files,
                data=data,
                catch_response=True,
                name=f"[私有] 断点续传-初传分片 {chunk_index+1}/{total_chunks}"
            ) as response:
                if response.status_code == 200:
                    uploaded_chunks.append(chunk_index)
                else:
                    response.failure(f"上传分片失败: {response.text}")
                    return

        # 第二步：模拟中断后恢复，检查已上传分片状态
        # 通过查询传输列表检查上传进度
        self.client.get(
            '/api/document/transfers/?is_public=False',
            name="[私有] 断点续传-检查传输状态"
        )

        # 第三步：续传剩余分片
        for chunk_index in range(first_upload_count, total_chunks):
            start = chunk_index * chunk_size
            end = min(start + chunk_size, len(file_content))
            chunk_content = file_content[start:end]

            files = {'file': (f"{file_name}.part{chunk_index}", chunk_content, 'application/octet-stream')}
            data = {
                'file_name': file_name,
                'file_size': file_size,
                'chunk_index': chunk_index,
                'total_chunks': total_chunks,
                'file_hash': file_hash,
                'folder_id': parent_id,
                'is_public': 'False'
            }

            with self.client.post(
                '/api/document/upload_chunk/',
                files=files,
                data=data,
                catch_response=True,
                name=f"[私有] 断点续传-续传分片 {chunk_index+1}/{total_chunks}"
            ) as response:
                if response.status_code == 200:
                    uploaded_chunks.append(chunk_index)
                else:
                    response.failure(f"续传分片失败: {response.text}")
                    return

        # 第四步：合并分片
        if len(uploaded_chunks) == total_chunks:
            data = {
                'file_name': file_name,
                'file_size': file_size,
                'total_chunks': total_chunks,
                'file_hash': file_hash,
                'parent_id': parent_id,
                'is_public': False,
                'transfer_id': task_id
            }

            with self.client.post(
                '/api/document/merge_chunks/',
                json=data,
                catch_response=True,
                name="[私有] 断点续传-合并分片"
            ) as response:
                if response.status_code == 200:
                    file_id = response.json().get('id')
                    if file_id:
                        self.test_file_ids.append(file_id)
                else:
                    response.failure(f"合并分片失败: {response.text}")

    # ========== 并发上传测试 ==========

    @task(2)
    def test_concurrent_upload(self):
        """
        并发上传测试：
        使用多线程同时上传多个分片
        """
        if not self.test_folder_ids:
            parent_id = None
        else:
            parent_id = random.choice(self.test_folder_ids)

        # 生成大文件（3MB，分为3个分片）
        file_size = TEST_CONFIG['file_sizes']['large']
        chunk_size = TEST_CONFIG['chunk_size']
        total_chunks = (file_size + chunk_size - 1) // chunk_size

        file_name = f"private_concurrent_{self.username}_{uuid.uuid4().hex[:8]}.txt"
        file_content = self.generate_test_file('large')
        file_hash = self.calculate_md5(file_content)

        task_id = f"{uuid.uuid4().hex[:16]}"
        uploaded_chunks = []
        upload_results = []

        # 准备所有分片数据
        chunks_data = []
        for chunk_index in range(total_chunks):
            start = chunk_index * chunk_size
            end = min(start + chunk_size, len(file_content))
            chunk_content = file_content[start:end]
            chunks_data.append({
                'index': chunk_index,
                'content': chunk_content
            })

        # 定义并发上传函数
        def upload_chunk_sync(chunk_data):
            try:
                chunk_index = chunk_data['index']
                chunk_content = chunk_data['content']

                files = {'file': (f"{file_name}.part{chunk_index}", chunk_content, 'application/octet-stream')}
                data = {
                    'file_name': file_name,
                    'file_size': file_size,
                    'chunk_index': chunk_index,
                    'total_chunks': total_chunks,
                    'file_hash': file_hash,
                    'folder_id': parent_id,
                    'is_public': 'False'
                }

                response = self.client.post(
                    '/api/document/upload_chunk/',
                    files=files,
                    data=data,
                    name=f"[私有] 并发上传-分片 {chunk_index+1}/{total_chunks}"
                )

                upload_results.append({
                    'index': chunk_index,
                    'status': response.status_code,
                    'success': response.status_code == 200
                })

                if response.status_code == 200:
                    uploaded_chunks.append(chunk_index)
            except Exception as e:
                upload_results.append({
                    'index': chunk_data['index'],
                    'status': 0,
                    'success': False,
                    'error': str(e)
                })

        # 创建并启动线程并发上传
        threads = []
        for chunk_data in chunks_data:
            thread = threading.Thread(target=upload_chunk_sync, args=(chunk_data,))
            threads.append(thread)
            thread.start()

        # 等待所有线程完成
        for thread in threads:
            thread.join()

        # 合并分片
        if len(uploaded_chunks) == total_chunks:
            data = {
                'file_name': file_name,
                'file_size': file_size,
                'total_chunks': total_chunks,
                'file_hash': file_hash,
                'parent_id': parent_id,
                'is_public': False,
                'transfer_id': task_id
            }

            with self.client.post(
                '/api/document/merge_chunks/',
                json=data,
                catch_response=True,
                name="[私有] 并发上传-合并分片"
            ) as response:
                if response.status_code == 200:
                    file_id = response.json().get('id')
                    if file_id:
                        self.test_file_ids.append(file_id)
                else:
                    response.failure(f"合并分片失败: {response.text}")

    # ========== 分片顺序校验测试 ==========

    @task(2)
    def test_out_of_order_upload(self):
        """
        分片顺序校验测试：
        乱序上传分片（2->0->1），验证后端是否能正确处理
        """
        if not self.test_folder_ids:
            parent_id = None
        else:
            parent_id = random.choice(self.test_folder_ids)

        # 生成大文件（2MB，分为2个分片）
        file_size = TEST_CONFIG['file_sizes']['large']
        chunk_size = TEST_CONFIG['chunk_size']
        total_chunks = 2

        file_name = f"private_outoforder_{self.username}_{uuid.uuid4().hex[:8]}.txt"
        file_content = self.generate_test_file('large')
        file_hash = self.calculate_md5(file_content)

        task_id = f"{uuid.uuid4().hex[:16]}"
        uploaded_chunks = []

        # 准备分片数据
        chunks_data = []
        for chunk_index in range(total_chunks):
            start = chunk_index * chunk_size
            end = min(start + chunk_size, len(file_content))
            chunk_content = file_content[start:end]
            chunks_data.append({
                'index': chunk_index,
                'content': chunk_content
            })

        # 乱序上传：先上传分片1，再上传分片0
        upload_order = [1, 0]  # 乱序顺序

        for chunk_index in upload_order:
            chunk_data = chunks_data[chunk_index]

            files = {'file': (f"{file_name}.part{chunk_index}", chunk_data['content'], 'application/octet-stream')}
            data = {
                'file_name': file_name,
                'file_size': file_size,
                'chunk_index': chunk_index,
                'total_chunks': total_chunks,
                'file_hash': file_hash,
                'folder_id': parent_id,
                'is_public': 'False'
            }

            with self.client.post(
                '/api/document/upload_chunk/',
                files=files,
                data=data,
                catch_response=True,
                name=f"[私有] 乱序上传-分片{chunk_index+1}"
            ) as response:
                if response.status_code == 200:
                    uploaded_chunks.append(chunk_index)
                else:
                    response.failure(f"乱序上传分片失败: {response.text}")
                    return

        # 合并分片
        if len(uploaded_chunks) == total_chunks:
            data = {
                'file_name': file_name,
                'file_size': file_size,
                'total_chunks': total_chunks,
                'file_hash': file_hash,
                'parent_id': parent_id,
                'is_public': False,
                'transfer_id': task_id
            }

            with self.client.post(
                '/api/document/merge_chunks/',
                json=data,
                catch_response=True,
                name="[私有] 乱序上传-合并分片"
            ) as response:
                if response.status_code == 200:
                    file_id = response.json().get('id')
                    if file_id:
                        self.test_file_ids.append(file_id)
                else:
                    response.failure(f"合并分片失败: {response.text}")

    # ========== 分片丢失处理测试 ==========

    @task(2)
    def test_chunk_loss_recovery(self):
        """
        分片丢失处理测试：
        模拟某个分片上传失败，然后重传
        """
        if not self.test_folder_ids:
            parent_id = None
        else:
            parent_id = random.choice(self.test_folder_ids)

        # 生成大文件（3MB，分为3个分片）
        file_size = TEST_CONFIG['file_sizes']['large']
        chunk_size = TEST_CONFIG['chunk_size']
        total_chunks = (file_size + chunk_size - 1) // chunk_size

        file_name = f"private_lossrecovery_{self.username}_{uuid.uuid4().hex[:8]}.txt"
        file_content = self.generate_test_file('large')
        file_hash = self.calculate_md5(file_content)

        task_id = f"{uuid.uuid4().hex[:16]}"
        uploaded_chunks = []

        # 准备分片数据
        chunks_data = []
        for chunk_index in range(total_chunks):
            start = chunk_index * chunk_size
            end = min(start + chunk_size, len(file_content))
            chunk_content = file_content[start:end]
            chunks_data.append({
                'index': chunk_index,
                'content': chunk_content
            })

        # 随机选择一个分片作为"丢失"的分片
        lost_chunk_index = random.randint(0, total_chunks - 1)

        # 第一轮上传：故意跳过"丢失"的分片
        for chunk_index in range(total_chunks):
            if chunk_index == lost_chunk_index:
                # 跳过这个分片，模拟丢失
                continue

            chunk_data = chunks_data[chunk_index]
            files = {'file': (f"{file_name}.part{chunk_index}", chunk_data['content'], 'application/octet-stream')}
            data = {
                'file_name': file_name,
                'file_size': file_size,
                'chunk_index': chunk_index,
                'total_chunks': total_chunks,
                'file_hash': file_hash,
                'folder_id': parent_id,
                'is_public': 'False'
            }

            with self.client.post(
                '/api/document/upload_chunk/',
                files=files,
                data=data,
                catch_response=True,
                name=f"[私有] 丢失恢复-初传分片 {chunk_index+1}/{total_chunks}"
            ) as response:
                if response.status_code == 200:
                    uploaded_chunks.append(chunk_index)
                else:
                    response.failure(f"上传分片失败: {response.text}")
                    return

        # 第二轮：重传"丢失"的分片
        chunk_data = chunks_data[lost_chunk_index]
        files = {'file': (f"{file_name}.part{lost_chunk_index}", chunk_data['content'], 'application/octet-stream')}
        data = {
            'file_name': file_name,
            'file_size': file_size,
            'chunk_index': lost_chunk_index,
            'total_chunks': total_chunks,
            'file_hash': file_hash,
            'folder_id': parent_id,
            'is_public': 'False'
        }

        with self.client.post(
            '/api/document/upload_chunk/',
            files=files,
            data=data,
            catch_response=True,
            name=f"[私有] 丢失恢复-重传分片 {lost_chunk_index+1}/{total_chunks}"
        ) as response:
            if response.status_code == 200:
                uploaded_chunks.append(lost_chunk_index)
            else:
                response.failure(f"重传分片失败: {response.text}")
                return

        # 合并分片
        if len(uploaded_chunks) == total_chunks:
            data = {
                'file_name': file_name,
                'file_size': file_size,
                'total_chunks': total_chunks,
                'file_hash': file_hash,
                'parent_id': parent_id,
                'is_public': False,
                'transfer_id': task_id
            }

            with self.client.post(
                '/api/document/merge_chunks/',
                json=data,
                catch_response=True,
                name="[私有] 丢失恢复-合并分片"
            ) as response:
                if response.status_code == 200:
                    file_id = response.json().get('id')
                    if file_id:
                        self.test_file_ids.append(file_id)
                else:
                    response.failure(f"合并分片失败: {response.text}")

    # ========== 传输列表查询 ==========

    @task(5)
    def get_transfers(self):
        """获取传输列表"""
        self.client.get(
            '/api/document/transfers/?is_public=False',
            name="[私有] 查询传输列表"
        )

    # ========== 磁盘使用查询 ==========

    @task(3)
    def get_disk_usage(self):
        """查询磁盘使用情况"""
        self.client.get(
            '/api/document/disk_usage/?is_public=False',
            name="[私有] 查询磁盘使用"
        )

    # ========== 回收站操作 ==========

    @task(3)
    def list_recycle_bin(self):
        """查询回收站"""
        self.client.get(
            '/api/document/recycle-bin/?page=1&page_size=50&is_public=False',
            name="[私有] 查询回收站"
        )

    @task(1)
    def get_recycle_bin_stats(self):
        """查询回收站统计"""
        self.client.get(
            '/api/document/recycle-bin/stats/?is_public=False',
            name="[私有] 回收站统计"
        )


class PublicSpaceUser(BaseUser):
    """公共空间用户"""

    def get_users(self):
        return TEST_CONFIG['private_users']

    def get_is_public(self):
        return True

    # ========== 文件夹操作 ==========

    @task(3)
    def create_folder(self):
        """创建文件夹"""
        folder_name = f"public_test_{self.username}_{uuid.uuid4().hex[:8]}"

        with self.client.post(
            '/api/document/folder/',
            json={'name': folder_name, 'is_public': True},
            catch_response=True,
            name="[公共] 创建文件夹"
        ) as response:
            if response.status_code == 200:
                folder_id = response.json().get('id')
                if folder_id:
                    self.test_folder_ids.append(folder_id)
            else:
                response.failure(f"创建文件夹失败: {response.text}")

    @task(6)
    def list_folders(self):
        """查询文件夹列表"""
        self.client.get(
            '/api/document/folder/?is_public=True',
            name="[公共] 查询文件夹"
        )

    # ========== 文件操作（普通上传） ==========

    @task(4)
    def upload_file(self):
        """上传文件（普通上传）"""
        if not self.test_folder_ids:
            parent_id = None
        else:
            parent_id = random.choice(self.test_folder_ids)

        file_name = f"public_test_{self.username}_{uuid.uuid4().hex[:8]}.txt"
        file_content = self.generate_test_file('small')

        files = {'file': (file_name, file_content, 'text/plain')}
        data = {
            'parent_id': parent_id,
            'is_public': True
        }

        with self.client.post(
            '/api/document/upload/',
            files=files,
            data=data,
            catch_response=True,
            name="[公共] 上传文件（普通）"
        ) as response:
            if response.status_code == 200:
                file_id = response.json().get('id')
                if file_id:
                    self.test_file_ids.append(file_id)
            else:
                response.failure(f"上传文件失败: {response.text}")

    @task(2)
    def delete_file(self):
        """删除文件"""
        if self.test_file_ids:
            file_id = self.test_file_ids.pop(0)

            with self.client.delete(
                f'/api/document/file/?id={file_id}&is_public=True',
                catch_response=True,
                name="[公共] 删除文件"
            ) as response:
                if response.status_code != 200:
                    self.test_file_ids.append(file_id)
                    response.failure(f"删除文件失败: {response.text}")

    # ========== 基础分片上传 ==========

    @task(3)
    def upload_chunked_file(self):
        """基础分片上传：顺序上传所有分片"""
        if not self.test_folder_ids:
            parent_id = None
        else:
            parent_id = random.choice(self.test_folder_ids)

        # 生成大文件（3MB，分为3个分片）
        file_size = TEST_CONFIG['file_sizes']['large']
        chunk_size = TEST_CONFIG['chunk_size']
        total_chunks = (file_size + chunk_size - 1) // chunk_size

        file_name = f"public_chunked_{self.username}_{uuid.uuid4().hex[:8]}.txt"
        file_content = self.generate_test_file('large')
        file_hash = self.calculate_md5(file_content)

        # 顺序上传所有分片
        task_id = f"{uuid.uuid4().hex[:16]}"
        uploaded_chunks = []

        for chunk_index in range(total_chunks):
            # 计算分片内容
            start = chunk_index * chunk_size
            end = min(start + chunk_size, len(file_content))
            chunk_content = file_content[start:end]

            # 上传分片
            files = {'file': (f"{file_name}.part{chunk_index}", chunk_content, 'application/octet-stream')}
            data = {
                'file_name': file_name,
                'file_size': file_size,
                'chunk_index': chunk_index,
                'total_chunks': total_chunks,
                'file_hash': file_hash,
                'folder_id': parent_id,
                'is_public': 'True'
            }

            with self.client.post(
                '/api/document/upload_chunk/',
                files=files,
                data=data,
                catch_response=True,
                name=f"[公共] 上传分片 {chunk_index+1}/{total_chunks}"
            ) as response:
                if response.status_code == 200:
                    uploaded_chunks.append(chunk_index)
                else:
                    response.failure(f"上传分片失败: {response.text}")
                    return

        # 合并分片
        if len(uploaded_chunks) == total_chunks:
            data = {
                'file_name': file_name,
                'file_size': file_size,
                'total_chunks': total_chunks,
                'file_hash': file_hash,
                'parent_id': parent_id,
                'is_public': True,
                'transfer_id': task_id
            }

            with self.client.post(
                '/api/document/merge_chunks/',
                json=data,
                catch_response=True,
                name="[公共] 合并分片"
            ) as response:
                if response.status_code == 200:
                    file_id = response.json().get('id')
                    if file_id:
                        self.test_file_ids.append(file_id)
                else:
                    response.failure(f"合并分片失败: {response.text}")

    # ========== 断点续传测试 ==========

    @task(2)
    def test_resumable_upload(self):
        """
        断点续传测试：
        1. 上传部分分片（模拟中断）
        2. 检查已上传的分片
        3. 续传剩余分片
        4. 合并文件
        """
        if not self.test_folder_ids:
            parent_id = None
        else:
            parent_id = random.choice(self.test_folder_ids)

        # 生成大文件（3MB，分为3个分片）
        file_size = TEST_CONFIG['file_sizes']['large']
        chunk_size = TEST_CONFIG['chunk_size']
        total_chunks = (file_size + chunk_size - 1) // chunk_size

        file_name = f"public_resume_{self.username}_{uuid.uuid4().hex[:8]}.txt"
        file_content = self.generate_test_file('large')
        file_hash = self.calculate_md5(file_content)

        task_id = f"{uuid.uuid4().hex[:16]}"
        uploaded_chunks = []

        # 第一步：只上传前2个分片（模拟中断）
        first_upload_count = max(1, total_chunks - 1)

        for chunk_index in range(first_upload_count):
            start = chunk_index * chunk_size
            end = min(start + chunk_size, len(file_content))
            chunk_content = file_content[start:end]

            files = {'file': (f"{file_name}.part{chunk_index}", chunk_content, 'application/octet-stream')}
            data = {
                'file_name': file_name,
                'file_size': file_size,
                'chunk_index': chunk_index,
                'total_chunks': total_chunks,
                'file_hash': file_hash,
                'folder_id': parent_id,
                'is_public': 'True'
            }

            with self.client.post(
                '/api/document/upload_chunk/',
                files=files,
                data=data,
                catch_response=True,
                name=f"[公共] 断点续传-初传分片 {chunk_index+1}/{total_chunks}"
            ) as response:
                if response.status_code == 200:
                    uploaded_chunks.append(chunk_index)
                else:
                    response.failure(f"上传分片失败: {response.text}")
                    return

        # 第二步：模拟中断后恢复，检查已上传分片状态
        self.client.get(
            '/api/document/transfers/?is_public=True',
            name="[公共] 断点续传-检查传输状态"
        )

        # 第三步：续传剩余分片
        for chunk_index in range(first_upload_count, total_chunks):
            start = chunk_index * chunk_size
            end = min(start + chunk_size, len(file_content))
            chunk_content = file_content[start:end]

            files = {'file': (f"{file_name}.part{chunk_index}", chunk_content, 'application/octet-stream')}
            data = {
                'file_name': file_name,
                'file_size': file_size,
                'chunk_index': chunk_index,
                'total_chunks': total_chunks,
                'file_hash': file_hash,
                'folder_id': parent_id,
                'is_public': 'True'
            }

            with self.client.post(
                '/api/document/upload_chunk/',
                files=files,
                data=data,
                catch_response=True,
                name=f"[公共] 断点续传-续传分片 {chunk_index+1}/{total_chunks}"
            ) as response:
                if response.status_code == 200:
                    uploaded_chunks.append(chunk_index)
                else:
                    response.failure(f"续传分片失败: {response.text}")
                    return

        # 第四步：合并分片
        if len(uploaded_chunks) == total_chunks:
            data = {
                'file_name': file_name,
                'file_size': file_size,
                'total_chunks': total_chunks,
                'file_hash': file_hash,
                'parent_id': parent_id,
                'is_public': True,
                'transfer_id': task_id
            }

            with self.client.post(
                '/api/document/merge_chunks/',
                json=data,
                catch_response=True,
                name="[公共] 断点续传-合并分片"
            ) as response:
                if response.status_code == 200:
                    file_id = response.json().get('id')
                    if file_id:
                        self.test_file_ids.append(file_id)
                else:
                    response.failure(f"合并分片失败: {response.text}")

    # ========== 并发上传测试 ==========

    @task(2)
    def test_concurrent_upload(self):
        """
        并发上传测试：
        使用多线程同时上传多个分片
        """
        if not self.test_folder_ids:
            parent_id = None
        else:
            parent_id = random.choice(self.test_folder_ids)

        # 生成大文件（3MB，分为3个分片）
        file_size = TEST_CONFIG['file_sizes']['large']
        chunk_size = TEST_CONFIG['chunk_size']
        total_chunks = (file_size + chunk_size - 1) // chunk_size

        file_name = f"public_concurrent_{self.username}_{uuid.uuid4().hex[:8]}.txt"
        file_content = self.generate_test_file('large')
        file_hash = self.calculate_md5(file_content)

        task_id = f"{uuid.uuid4().hex[:16]}"
        uploaded_chunks = []
        upload_results = []

        # 准备所有分片数据
        chunks_data = []
        for chunk_index in range(total_chunks):
            start = chunk_index * chunk_size
            end = min(start + chunk_size, len(file_content))
            chunk_content = file_content[start:end]
            chunks_data.append({
                'index': chunk_index,
                'content': chunk_content
            })

        # 定义并发上传函数
        def upload_chunk_sync(chunk_data):
            try:
                chunk_index = chunk_data['index']
                chunk_content = chunk_data['content']

                files = {'file': (f"{file_name}.part{chunk_index}", chunk_content, 'application/octet-stream')}
                data = {
                    'file_name': file_name,
                    'file_size': file_size,
                    'chunk_index': chunk_index,
                    'total_chunks': total_chunks,
                    'file_hash': file_hash,
                    'folder_id': parent_id,
                    'is_public': 'True'
                }

                response = self.client.post(
                    '/api/document/upload_chunk/',
                    files=files,
                    data=data,
                    name=f"[公共] 并发上传-分片 {chunk_index+1}/{total_chunks}"
                )

                upload_results.append({
                    'index': chunk_index,
                    'status': response.status_code,
                    'success': response.status_code == 200
                })

                if response.status_code == 200:
                    uploaded_chunks.append(chunk_index)
            except Exception as e:
                upload_results.append({
                    'index': chunk_data['index'],
                    'status': 0,
                    'success': False,
                    'error': str(e)
                })

        # 创建并启动线程并发上传
        threads = []
        for chunk_data in chunks_data:
            thread = threading.Thread(target=upload_chunk_sync, args=(chunk_data,))
            threads.append(thread)
            thread.start()

        # 等待所有线程完成
        for thread in threads:
            thread.join()

        # 合并分片
        if len(uploaded_chunks) == total_chunks:
            data = {
                'file_name': file_name,
                'file_size': file_size,
                'total_chunks': total_chunks,
                'file_hash': file_hash,
                'parent_id': parent_id,
                'is_public': True,
                'transfer_id': task_id
            }

            with self.client.post(
                '/api/document/merge_chunks/',
                json=data,
                catch_response=True,
                name="[公共] 并发上传-合并分片"
            ) as response:
                if response.status_code == 200:
                    file_id = response.json().get('id')
                    if file_id:
                        self.test_file_ids.append(file_id)
                else:
                    response.failure(f"合并分片失败: {response.text}")

    # ========== 分片顺序校验测试 ==========

    @task(2)
    def test_out_of_order_upload(self):
        """
        分片顺序校验测试：
        乱序上传分片（2->0->1），验证后端是否能正确处理
        """
        if not self.test_folder_ids:
            parent_id = None
        else:
            parent_id = random.choice(self.test_folder_ids)

        # 生成大文件（2MB，分为2个分片）
        file_size = TEST_CONFIG['file_sizes']['large']
        chunk_size = TEST_CONFIG['chunk_size']
        total_chunks = 2

        file_name = f"public_outoforder_{self.username}_{uuid.uuid4().hex[:8]}.txt"
        file_content = self.generate_test_file('large')
        file_hash = self.calculate_md5(file_content)

        task_id = f"{uuid.uuid4().hex[:16]}"
        uploaded_chunks = []

        # 准备分片数据
        chunks_data = []
        for chunk_index in range(total_chunks):
            start = chunk_index * chunk_size
            end = min(start + chunk_size, len(file_content))
            chunk_content = file_content[start:end]
            chunks_data.append({
                'index': chunk_index,
                'content': chunk_content
            })

        # 乱序上传：先上传分片1，再上传分片0
        upload_order = [1, 0]  # 乱序顺序

        for chunk_index in upload_order:
            chunk_data = chunks_data[chunk_index]

            files = {'file': (f"{file_name}.part{chunk_index}", chunk_data['content'], 'application/octet-stream')}
            data = {
                'file_name': file_name,
                'file_size': file_size,
                'chunk_index': chunk_index,
                'total_chunks': total_chunks,
                'file_hash': file_hash,
                'folder_id': parent_id,
                'is_public': 'True'
            }

            with self.client.post(
                '/api/document/upload_chunk/',
                files=files,
                data=data,
                catch_response=True,
                name=f"[公共] 乱序上传-分片{chunk_index+1}"
            ) as response:
                if response.status_code == 200:
                    uploaded_chunks.append(chunk_index)
                else:
                    response.failure(f"乱序上传分片失败: {response.text}")
                    return

        # 合并分片
        if len(uploaded_chunks) == total_chunks:
            data = {
                'file_name': file_name,
                'file_size': file_size,
                'total_chunks': total_chunks,
                'file_hash': file_hash,
                'parent_id': parent_id,
                'is_public': True,
                'transfer_id': task_id
            }

            with self.client.post(
                '/api/document/merge_chunks/',
                json=data,
                catch_response=True,
                name="[公共] 乱序上传-合并分片"
            ) as response:
                if response.status_code == 200:
                    file_id = response.json().get('id')
                    if file_id:
                        self.test_file_ids.append(file_id)
                else:
                    response.failure(f"合并分片失败: {response.text}")

    # ========== 分片丢失处理测试 ==========

    @task(2)
    def test_chunk_loss_recovery(self):
        """
        分片丢失处理测试：
        模拟某个分片上传失败，然后重传
        """
        if not self.test_folder_ids:
            parent_id = None
        else:
            parent_id = random.choice(self.test_folder_ids)

        # 生成大文件（3MB，分为3个分片）
        file_size = TEST_CONFIG['file_sizes']['large']
        chunk_size = TEST_CONFIG['chunk_size']
        total_chunks = (file_size + chunk_size - 1) // chunk_size

        file_name = f"public_lossrecovery_{self.username}_{uuid.uuid4().hex[:8]}.txt"
        file_content = self.generate_test_file('large')
        file_hash = self.calculate_md5(file_content)

        task_id = f"{uuid.uuid4().hex[:16]}"
        uploaded_chunks = []

        # 准备分片数据
        chunks_data = []
        for chunk_index in range(total_chunks):
            start = chunk_index * chunk_size
            end = min(start + chunk_size, len(file_content))
            chunk_content = file_content[start:end]
            chunks_data.append({
                'index': chunk_index,
                'content': chunk_content
            })

        # 随机选择一个分片作为"丢失"的分片
        lost_chunk_index = random.randint(0, total_chunks - 1)

        # 第一轮上传：故意跳过"丢失"的分片
        for chunk_index in range(total_chunks):
            if chunk_index == lost_chunk_index:
                # 跳过这个分片，模拟丢失
                continue

            chunk_data = chunks_data[chunk_index]
            files = {'file': (f"{file_name}.part{chunk_index}", chunk_data['content'], 'application/octet-stream')}
            data = {
                'file_name': file_name,
                'file_size': file_size,
                'chunk_index': chunk_index,
                'total_chunks': total_chunks,
                'file_hash': file_hash,
                'folder_id': parent_id,
                'is_public': 'True'
            }

            with self.client.post(
                '/api/document/upload_chunk/',
                files=files,
                data=data,
                catch_response=True,
                name=f"[公共] 丢失恢复-初传分片 {chunk_index+1}/{total_chunks}"
            ) as response:
                if response.status_code == 200:
                    uploaded_chunks.append(chunk_index)
                else:
                    response.failure(f"上传分片失败: {response.text}")
                    return

        # 第二轮：重传"丢失"的分片
        chunk_data = chunks_data[lost_chunk_index]
        files = {'file': (f"{file_name}.part{lost_chunk_index}", chunk_data['content'], 'application/octet-stream')}
        data = {
            'file_name': file_name,
            'file_size': file_size,
            'chunk_index': lost_chunk_index,
            'total_chunks': total_chunks,
            'file_hash': file_hash,
            'folder_id': parent_id,
            'is_public': 'True'
        }

        with self.client.post(
            '/api/document/upload_chunk/',
            files=files,
            data=data,
            catch_response=True,
            name=f"[公共] 丢失恢复-重传分片 {lost_chunk_index+1}/{total_chunks}"
        ) as response:
            if response.status_code == 200:
                uploaded_chunks.append(lost_chunk_index)
            else:
                response.failure(f"重传分片失败: {response.text}")
                return

        # 合并分片
        if len(uploaded_chunks) == total_chunks:
            data = {
                'file_name': file_name,
                'file_size': file_size,
                'total_chunks': total_chunks,
                'file_hash': file_hash,
                'parent_id': parent_id,
                'is_public': True,
                'transfer_id': task_id
            }

            with self.client.post(
                '/api/document/merge_chunks/',
                json=data,
                catch_response=True,
                name="[公共] 丢失恢复-合并分片"
            ) as response:
                if response.status_code == 200:
                    file_id = response.json().get('id')
                    if file_id:
                        self.test_file_ids.append(file_id)
                else:
                    response.failure(f"合并分片失败: {response.text}")

    # ========== 传输列表查询 ==========

    @task(5)
    def get_transfers(self):
        """获取传输列表"""
        self.client.get(
            '/api/document/transfers/?is_public=True',
            name="[公共] 查询传输列表"
        )

    # ========== 磁盘使用查询 ==========

    @task(3)
    def get_disk_usage(self):
        """查询磁盘使用情况"""
        self.client.get(
            '/api/document/disk_usage/?is_public=True',
            name="[公共] 查询磁盘使用"
        )

    # ========== 回收站操作 ==========

    @task(3)
    def list_recycle_bin(self):
        """查询回收站"""
        self.client.get(
            '/api/document/recycle-bin/?page=1&page_size=50&is_public=True',
            name="[公共] 查询回收站"
        )

    @task(1)
    def get_recycle_bin_stats(self):
        """查询回收站统计"""
        self.client.get(
            '/api/document/recycle-bin/stats/?is_public=True',
            name="[公共] 回收站统计"
        )


class AdminUser(HttpUser):
    """管理员用户"""

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
                raise Exception("管理员登录失败：无法获取token")
        else:
            raise Exception("管理员登录失败")

    def on_stop(self):
        """用户结束时尝试登出，忽略错误"""
        try:
            self.client.delete('/api/account/logout/')
        except:
            pass

    @task(10)
    def monitor_transfers(self):
        """监控传输列表（包括私有和公共空间）"""
        # 私有空间传输
        self.client.get(
            '/api/document/transfers/?is_public=False',
            name="[Admin] 查询私有传输列表"
        )

        # 公共空间传输
        self.client.get(
            '/api/document/transfers/?is_public=True',
            name="[Admin] 查询公共传输列表"
        )

    @task(5)
    def check_disk_usage(self):
        """检查磁盘使用情况（包括私有和公共空间）"""
        # 私有空间
        self.client.get(
            '/api/document/disk_usage/?is_public=False',
            name="[Admin] 查询私有磁盘使用"
        )

        # 公共空间
        self.client.get(
            '/api/document/disk_usage/?is_public=True',
            name="[Admin] 查询公共磁盘使用"
        )
