"""手动触发全量扫描，生成今日 expiring_daily 提醒"""
import django
django.setup()
from apps.radio_license.tasks import scan_radio_license_expiration
result = scan_radio_license_expiration.apply()
print('RESULT:', result.get())
