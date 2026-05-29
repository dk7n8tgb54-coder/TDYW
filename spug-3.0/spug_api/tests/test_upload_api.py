import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')
import django
django.setup()

import logging
logging.basicConfig(level=logging.DEBUG)

from django.test import RequestFactory
from apps.document.views import FileUploadView
from apps.account.models import User
from django.core.files.uploadedfile import SimpleUploadedFile

try:
    factory = RequestFactory()
    user = User.objects.first()
    print(f"Testing upload as user: {user.username}")
    
    test_file = SimpleUploadedFile("test.txt", b"test content", content_type="text/plain")
    
    request = factory.post('/api/document/file/upload/', {
        'folder_id': '',
        'is_public': 'true',
    }, format='multipart')
    request.FILES['file'] = test_file
    request.user = user
    
    print(f"Request POST: {request.POST}")
    print(f"Request FILES: {request.FILES}")
    
    view = FileUploadView()
    response = view.post(request)
    
    print(f"\nResponse status: {response.status_code}")
    print(f"Response content: {response.content}")
    
except Exception as e:
    import traceback
    print(f"Error: {e}")
    traceback.print_exc()
