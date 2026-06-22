#!/bin/bash
# 历史兼容脚本：原 dev-worker 已废弃
# 原职责: 监听 document.merge,document.batch,document.cleanup（导致与 general worker 重复消费 document.merge）
# 现职责: 转调专用 merge worker 脚本，避免历史引用监听错误队列
# 依据: 《资料库并发上传与状态机修复方案》5.3 拆分 Celery merge worker
# 建议: 新部署请直接使用 start-celery-merge.sh
exec bash /data/spug/spug_api/tools/start-celery-merge.sh
