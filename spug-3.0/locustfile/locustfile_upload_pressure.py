"""
资料库批量上传多终端并发压测脚本

基于 spug-3.0 仓库实际上传实现编写，模拟前端完整上传流程：
1. 计算文件MD5
2. 创建传输记录
3. 检查已上传分片（断点续传）
4. 分片上传
5. 触发合并
6. 轮询合并状态

使用方法：
  locust -f locustfile_upload_pressure.py --host=http://localhost:3000/ \
    -u 3 -r 1 -t 5m --headless --csv=upload_pressure_3terminals

参数说明：
  -u N : N 个终端（每个终端内部 3 并发上传）
  -r 1 : 每秒增加 1 个用户
  -t 5m : 持续 5 分钟
"""

import os
import time
import hashlib
import json
import threading
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

from locust import HttpUser, task, between, events, tag
from locust.runners import MasterRunner, WorkerRunner

# ============================================================
# 配置常量（与前端 constants/upload.js 保持一致）
# ============================================================
CHUNK_SIZE = 32 * 1024 * 1024       # 32MB 分片大小
MAX_CONCURRENT_UPLOADS = 3          # 每终端最大并发上传数
MERGE_POLLING_INTERVAL = 2          # 合并轮询间隔（秒）
MERGE_MAX_POLLING_TIME = 300        # 合并最大轮询时间（秒）
MAX_RETRIES = 3                     # 最大重试次数

# 文件类型配置
FILE_CATEGORIES = {
    'small':  {'min_mb': 1,   'max_mb': 30,  'count': 10, 'description': '小文件(1-30MB, 不触发分片)'},
    'medium': {'min_mb': 50,  'max_mb': 300, 'count': 5,  'description': '中文件(50-300MB, 2-10分片)'},
    'large':  {'min_mb': 500, 'max_mb': 1000, 'count': 2,  'description': '大文件(500MB-1GB, 16-32分片)'},
}

# 统计收集器
_stats_lock = threading.Lock()
global_stats = {
    'total_files': 0,
    'completed_files': 0,
    'failed_files': 0,
    'upload_times': [],
    'merge_times': [],
    'chunk_upload_times': [],
    'merge_queue_waits': [],
    'errors': [],
}

logger = logging.getLogger('upload_pressure')


def record_stat(key, value):
    """线程安全地记录统计数据"""
    with _stats_lock:
        if key in global_stats:
            if isinstance(global_stats[key], list):
                global_stats[key].append(value)
            elif isinstance(global_stats[key], int):
                global_stats[key] += value


def record_error(error_msg):
    """线程安全地记录错误"""
    with _stats_lock:
        global_stats['errors'].append({
            'time': datetime.now().isoformat(),
            'error': error_msg
        })
        global_stats['failed_files'] += 1


# ============================================================
# 测试文件生成器
# ============================================================

def generate_test_files(base_dir='/tmp/upload_pressure_files', category='mixed'):
    """生成测试文件

    Args:
        base_dir: 测试文件存储目录
        category: 文件类型 small/medium/large/mixed
    """
    os.makedirs(base_dir, exist_ok=True)

    categories = FILE_CATEGORIES if category == 'mixed' else {category: FILE_CATEGORIES[category]}

    for cat_name, config in categories.items():
        cat_dir = os.path.join(base_dir, cat_name)
        os.makedirs(cat_dir, exist_ok=True)

        for i in range(config['count']):
            fpath = os.path.join(cat_dir, f'test_{cat_name}_{i:03d}.dat')
            if os.path.exists(fpath):
                # 跳过已存在的文件
                expected_size = (config['min_mb'] + config['max_mb']) // 2 * 1024 * 1024
                if abs(os.path.getsize(fpath) - expected_size) < 1024:
                    continue

            size_mb = (config['min_mb'] + config['max_mb']) // 2
            size_bytes = size_mb * 1024 * 1024
            logger.info(f'Generating {fpath} ({size_mb}MB)...')

            with open(fpath, 'wb') as f:
                # 写入可识别的测试数据模式
                remaining = size_bytes
                chunk = b'A' * (1024 * 1024)  # 1MB chunk
                while remaining > 0:
                    write_size = min(len(chunk), remaining)
                    f.write(chunk[:write_size])
                    remaining -= write_size

    logger.info(f'Test files generated in {base_dir}')


