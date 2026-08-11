#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""上传冲突检测测试

覆盖：
1. 同名上传返回 conflict 响应
2. replace 动作删除已有文件后上传
3. keep 动作生成唯一 display_name
4. skip 动作返回 skipped
5. 无冲突直接上传成功
"""
import os, sys, json, uuid, random

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')
import django
django.setup()

from django.conf import settings
from apps.account.models import User
from apps.document.models import DocumentFolderPublic, DocumentFilePublic
from apps.document.libs.document_utils import get_document_absolute_path
from apps.document.views.file.upload import FileUploadView

R = []


def report(name, passed, detail=''):
    s = "PASS" if passed else "FAIL"
    R.append((name, s, detail))
    print(f"[{s}] {name}")
    if detail:
        for l in detail.split('\n'):
            print(f"       {l}")


def make_user(username, tenant_id):
    u, _ = User.objects.get_or_create(
        username=username,
        defaults={
            'nickname': username, 'password_hash': 'x',
            'access_token': uuid.uuid4().hex, 'tenant_id': tenant_id,
            'is_supper': True, 'last_ip': '127.0.0.1',
        },
    )
    return u


class FakeFile:
    """模拟上传的文件"""
    def __init__(self, name, content='test', size=None):
        self.name = name
        self._content = content
        self.size = size or len(content)
        self.content_type = 'application/octet-stream'

    def read(self):
        return self._content.encode('utf-8')

    def chunks(self):
        yield self._content.encode('utf-8')


class FakePostRequest:
    """模拟带 FILES 和 POST 的请求"""
    def __init__(self, user, file, folder_id, is_public=False, conflict_action=None, system_folder=None):
        self.user = user
        self.method = 'POST'
        self.FILES = {'file': file}
        self.POST = {
            'folder_id': str(folder_id) if folder_id else '',
            'is_public': 'true' if is_public else 'false',
        }
        if conflict_action:
            self.POST['conflict_action'] = conflict_action
        if system_folder:
            self.POST['system_folder'] = system_folder
        self.GET = {}
        self.content_type = 'multipart/form-data'
        self.body = b''
        self.data = {}


def make_folder(user, name, parent=None):
    return DocumentFolderPublic.objects.create(
        name=name, parent=parent,
        created_by=user, tenant_id=user.tenant_id,
    )


def make_existing_file(user, folder, display_name, content='existing', size=None):
    """创建已有文件记录 + 物理文件"""
    physical_name = f'{uuid.uuid4().hex}.bin'
    file_dir = get_document_absolute_path(
        is_public=False, user_id=user.id, folder_id=folder.id if folder else None)
    os.makedirs(file_dir, exist_ok=True)
    file_path = os.path.join(file_dir, physical_name)
    with open(file_path, 'w') as f:
        f.write(content)
    return DocumentFilePublic.objects.create(
        name=display_name, display_name=display_name,
        physical_name=physical_name, file_path=file_path,
        file_size=size or len(content),
        folder=folder, created_by=user, tenant_id=user.tenant_id,
    )


def cleanup_files(ids):
    for fid in ids:
        try:
            f = DocumentFilePublic.objects.filter(id=fid).first()
            if f:
                p = f.file_path
                t = f.thumbnail_path or ''
                f.delete()
                if p and os.path.exists(p):
                    os.remove(p)
                if t and os.path.exists(t):
                    os.remove(t)
        except Exception:
            pass


def cleanup_folders(ids):
    for fid in ids:
        try:
            DocumentFolderPublic.objects.filter(id=fid).delete()
        except Exception:
            pass


def test_1_upload_conflict_no_action():
    """T1: 同名上传无 conflict_action -> 返回 conflict"""
    print("\n--- T1: 上传冲突检测 ---")
    user = make_user('ut1', 'ut_t1')
    s = str(random.randint(10000, 99999))

    folder = make_folder(user, f'F_{s}')
    existing = make_existing_file(user, folder, f'doc_{s}.txt', 'old', 3)

    upload_file = FakeFile(f'doc_{s}.txt', 'new content', 11)
    view = FileUploadView()
    resp = view.post(FakePostRequest(user, upload_file, folder.id))
    data = json.loads(resp.content)
    status = data.get('data', {}).get('status')

    report('T1: 返回 conflict', status == 'conflict', f'response={data}')
    conflicts = data.get('data', {}).get('conflicts', [])
    report('T1: 有冲突信息', len(conflicts) > 0)

    # 数据库没有新增
    count = DocumentFilePublic.objects.filter(folder=folder, display_name=f'doc_{s}.txt').count()
    report('T1: 文件数不变(1)', count == 1, f'count={count}')

    cleanup_files([existing.id])
    cleanup_folders([folder.id])


def test_2_upload_replace():
    """T2: replace 动作 -> 删除已有文件后上传"""
    print("\n--- T2: 上传 replace ---")
    user = make_user('ut2', 'ut_t2')
    s = str(random.randint(10000, 99999))

    folder = make_folder(user, f'F_{s}')
    existing = make_existing_file(user, folder, f'rep_{s}.txt', 'old', 3)

    upload_file = FakeFile(f'rep_{s}.txt', 'new content', 11)
    view = FileUploadView()
    resp = view.post(FakePostRequest(user, upload_file, folder.id, conflict_action='replace'))
    data = json.loads(resp.content)

    report('T2: 返回 success', data.get('data', {}).get('status') == 'success',
           f'response={data}')
    report('T2: action=replace', data.get('data', {}).get('action') == 'replace')

    # 旧文件被删除
    report('T2: 旧文件已删除', not DocumentFilePublic.objects.filter(id=existing.id).exists())

    # 新文件已创建
    new_files = DocumentFilePublic.objects.filter(folder=folder, display_name=f'rep_{s}.txt')
    report('T2: 新文件已创建', new_files.count() == 1)

    cleanup_files([f.id for f in new_files])
    cleanup_folders([folder.id])


def test_3_upload_keep():
    """T3: keep 动作 -> 生成唯一 display_name"""
    print("\n--- T3: 上传 keep ---")
    user = make_user('ut3', 'ut_t3')
    s = str(random.randint(10000, 99999))

    folder = make_folder(user, f'F_{s}')
    existing = make_existing_file(user, folder, f'keep_{s}.txt', 'old', 3)

    upload_file = FakeFile(f'keep_{s}.txt', 'new content', 11)
    view = FileUploadView()
    resp = view.post(FakePostRequest(user, upload_file, folder.id, conflict_action='keep'))
    data = json.loads(resp.content)

    report('T3: 返回 success', data.get('data', {}).get('status') == 'success',
           f'response={data}')

    # 检查有 _1 后缀的文件
    new_files = DocumentFilePublic.objects.filter(
        folder=folder, display_name__startswith=f'keep_{s}')
    report('T3: 有 2 个文件（原+_1）', new_files.count() == 2,
           f'count={new_files.count()}')

    has_suffix = any('_1.txt' in f.display_name for f in new_files)
    report('T3: 新文件 display_name 带 _1', has_suffix)

    cleanup_files([existing.id] + [f.id for f in new_files if f.id != existing.id])
    cleanup_folders([folder.id])


def test_4_upload_skip():
    """T4: skip 动作 -> 不上传"""
    print("\n--- T4: 上传 skip ---")
    user = make_user('ut4', 'ut_t4')
    s = str(random.randint(10000, 99999))

    folder = make_folder(user, f'F_{s}')
    existing = make_existing_file(user, folder, f'skip_{s}.txt', 'old', 3)

    upload_file = FakeFile(f'skip_{s}.txt', 'new content', 11)
    view = FileUploadView()
    resp = view.post(FakePostRequest(user, upload_file, folder.id, conflict_action='skip'))
    data = json.loads(resp.content)

    report('T4: 返回 skipped', data.get('data', {}).get('status') == 'skipped',
           f'response={data}')

    # 文件数不变
    count = DocumentFilePublic.objects.filter(folder=folder, display_name=f'skip_{s}.txt').count()
    report('T4: 文件数不变(1)', count == 1)

    cleanup_files([existing.id])
    cleanup_folders([folder.id])


def test_5_upload_no_conflict():
    """T5: 无冲突直接上传"""
    print("\n--- T5: 无冲突上传 ---")
    user = make_user('ut5', 'ut_t5')
    s = str(random.randint(10000, 99999))

    folder = make_folder(user, f'F_{s}')

    upload_file = FakeFile(f'new_{s}.txt', 'fresh content', 13)
    view = FileUploadView()
    resp = view.post(FakePostRequest(user, upload_file, folder.id))
    data = json.loads(resp.content)

    report('T5: 返回 success', data.get('data', {}).get('status') == 'success',
           f'response={data}')

    new_files = DocumentFilePublic.objects.filter(folder=folder, display_name=f'new_{s}.txt')
    report('T5: 文件已创建', new_files.count() == 1)

    cleanup_files([f.id for f in new_files])
    cleanup_folders([folder.id])


def main():
    print("=" * 60)
    print("上传冲突检测测试")
    print("=" * 60)

    for t in [test_1_upload_conflict_no_action, test_2_upload_replace,
              test_3_upload_keep, test_4_upload_skip, test_5_upload_no_conflict]:
        try:
            t()
        except Exception as e:
            report(t.__name__, False, str(e))
            import traceback
            traceback.print_exc()

    print("\n" + "=" * 60)
    passed = sum(1 for _, s, _ in R if s == "PASS")
    failed = sum(1 for _, s, _ in R if s == "FAIL")
    print(f"总计: {passed} PASS / {failed} FAIL / {len(R)} 总")
    if failed:
        print("\n失败项:")
        for name, s, detail in R:
            if s == "FAIL":
                print(f"  - {name}: {detail}")
    print("=" * 60)
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
