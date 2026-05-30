import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Security: read from environment variables
DEBUG = os.environ.get('DEBUG', 'False').lower() == 'true'

_allowed_hosts = os.environ.get('ALLOWED_HOSTS', '127.0.0.1,localhost')
ALLOWED_HOSTS = [h.strip() for h in _allowed_hosts.split(',') if h.strip()]

# SECRET_KEY is handled in settings.py (from DJANGO_SECRET_KEY env var)
# Do NOT set SECRET_KEY here

# Media files settings
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')
MEDIA_URL = '/media/'
