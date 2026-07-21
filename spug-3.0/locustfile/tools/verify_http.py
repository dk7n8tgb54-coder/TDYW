# -*- coding: utf-8 -*-
"""HTTP 冒烟测试：真实打到目标环境（默认 localhost，即生产容器 tdyw 的 80 端口，可用 BASE 环境变量覆盖）。

生产 tdyw：
    set BASE=http://<tdyw-host>:<port>  (PowerShell)
    export BASE=http://<tdyw-host>:<port>  (bash)
账号默认复用现有生产账号 tongxinke，可用 STRESS_USER / STRESS_PASS 覆盖。
"""
import os
import json
import urllib.request
import urllib.error

BASE = os.environ.get("BASE", "http://localhost")
STRESS_USER = os.environ.get("STRESS_USER", "tongxinke")
STRESS_PASS = os.environ.get("STRESS_PASS", "Dt@6299093")


def call(method, path, payload=None, token=None, files=None):
    url = BASE + path
    headers = {}
    if token:
        headers["x-token"] = token
    data = None
    if files is not None:
        import io, random, string
        boundary = "----spugstress" + "".join(random.choices(string.ascii_letters, k=8))
        body = bytearray()
        for k, v in (payload or {}).items():
            body += f"--{boundary}\r\n".encode()
            body += f'Content-Disposition: form-data; name="{k}"\r\n\r\n'.encode()
            body += str(v).encode() + b"\r\n"
        for k, (fname, fdata, ftype) in files.items():
            body += f"--{boundary}\r\n".encode()
            body += f'Content-Disposition: form-data; name="{k}"; filename="{fname}"\r\n'.encode()
            body += f"Content-Type: {ftype}\r\n\r\n".encode()
            body += fdata + b"\r\n"
        body += f"--{boundary}--\r\n".encode()
        headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
        data = bytes(body)
    elif payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        resp = urllib.request.urlopen(req, timeout=30)
        return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


# 1. 登录（默认复用现有生产账号）
st, body = call("POST", "/api/account/login/",
                {"username": STRESS_USER, "password": STRESS_PASS, "type": "default"})
print("LOGIN", st, body[:160])
tok = (json.loads(body).get("data") or {}).get("access_token")
assert tok, "登录失败，未拿到 token"
print("TOKEN", tok[:8])

# 2. 创建文件夹
st, body = call("POST", "/api/document/folder/",
                {"name": "smoke_folder", "parent_id": None, "is_public": False}, token=tok)
print("CREATE_FOLDER", st, body[:160])
fid = (json.loads(body).get("data") or {}).get("id")
assert fid, "创建文件夹未返回 id"

# 3. 列表
st, body = call("GET", "/api/document/folder/?is_public=false", token=tok)
print("LIST", st)

# 4. 普通上传
st, body = call("POST", "/api/document/upload/",
                {"folder_id": fid, "is_public": "false"},
                token=tok, files={"file": ("smoke.txt", b"hello world", "text/plain")})
print("UPLOAD", st, body[:160])

# 5. 分片上传 + 合并
content = b"x" * (2 * 1024 * 1024)
import hashlib
h = hashlib.md5(content).hexdigest()
total = 2
for i in range(total):
    part = content[i * 1024 * 1024:(i + 1) * 1024 * 1024]
    st, body = call("POST", "/api/document/upload_chunk/",
                     {"file_name": "smoke.bin", "file_size": len(content), "chunk_index": i,
                      "total_chunks": total, "file_hash": h, "folder_id": fid, "is_public": "false"},
                     token=tok, files={"file": (f"smoke.bin.part{i}", part, "application/octet-stream")})
    print("CHUNK", i, st, body[:120])

st, body = call("POST", "/api/document/merge_chunks/",
                {"file_name": "smoke.bin", "file_size": len(content),
                 "total_chunks": total, "file_hash": h, "folder_id": fid, "is_public": False}, token=tok)
print("MERGE", st, body[:160])

# 6. 只读探针
for p in ["/api/document/transfers/?is_public=false",
          "/api/document/disk_usage/?is_public=false",
          "/api/document/health/db-pool/"]:
    st, body = call("GET", p, token=tok)
    print("GET", p, st)

# 7. 清理
st, body = call("DELETE", f"/api/document/folder/?id={fid}&is_public=false", token=tok)
print("CLEANUP", st, body[:120])
print("SMOKE_OK")
