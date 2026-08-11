import os, django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "spug.settings")
django.setup()
from django.test import TestCase
from apps.document.models import DocumentFolderPrivate, DocumentFilePrivate
from tests.helpers.test_base import make_user, make_client, setup_test_env, post_json
import tempfile, shutil
from django.conf import settings

admin = make_user("dbg_admin", is_supper=True)
setup_test_env()
client = make_client(admin)
client.defaults["HTTP_X_REAL_IP"] = "127.0.0.1"
storage = os.path.join(settings.BASE_DIR, "storage", "documents")
tmp = tempfile.mkdtemp(prefix="dbg_", dir=storage)
ud = os.path.join(tmp, "user-" + str(admin.id))
os.makedirs(ud, exist_ok=True)
folder = DocumentFolderPrivate.objects.create(name="dbg_folder", created_by=admin, tenant_id="admin")
old_path = os.path.join(ud, "old.txt")
with open(old_path, "wb") as f: f.write(b"old")
old = DocumentFilePrivate.objects.create(name="dbg.txt", display_name="dbg.txt", physical_name="dbg.txt", file_path=old_path, file_size=3, file_type="text/plain", folder=folder, created_by=admin, tenant_id="admin")
src_path = os.path.join(ud, "src.txt")
with open(src_path, "wb") as f: f.write(b"new")
src = DocumentFilePrivate.objects.create(name="dbg.txt", display_name="dbg.txt", physical_name="dbg.txt", file_path=src_path, file_size=3, file_type="text/plain", created_by=admin, tenant_id="admin")
resp = post_json(client, "/document/file/copy/", {
    "file_id": src.id, "is_public": False,
    "folder_id": folder.id, "conflict_action": "replace",
})
print("RESP:", resp.status_code, resp.json())
print("old exists:", DocumentFilePrivate.objects.filter(id=old.id).exists())
print("src exists:", DocumentFilePrivate.objects.filter(id=src.id).exists())
print("folder files:", list(DocumentFilePrivate.objects.filter(folder=folder).values_list("id", "display_name")))
DocumentFolderPrivate.objects.filter(name="dbg_folder").delete()
DocumentFilePrivate.objects.filter(file_path__startswith=tmp).delete()
shutil.rmtree(tmp, ignore_errors=True)
