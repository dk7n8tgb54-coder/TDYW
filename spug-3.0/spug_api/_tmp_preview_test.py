import urllib.request, urllib.parse, urllib.error
from apps.evidence.attachment_preview_token import generate_attachment_preview_token
from apps.evidence.models import EvidenceAttachment

att = EvidenceAttachment.objects.get(pk=3)
tok = generate_attachment_preview_token(att.id, 1, 'admin', att.module, att.object_type, att.object_id)
print('TOKEN:', tok)
print('FILE_NAME:', att.file_name, 'EXT:', att.file_ext)
url = 'http://127.0.0.1:9001/contract-agreement/attachments/3/preview-file/?preview_token=' + urllib.parse.quote(tok, safe='') + '&fullfilename=' + urllib.parse.quote(att.file_name)
print('URL:', url)
try:
    r = urllib.request.urlopen(url, timeout=30)
    data = r.read()
    print('STATUS', r.status, 'CTYPE', r.headers.get('Content-Type'), 'LEN', len(data))
except urllib.error.HTTPError as e:
    print('HTTPERROR', e.code, e.headers.get('Content-Type'), e.read()[:800])
except Exception as e:
    print('ERR', type(e).__name__, e)
