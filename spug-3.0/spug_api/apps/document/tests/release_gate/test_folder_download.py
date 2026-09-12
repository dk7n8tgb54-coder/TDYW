"""文件夹打包下载探测（probe）行为测试（stable_contract）。

覆盖：probe 模式按"总大小优先、文件数兜底"双条件返回打包方式、
异步任务在探测请求内提交、Celery 不可用时降级同步、
probe 不绕过党建作用域校验、小文件夹非 probe 同步下载保持 ZIP 流式响应、
ready 接口必须返回 ZIP 而非 JSON 错误体。
"""
import io
import zipfile
from unittest import mock

from django.test import TestCase

from apps.document.models import DocumentFilePublic
from tests.helpers.test_base import (
    get_response_data, has_error, make_client, make_user, setup_test_env)

from .helpers import (
    PB, PB_VIEW, PERM_DOWNLOAD, PERM_VIEW, StorageCleanupMixin,
    bind_party_building, make_file, make_folder, unique)

VIEW_NAME = 'apps.document.views.folder.download.FolderDownloadView'


def make_file_records(folder, created_by, count, file_size=1):
    """批量创建文件记录（仅数据库记录，probe 判定不依赖物理文件）。"""
    DocumentFilePublic.objects.bulk_create([
        DocumentFilePublic(
            name=f'{unique("bulk")}_{i}.txt',
            display_name=f'批量文件_{i}.txt',
            physical_name=f'{unique("phys")}_{i}.txt',
            file_path=f'/nonexistent/{unique("path")}_{i}.txt',
            file_size=file_size,
            file_type='text/plain',
            folder=folder,
            created_by=created_by,
        ) for i in range(count)
    ])


