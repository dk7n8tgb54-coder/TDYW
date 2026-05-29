import os

DEBUG = False
ALLOWED_HOSTS = ['127.0.0.1', 'localhost', '*']
SECRET_KEY = 'Dc1Wpu2QCmt1R4vW!5Rmj7w%dcZxeiod#ReGNWSn1jjhyfrCr!'

# 注意：数据库配置已移至 settings.py
# 如需覆盖，请取消下面的注释并修改
# DATABASES = { ... }

# Media files settings
import sys
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')
MEDIA_URL = '/media/'
