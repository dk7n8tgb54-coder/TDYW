import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')
import django
django.setup()

import logging
logging.basicConfig(level=logging.DEBUG)

from apps.document.models import DocumentFolderPublic, DocumentFilePublic
from apps.account.models import User
from apps.document.libs.document_utils import get_document_absolute_path

try:
    user = User.objects.first()
    print(f"User: {user.username}, id: {user.id}")
    
    upload_dir = get_document_absolute_path(
        is_public=True,
        user_id=user.id,
        folder_id=None
    )
    print(f"Upload dir: {upload_dir}")
    
    os.makedirs(upload_dir, exist_ok=True)
    print(f"Directory created/exists")
    
    test_file_path = os.path.join(upload_dir, "test_file.txt")
    with open(test_file_path, 'w') as f:
        f.write("test content")
    print(f"Test file created: {test_file_path}")
    
    os.remove(test_file_path)
    print("Test file removed")
    
except Exception as e:
    import traceback
    print(f"Error: {e}")
    traceback.print_exc()
