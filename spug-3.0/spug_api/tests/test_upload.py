import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')
import django
django.setup()

from apps.document.models import DocumentFolderPublic, DocumentFilePublic
from apps.account.models import User

try:
    print("Testing DocumentFolderPublic model...")
    folders = DocumentFolderPublic.objects.all()
    print(f"Found {folders.count()} public folders")
    
    print("\nTesting DocumentFilePublic model...")
    files = DocumentFilePublic.objects.all()
    print(f"Found {files.count()} public files")
    
    print("\nTesting user...")
    user = User.objects.first()
    print(f"First user: {user.username if user else 'None'}")
    
    print("\nTesting create folder...")
    folder = DocumentFolderPublic(name="test_folder", created_by=user)
    folder.save()
    print(f"Created folder with id: {folder.id}")
    
    print("\nTesting create file record...")
    file = DocumentFilePublic(
        name="test.txt",
        folder=folder,
        file_path="/tmp/test.txt",
        file_size=100,
        file_type="text/plain",
        created_by=user
    )
    file.save()
    print(f"Created file with id: {file.id}")
    
    print("\nCleaning up...")
    file.delete()
    folder.delete()
    print("Done!")
    
except Exception as e:
    import traceback
    print(f"Error: {e}")
    traceback.print_exc()
