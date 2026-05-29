import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')
import django
django.setup()

import logging
logger = logging.getLogger(__name__)

try:
    from apps.document.views import FileUploadView
    print("FileUploadView imported successfully")
    
    import inspect
    source = inspect.getsource(FileUploadView.post)
    print("\n=== FileUploadView.post source (first 2000 chars) ===")
    print(source[:2000])
except Exception as e:
    import traceback
    print(f"Error: {e}")
    traceback.print_exc()
