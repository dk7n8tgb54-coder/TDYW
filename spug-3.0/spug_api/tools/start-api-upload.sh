#!/bin/bash
# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
# start upload api service (dedicated Gunicorn for upload endpoints)
#
# 依据: 《资料库并发上传与状态机修复方案》6.2 上传 API 与普通 API 隔离
#
# 职责: 专门处理文件上传相关接口，避免大文件落盘阻塞普通 API worker
#   - /document/upload/            普通上传
#   - /document/upload_chunk/      分片上传
#   - /document/check_uploaded_chunks/  断点续传检查
#   - /document/merge_chunks/      分片合并请求
#   - /document/merge_status/      合并状态轮询
#
# 端口: 9003 (9001=普通API, 9002=WebSocket, 9003=上传API)
#
# 与普通 API 的差异:
#   - timeout 更长 (600s)，因为大文件上传/合并可能耗时长
#   - 独立 worker，落盘 I/O 不影响普通查询接口

cd $(dirname $(dirname $0))
if [ -f ./venv/bin/activate ]; then
  source ./venv/bin/activate
fi

# 上传服务超时时间，默认 600s，可通过环境变量覆盖
UPLOAD_API_TIMEOUT=${UPLOAD_API_TIMEOUT:-600}

# 复用 gunicorn.conf.py 基础配置，仅覆盖 bind 和 timeout
exec gunicorn -c gunicorn.conf.py spug.wsgi \
    --bind 127.0.0.1:9003 \
    --timeout ${UPLOAD_API_TIMEOUT}
