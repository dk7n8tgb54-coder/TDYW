# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
from django.test import TestCase
from apps.document.models import DocumentFolderPrivate as DocumentFolder, DocumentFilePrivate as DocumentFile
from apps.account.models import User


class DocumentFolderModelTest(TestCase):
    """DocumentFolder模型测试（适配分表重构后的 DocumentFolderPrivate）"""
    
    def setUp(self):
        """测试前准备"""
        self.user = User.objects.create(
            username='testuser',
            nickname='测试用户',
            password_hash=User.make_password('password123'),
            tenant_id='test_tenant'
        )
    
    def test_create_folder(self):
        """测试创建文件夹"""
        folder = DocumentFolder.objects.create(
            name='测试文件夹',
            created_by=self.user
        )
        self.assertEqual(folder.name, '测试文件夹')
        self.assertEqual(folder.created_by, self.user)
        self.assertIsNone(folder.parent)
    
    def test_create_subfolder(self):
        """测试创建子文件夹"""
        parent_folder = DocumentFolder.objects.create(
            name='父文件夹',
            created_by=self.user
        )
        
        subfolder = DocumentFolder.objects.create(
            name='子文件夹',
            parent=parent_folder,
            created_by=self.user
        )
        
        self.assertEqual(subfolder.name, '子文件夹')
        self.assertEqual(subfolder.parent, parent_folder)
        self.assertEqual(parent_folder.files.count(), 0)  # 文件夹本身不包含文件
    
    def test_folder_str(self):
        """测试文件夹字符串表示"""
        folder = DocumentFolder.objects.create(
            name='测试文件夹',
            created_by=self.user
        )
        self.assertEqual(str(folder), '测试文件夹')
    
    def test_folder_ordering(self):
        """测试文件夹排序（显式按创建顺序倒序，避免依赖隐式 ordering）"""
        folder1 = DocumentFolder.objects.create(name='文件夹1', created_by=self.user)
        folder2 = DocumentFolder.objects.create(name='文件夹2', created_by=self.user)
        folder3 = DocumentFolder.objects.create(name='文件夹3', created_by=self.user)
        
        folders = list(DocumentFolder.objects.all().order_by('-id'))
        self.assertEqual(folders[0], folder3)  # 按创建顺序倒序
        self.assertEqual(folders[1], folder2)
        self.assertEqual(folders[2], folder1)


class DocumentFileModelTest(TestCase):
    """DocumentFile模型测试（适配分表重构后的 DocumentFilePrivate）"""
    
    def setUp(self):
        """测试前准备"""
        self.user = User.objects.create(
            username='testuser',
            nickname='测试用户',
            password_hash=User.make_password('password123'),
            tenant_id='test_tenant'
        )
        self.folder = DocumentFolder.objects.create(
            name='测试文件夹',
            created_by=self.user
        )
    
    def test_create_file(self):
        """测试创建文件"""
        file = DocumentFile.objects.create(
            name='测试文件.pdf',
            display_name='测试文件.pdf',
            folder=self.folder,
            file_path='/uploads/test.pdf',
            file_size=1024,
            file_type='application/pdf',
            created_by=self.user
        )
        self.assertEqual(file.name, '测试文件.pdf')
        self.assertEqual(file.folder, self.folder)
        self.assertEqual(file.file_size, 1024)
        self.assertEqual(file.file_type, 'application/pdf')
    
    def test_create_file_without_folder(self):
        """测试创建无文件夹的文件"""
        file = DocumentFile.objects.create(
            name='根目录文件.txt',
            display_name='根目录文件.txt',
            file_path='/uploads/root.txt',
            file_size=512,
            file_type='text/plain',
            created_by=self.user
        )
        self.assertEqual(file.name, '根目录文件.txt')
        self.assertIsNone(file.folder)
    
    def test_file_str(self):
        """测试文件字符串表示"""
        file = DocumentFile.objects.create(
            name='测试文件.pdf',
            display_name='测试文件.pdf',
            folder=self.folder,
            file_path='/uploads/test.pdf',
            file_size=1024,
            file_type='application/pdf',
            created_by=self.user
        )
        self.assertEqual(str(file), '测试文件.pdf')
    
    def test_file_folder_relation(self):
        """测试文件与文件夹的关联"""
        file1 = DocumentFile.objects.create(
            name='文件1.txt',
            display_name='文件1.txt',
            folder=self.folder,
            file_path='/uploads/file1.txt',
            file_size=100,
            file_type='text/plain',
            created_by=self.user
        )
        file2 = DocumentFile.objects.create(
            name='文件2.txt',
            display_name='文件2.txt',
            folder=self.folder,
            file_path='/uploads/file2.txt',
            file_size=200,
            file_type='text/plain',
            created_by=self.user
        )
        
        # 通过文件夹的files属性访问文件
        self.assertEqual(self.folder.files.count(), 2)
        self.assertIn(file1, self.folder.files.all())
        self.assertIn(file2, self.folder.files.all())
    
    def test_file_ordering(self):
        """测试文件排序（显式按创建顺序倒序）"""
        file1 = DocumentFile.objects.create(
            name='文件1.txt',
            display_name='文件1.txt',
            folder=self.folder,
            file_path='/uploads/file1.txt',
            file_size=100,
            file_type='text/plain',
            created_by=self.user
        )
        file2 = DocumentFile.objects.create(
            name='文件2.txt',
            display_name='文件2.txt',
            folder=self.folder,
            file_path='/uploads/file2.txt',
            file_size=200,
            file_type='text/plain',
            created_by=self.user
        )
        
        files = list(self.folder.files.all().order_by('-id'))
        self.assertEqual(files[0], file2)  # 按创建顺序倒序
        self.assertEqual(files[1], file1)
    
    def test_delete_folder_not_cascade_file(self):
        """测试删除文件夹不会级联删除文件（新模型 folder 外键为 SET_NULL）"""
        file = DocumentFile.objects.create(
            name='文件.txt',
            display_name='文件.txt',
            folder=self.folder,
            file_path='/uploads/file.txt',
            file_size=100,
            file_type='text/plain',
            created_by=self.user
        )
        
        folder_id = self.folder.id
        self.folder.delete()

        # 软删除：文件夹记录保留（默认管理器查不到，all_objects 可查到），文件不被级联删除
        self.assertTrue(DocumentFile.objects.filter(id=file.id).exists())
        file.refresh_from_db()
        # 软删除不会触发外键 SET_NULL（SET_NULL 仅在物理删除时生效），
        # 文件仍指向原文件夹（仅该文件夹被标记为已删除）
        self.assertIsNotNone(file.folder)
        self.assertEqual(file.folder_id, folder_id)
        # 默认管理器排除软删除记录
        self.assertFalse(DocumentFolder.objects.filter(id=folder_id).exists())
        # all_objects 仍能查到，证明是软删除而非硬删除
        self.assertTrue(DocumentFolder.all_objects.filter(id=folder_id).exists())
