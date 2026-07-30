import os, django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "spug.settings")
django.setup()
from apps.interference.models import Interference
from apps.runlog.models import RunLog
from apps.home.models import Notice, Navigation
from apps.upgrade.models import UpgradeRecord, UpgradeSystem
from apps.upgrade.models_checklist import UpgradeRecordStep

def chk(m, f):
    return f in [x.name for x in m._meta.get_fields()]

print("R4", chk(Interference, "is_deleted"))
print("R5", chk(RunLog, "is_deleted"))
print("R11", chk(Notice, "is_deleted"), chk(Navigation, "is_deleted"))
print("R12", chk(UpgradeRecord, "is_deleted"), chk(UpgradeRecordStep, "is_deleted"), chk(UpgradeSystem, "is_deleted"))
print("R13", chk(Notice, "tenant_id"), chk(Navigation, "tenant_id"))