def get_all_test_files(base_dir='/tmp/upload_pressure_files', category='mixed'):
    """获取所有测试文件路径"""
    files = []
    if category == 'mixed':
        for cat in FILE_CATEGORIES:
            cat_dir = os.path.join(base_dir, cat)
            if os.path.exists(cat_dir):
                for fn in sorted(os.listdir(cat_dir)):
                    fpath = os.path.join(cat_dir, fn)
                    if os.path.isfile(fpath):
                        files.append(fpath)
    else:
        cat_dir = os.path.join(base_dir, category)
        if os.path.exists(cat_dir):
            for fn in sorted(os.listdir(cat_dir)):
                fpath = os.path.join(cat_dir, fn)
                if os.path.isfile(fpath):
                    files.append(fpath)
    return files


def calculate_md5(file_path):
    """计算文件 MD5（与前端一致的分片计算方式）"""
    h = hashlib.md5()
    with open(file_path, 'rb') as f:
        while True:
            chunk = f.read(8 * 1024 * 1024)  # 8MB 分片
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


# ============================================================
# 上传用户类（模拟一个终端）
# ============================================================

class UploadTerminalUser(HttpUser):
    """模拟一个终端的上传行为

    每个终端内部维护 MAX_CONCURRENT_UPLOADS=3 个并发上传槽位，
    与前端 UploadCoordinator 的行为一致。
    """

    wait_time = between(0.5, 2)  # 上传批次之间的等待时间
    host = 'http://localhost'     # 默认值，命令行覆盖

    def on_start(self):
        """初始化终端状态"""
        self.upload_pool = ThreadPoolExecutor(max_workers=MAX_CONCURRENT_UPLOADS)
        self.file_queue = get_all_test_files(category='mixed')
        self.queue_index = 0
        self.token = None
        self.user_id = None

        # 登录获取 token
        self._login()

        # 环境信息
        self.is_public = False
        self.folder_id = None

        # 终端统计
        self.terminal_stats = {
            'uploaded': 0,
            'failed': 0,
            'merge_time': [],
            'upload_time': [],
        }

        logger.info(f'[Terminal] Started, {len(self.file_queue)} files in queue')

    def _login(self):
        """登录获取认证 token"""
        # 尝试多种登录方式
        try:
            resp = self.client.post('/api/account/login/', json={
                'username': os.environ.get('TEST_USERNAME', 'admin'),
                'password': os.environ.get('TEST_PASSWORD', 'spug'),
            }, name='[AUTH] login')
            if resp.status_code == 200:
                data = resp.json()
                self.token = data.get('data', {}).get('access_token') or data.get('data', {}).get('token')
                if self.token:
                    self.client.headers.update({'Authorization': f'Bearer {self.token}'})
                    logger.info('[Terminal] Login successful')
                    return
        except Exception:
            pass

        # 尝试直接设置 token（如果已知）
        test_token = os.environ.get('TEST_TOKEN')
        if test_token:
            self.token = test_token
            self.client.headers.update({'Authorization': f'Bearer {test_token}'})
            logger.info('[Terminal] Using provided token')
            return

        logger.warning('[Terminal] No auth token available, requests may fail')

    @task(5)
    @tag('upload')
    def upload_files(self):
        """批量上传文件（核心任务）"""
        if not self.file_queue:
            logger.warning('[Terminal] No test files available')
            return

        # 取一批文件上传（最多 MAX_CONCURRENT_UPLOADS 个并发）
        batch = self._get_next_batch()
        if not batch:
            # 所有文件已上传完一轮，重新开始
            self.queue_index = 0
            batch = self._get_next_batch()
            if not batch:
                return

        # 并发上传
        futures = []
        for file_path in batch:
            future = self.upload_pool.submit(self._upload_single_file, file_path)
            futures.append((file_path, future))

        # 等待所有上传完成
        for file_path, future in futures:
            try:
                result = future.result(timeout=600)
                if result:
                    self.terminal_stats['uploaded'] += 1
                    record_stat('completed_files', 1)
                else:
                    self.terminal_stats['failed'] += 1
                    record_stat('failed_files', 1)
            except Exception as e:
                logger.error(f'[Terminal] Upload failed for {os.path.basename(file_path)}: {e}')
                self.terminal_stats['failed'] += 1
                record_error(str(e))

    @task(1)
    @tag('check')
    def check_health(self):
        """健康检查（验证服务器响应正常）"""
        self.client.get('/api/document/health/', name='[HEALTH] check')

    def _get_next_batch(self):
        """获取下一批上传文件"""
        batch_size = MAX_CONCURRENT_UPLOADS
        end = min(self.queue_index + batch_size, len(self.file_queue))
        if self.queue_index >= len(self.file_queue):
            return []
        batch = self.file_queue[self.queue_index:end]
        self.queue_index = end
        return batch

    def _upload_single_file(self, file_path):
        """单个文件的完整上传流程

        完整模拟前端 chunkUpload.js 的流程：
        1. 计算 MD5
        2. 创建传输记录
        3. 确保传输状态为 UPLOADING
        4. 检查已上传分片
        5. 顺序上传缺失分片
        6. 触发合并
        7. 轮询合并状态
        """
        start_time = time.time()
        file_name = os.path.basename(file_path)
        file_size = os.path.getsize(file_path)

        try:
            # Step 1: 计算 MD5
            md5 = calculate_md5(file_path)

            # Step 2: 创建传输记录
            transfer_id = self._create_transfer(file_name, file_size, md5)
            if not transfer_id:
                return False

            # Step 3: 小文件 / 分片上传
            if file_size <= CHUNK_SIZE:
                # 小文件直接上传（不触发分片）
                success = self._upload_small_file(file_path, md5, transfer_id)
            else:
                # 大文件分片上传
                total_chunks = (file_size + CHUNK_SIZE - 1) // CHUNK_SIZE
                success = self._upload_chunked_file(
                    file_path, md5, file_size, total_chunks, transfer_id
                )

            if not success:
                return False

            # Step 4: 触发合并
            total_chunks = max(1, (file_size + CHUNK_SIZE - 1) // CHUNK_SIZE)
            merge_result = self._trigger_merge(
                file_name, file_size, md5, total_chunks, transfer_id
            )

            if not merge_result:
                return False

            # 如果已经完成（幂等命中），直接返回
            if merge_result.get('status') == 'completed':
                upload_time = time.time() - start_time
                self.terminal_stats['upload_time'].append(upload_time)
                record_stat('upload_times', upload_time)
                return True

            # Step 5: 轮询合并状态
            task_id = merge_result.get('task_id')
            merge_start = time.time()
            merge_success = self._poll_merge_status(task_id, merge_start)

            if merge_success:
                merge_time = time.time() - merge_start
                self.terminal_stats['merge_time'].append(merge_time)
                record_stat('merge_times', merge_time)

            upload_time = time.time() - start_time
            self.terminal_stats['upload_time'].append(upload_time)
            record_stat('upload_times', upload_time)

            return merge_success

        except Exception as e:
            record_error(f'{file_name}: {str(e)}')
            return False

    def _create_transfer(self, file_name, file_size, file_hash):
        """创建传输记录"""
        try:
            resp = self.client.post('/api/document/transfers/create/', json={
                'file_name': file_name,
                'file_size': file_size,
                'file_hash': file_hash,
                'total_chunks': max(1, (file_size + CHUNK_SIZE - 1) // CHUNK_SIZE),
                'is_public': self.is_public,
                'folder_id': self.folder_id,
            }, name='[UPLOAD] create_transfer')

            if resp.status_code == 200:
                data = resp.json()
                transfer_id = data.get('data', {}).get('id')
                if transfer_id:
                    return transfer_id
                # 可能返回已有记录
                return data.get('data', {}).get('transfer_id')
            else:
                record_error(f'create_transfer HTTP {resp.status_code}')
                return None
        except Exception as e:
            record_error(f'create_transfer exception: {e}')
            return None

    def _upload_small_file(self, file_path, md5, transfer_id):
        """小文件上传（<32MB，不触发分片）"""
        try:
            with open(file_path, 'rb') as f:
                resp = self.client.post('/api/document/upload/', files={
                    'file': (os.path.basename(file_path), f)
                }, data={
                    'file_hash': md5,
                    'transfer_id': str(transfer_id) if transfer_id else '',
                    'is_public': 'false',
                    'folder_id': '',
                }, name='[UPLOAD] small_file')
                return resp.status_code == 200
        except Exception as e:
            record_error(f'small_file upload: {e}')
            return False

    def _upload_chunked_file(self, file_path, md5, file_size, total_chunks, transfer_id):
        """分片上传（>=32MB）"""
        # 先检查已上传分片（断点续传）
        uploaded_chunks = self._check_uploaded_chunks(md5, file_size, total_chunks)

        # 顺序上传缺失分片（与前端 chunkUpload.js 一致）
        with open(file_path, 'rb') as f:
            for i in range(total_chunks):
                if i in uploaded_chunks:
                    # 跳过已上传分片
                    f.seek(i * CHUNK_SIZE)
                    continue

                # 读取分片数据
                f.seek(i * CHUNK_SIZE)
                chunk_data = f.read(CHUNK_SIZE)
                actual_chunk_size = len(chunk_data)

                # 上传分片（带重试）
                success = self._upload_single_chunk(
                    chunk_data, i, total_chunks, actual_chunk_size,
                    md5, file_size, os.path.basename(file_path), transfer_id
                )

                if not success:
                    return False

                # 记录分片上传时间
                record_stat('chunk_upload_times', time.time())

        return True

    def _check_uploaded_chunks(self, file_hash, file_size, total_chunks):
        """检查已上传分片（断点续传）"""
        try:
            resp = self.client.post('/api/document/check_uploaded_chunks/', json={
                'file_hash': file_hash,
                'file_size': file_size,
                'total_chunks': total_chunks,
                'is_public': self.is_public,
            }, name='[UPLOAD] check_uploaded_chunks')

            if resp.status_code == 200:
                data = resp.json().get('data', {})
                return set(data.get('uploaded_chunks', []))
        except Exception:
            pass
        return set()

    def _upload_single_chunk(self, chunk_data, chunk_index, total_chunks,
                              chunk_size, file_hash, file_size, file_name, transfer_id):
        """上传单个分片（带重试）"""
        for attempt in range(MAX_RETRIES + 1):
            try:
                resp = self.client.post('/api/document/upload_chunk/',
                    files={'file': (f'{chunk_index}.part', chunk_data)},
                    data={
                        'file_hash': file_hash,
                        'chunk_index': str(chunk_index),
                        'total_chunks': str(total_chunks),
                        'chunk_size': str(chunk_size),
                        'file_name': file_name,
                        'file_size': str(file_size),
                        'folder_id': str(self.folder_id) if self.folder_id else '',
                        'is_public': 'true' if self.is_public else 'false',
                        'transfer_id': str(transfer_id) if transfer_id else '',
                    },
                    name='[UPLOAD] upload_chunk')

                if resp.status_code == 200:
                    return True
                elif resp.status_code in (408, 429, 500, 502, 503, 504):
                    # 可重试错误
                    if attempt < MAX_RETRIES:
                        wait = min(2 ** attempt, 30)
                        time.sleep(wait)
                        continue
                    record_error(f'chunk {chunk_index} HTTP {resp.status_code} after {attempt + 1} attempts')
                    return False
                else:
                    # 不可重试错误
                    record_error(f'chunk {chunk_index} HTTP {resp.status_code} (non-retryable)')
                    return False
            except Exception as e:
                if attempt < MAX_RETRIES:
                    wait = min(2 ** attempt, 30)
                    time.sleep(wait)
                    continue
                record_error(f'chunk {chunk_index} exception: {e}')
                return False
        return False

    def _trigger_merge(self, file_name, file_size, file_hash, total_chunks, transfer_id):
        """触发合并"""
        try:
            resp = self.client.post('/api/document/merge_chunks/', json={
                'file_name': file_name,
                'file_size': file_size,
                'file_hash': file_hash,
                'total_chunks': total_chunks,
                'folder_id': self.folder_id,
                'is_public': self.is_public,
                'transfer_id': transfer_id,
            }, name='[UPLOAD] merge_chunks')

            if resp.status_code == 200:
                data = resp.json()
                result = data.get('data', data.get('result', {}))
                return result
            else:
                record_error(f'merge_chunks HTTP {resp.status_code}')
                return None
        except Exception as e:
            record_error(f'merge_chunks exception: {e}')
            return None

    def _poll_merge_status(self, task_id, merge_start):
        """轮询合并状态（与前端渐进式退避一致）"""
        if not task_id:
            return False

        elapsed = 0
        # 渐进式退避：0-30s 每 2s，30s-5min 每 5s，>5min 每 15s
        while elapsed < MERGE_MAX_POLLING_TIME:
            if elapsed < 30:
                interval = 2
            elif elapsed < 300:
                interval = 5
            else:
                interval = 15

            time.sleep(interval)
            elapsed += interval

            try:
                resp = self.client.get('/api/document/merge_status/', params={
                    'task_id': task_id,
                }, name='[UPLOAD] merge_status')

                if resp.status_code == 200:
                    data = resp.json().get('data', {})
                    status = data.get('status', '').lower()

                    if status == 'success':
                        return True
                    elif status in ('failed', 'failure'):
                        error_msg = data.get('message', data.get('error', 'Unknown'))
                        record_error(f'merge failed: {error_msg}')
                        return False
                    # 继续轮询：pending, progress, merging...
                elif resp.status_code >= 500:
                    # 服务器错误，重试
                    continue
                else:
                    record_error(f'merge_status HTTP {resp.status_code}')
                    return False

            except Exception as e:
                # 网络错误，重试
                continue

        record_error(f'merge timeout after {elapsed}s')
        return False

    def on_stop(self):
        """终端停止时的清理"""
        self.upload_pool.shutdown(wait=False)
        logger.info(
            f'[Terminal] Stopped. uploaded={self.terminal_stats["uploaded"]}, '
            f'failed={self.terminal_stats["failed"]}'
        )


# ============================================================
# Locust 事件钩子
# ============================================================

@events.test_stop.add_listener
def on_test_stop(environment, **kwargs):
    """测试结束时输出汇总统计"""
    if isinstance(environment.runner, WorkerRunner):
        return  # Worker 不输出

    print('\n' + '=' * 80)
    print('上传压测结果汇总')
    print('=' * 80)

    with _stats_lock:
        total = global_stats['completed_files'] + global_stats['failed_files']
        if total > 0:
            success_rate = global_stats['completed_files'] / total * 100
        else:
            success_rate = 0

        print(f'\n文件统计:')
        print(f'  总文件数:    {global_stats["total_files"]}')
        print(f'  成功上传:    {global_stats["completed_files"]}')
        print(f'  失败上传:    {global_stats["failed_files"]}')
        print(f'  成功率:      {success_rate:.1f}%')

        if global_stats['upload_times']:
            times = sorted(global_stats['upload_times'])
            print(f'\n上传时间 (秒):')
            print(f'  平均: {sum(times)/len(times):.2f}')
            print(f'  p50:  {times[len(times)//2]:.2f}')
            print(f'  p95:  {times[int(len(times)*0.95)]:.2f}')
            print(f'  p99:  {times[int(len(times)*0.99)]:.2f}')
            print(f'  max:  {times[-1]:.2f}')

        if global_stats['merge_times']:
            merge_times = sorted(global_stats['merge_times'])
            print(f'\n合并时间 (秒):')
            print(f'  平均: {sum(merge_times)/len(merge_times):.2f}')
            print(f'  p50:  {merge_times[len(merge_times)//2]:.2f}')
            print(f'  p95:  {merge_times[int(len(merge_times)*0.95)]:.2f}')
            print(f'  p99:  {merge_times[int(len(merge_times)*0.99)]:.2f}')
            print(f'  max:  {merge_times[-1]:.2f}')

        if global_stats['errors']:
            print(f'\n错误统计 (最近 20 条):')
            error_types = {}
            for err in global_stats['errors'][-20:]:
                # 简化错误类型
                err_type = err['error'][:80]
                error_types[err_type] = error_types.get(err_type, 0) + 1
            for err_type, count in sorted(error_types.items(), key=lambda x: -x[1]):
                print(f'  [{count}x] {err_type}')

    print('\n' + '=' * 80)


# ============================================================
# 自定义 Locust 参数
# ============================================================

@events.init_command_line_parser.add_listener
def add_custom_args(parser):
    """添加自定义命令行参数"""
    parser.add_argument(
        '--file-category',
        type=str,
        default='mixed',
        choices=['small', 'medium', 'large', 'mixed'],
        help='测试文件类型: small/medium/large/mixed'
    )
    parser.add_argument(
        '--files-dir',
        type=str,
        default='/tmp/upload_pressure_files',
        help='测试文件目录'
    )
    parser.add_argument(
        '--generate-files',
        action='store_true',
        default=False,
        help='自动生成测试文件'
    )


@events.test_start.add_listener
def on_test_start(environment, **kwargs):
    """测试开始时的准备"""
    if isinstance(environment.runner, WorkerRunner):
        return

    # 如果指定了自动生成文件
    if environment.parsed_options.generate_files:
        category = environment.parsed_options.file_category
        files_dir = environment.parsed_options.files_dir
        logger.info(f'Generating test files: category={category}, dir={files_dir}')
        generate_test_files(base_dir=files_dir, category=category)

    # 更新全局文件列表
    category = environment.parsed_options.file_category
    files_dir = environment.parsed_options.files_dir
    files = get_all_test_files(base_dir=files_dir, category=category)
    logger.info(f'Found {len(files)} test files')

    if not files:
        logger.warning('No test files found! Use --generate-files to create them.')