class FolderDownloadProbeTest(StorageCleanupMixin, TestCase):
    """文件夹下载 probe 探测与打包方式分派"""

    @classmethod
    def setUpTestData(cls):
        cls.user = make_user('gate_probe', perms=[PERM_VIEW, PERM_DOWNLOAD, PB_VIEW])

    def setUp(self):
        super().setUp()
        setup_test_env()
        self.client = make_client(self.user)
        self.folder = make_folder(name=unique('打包目录'), created_by=self.user)

    def _probe(self, folder, **extra):
        params = {'id': folder.id, 'is_public': 'true', 'probe': 'true'}
        params.update(extra)
        return self.client.get('/document/folder/download/', params)

    def test_01_probe_small_folder_returns_sync(self):
        """少于阈值的文件夹探测返回 sync，且不提交异步任务"""
        make_file(folder=self.folder, created_by=self.user)
        with mock.patch(f'{VIEW_NAME}._celery_available', return_value=True), \
                mock.patch('apps.document.tasks.pack_folder_to_zip.delay') as mock_delay:
            resp = self._probe(self.folder)
        self.assertFalse(has_error(resp), resp.json())
        data = get_response_data(resp)
        self.assertEqual(data['mode'], 'sync', data)
        self.assertNotIn('task_id', data)
        mock_delay.assert_not_called()

    def test_02_probe_many_files_submits_async_task(self):
        """文件数达到阈值（500）的文件夹探测提交打包任务并返回 task_id"""
        make_file_records(self.folder, self.user, 500)
        fake_task = mock.MagicMock()
        fake_task.id = 'probe-test-task-id'
        with mock.patch(f'{VIEW_NAME}._celery_available', return_value=True), \
                mock.patch('apps.document.tasks.pack_folder_to_zip.delay',
                           return_value=fake_task) as mock_delay:
            resp = self._probe(self.folder)
        self.assertFalse(has_error(resp), resp.json())
        data = get_response_data(resp)
        self.assertEqual(data['mode'], 'async', data)
        self.assertEqual(data['task_id'], 'probe-test-task-id', data)
        mock_delay.assert_called_once()
        self.assertEqual(mock_delay.call_args.kwargs['folder_id'], self.folder.id)
        self.assertTrue(mock_delay.call_args.kwargs['is_public'])

    def test_03_probe_large_total_size_submits_async_task(self):
        """总大小达到阈值（200MB）即走异步——文件数很少的超大文件文件夹"""
        make_file_records(self.folder, self.user, 2,
                          file_size=150 * 1024 * 1024)
        fake_task = mock.MagicMock()
        fake_task.id = 'probe-size-task-id'
        with mock.patch(f'{VIEW_NAME}._celery_available', return_value=True), \
                mock.patch('apps.document.tasks.pack_folder_to_zip.delay',
                           return_value=fake_task) as mock_delay:
            resp = self._probe(self.folder)
        self.assertFalse(has_error(resp), resp.json())
        data = get_response_data(resp)
        self.assertEqual(data['mode'], 'async', data)
        self.assertEqual(data['task_id'], 'probe-size-task-id', data)
        mock_delay.assert_called_once()

    def test_04_probe_without_celery_falls_back_to_sync(self):
        """Celery 队列无消费者时大文件夹探测降级为 sync，不提交任务"""
        make_file_records(self.folder, self.user, 500)
        with mock.patch(f'{VIEW_NAME}._celery_available', return_value=False), \
                mock.patch('apps.document.tasks.pack_folder_to_zip.delay') as mock_delay:
            resp = self._probe(self.folder)
        self.assertFalse(has_error(resp), resp.json())
        data = get_response_data(resp)
        self.assertEqual(data['mode'], 'sync', data)
        mock_delay.assert_not_called()

    def test_05_probe_does_not_bypass_party_building_scope(self):
        """probe 模式同样执行党建作用域校验"""
        pb_root = make_folder(name=unique('党建根'), created_by=self.user)
        bind_party_building(pb_root)
        resp = self._probe(pb_root)
        self.assertTrue(has_error(resp), '党建目录不带 system_folder 的 probe 必须被拒绝')
        self.assertIn('党建', resp.json().get('error', ''), resp.json())

    def test_06_small_folder_sync_download_still_streams_zip(self):
        """非 probe 的小文件夹下载保持 ZIP 流式响应"""
        obj = make_file(folder=self.folder, created_by=self.user,
                        name=unique('打包内容') + '.txt', content=b'probe-zip-check')
        self.track_path(obj.file_path)
        resp = self.client.get('/document/folder/download/',
                               {'id': self.folder.id, 'is_public': 'true'})
        self.assertEqual(resp.status_code, 200)
        self.assertIn('application/zip', resp['Content-Type'], resp.get('Content-Type'))
        body = b''.join(resp.streaming_content) if resp.streaming else resp.content
        with zipfile.ZipFile(io.BytesIO(body)) as zf:
            self.assertEqual(zf.namelist(), [f'{self.folder.name}/{obj.name}'])
            self.assertEqual(zf.read(zf.namelist()[0]), b'probe-zip-check')

    def test_07_ready_endpoint_serves_zip_not_json(self):
        """ready 接口必须返回 ZIP 流而非 JSON 错误体

        回归 2026-09-11 缺陷：ready 视图从 tasks/__init__ 导入 PACK_TASKS_DIR
        抛 ImportError，兜底逻辑把错误 JSON 当下载内容返回，前端存成 .json 文件。
        """
        import io
        import os as _os
        import zipfile
        from apps.document.tasks.pack import PACK_TASKS_DIR
        from apps.document.libs.pack_task_ownership import record_ownership

        _os.makedirs(PACK_TASKS_DIR, exist_ok=True)
        zip_path = _os.path.join(PACK_TASKS_DIR, f'test_{unique("ready")}.zip')
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(f'{self.folder.name}/hello.txt', b'probe-ready-check')
        self.track_path(zip_path)
        record_ownership('ready-regression-task', self.user.id,
                         getattr(self.user, 'tenant_id', None), True)

        fake_task = mock.MagicMock()
        fake_task.ready.return_value = True
        fake_task.successful.return_value = True
        fake_task.result = {
            'status': 'success', 'zip_path': zip_path,
            'zip_size': _os.path.getsize(zip_path),
            'folder_name': self.folder.name, 'user_id': self.user.id,
            'tenant_id': getattr(self.user, 'tenant_id', None),
            'is_public': True, 'folder_id': self.folder.id,
        }
        with mock.patch('celery.result.AsyncResult', return_value=fake_task):
            resp = self.client.get('/document/folder/download/ready/',
                                   {'task_id': 'ready-regression-task'})

        self.assertEqual(resp.status_code, 200)
        self.assertNotIn('application/json', resp['Content-Type'],
                         'ready 接口不应返回 JSON')
        self.assertIn('application/zip', resp['Content-Type'], resp.get('Content-Type'))
        body = b''.join(resp.streaming_content) if resp.streaming else resp.content
        with zipfile.ZipFile(io.BytesIO(body)) as zf:
            self.assertEqual(zf.read(zf.namelist()[0]), b'probe-ready-check')
