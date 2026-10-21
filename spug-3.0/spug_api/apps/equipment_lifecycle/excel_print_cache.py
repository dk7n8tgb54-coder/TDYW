# Copyright: (c) OpenSpug Organization. https://github.com/openspug
# Released under the AGPL-3.0 License.
"""设备全生命周期——统一打印 PDF 预览缓存（2026-10-21）。

「打印预览」页签高频打开，与导出 PDF 共用同一生成服务（excel_ledger_
services.export_pdf_file 的引擎路径），生成结果按内容寻址缓存：

- key = sha256(缓存版本 + 台账填写记录 ID + 版本 ID + 填写值 JSON +
  打印参数 JSON + 引擎名)：台账值、模板版本或打印配置任一变化都会
  得到新 key，旧缓存自然失效，无需显式失效通知；
- 存储在容器临时目录（每容器独立，重启即清），不进 media 卷、不污染
  用户文件；写入时机会式清理（过期与超量淘汰），不做后台任务。
"""
import hashlib
import os
import tempfile
import time

PRINT_CACHE_VERSION = 2
CACHE_DIR_NAME = 'el_print_pdf_cache'
CACHE_TTL_SECONDS = 6 * 3600
CACHE_MAX_FILES = 200


def cache_key(record_id, version_id, values_json, params_json, engine):
    """内容寻址缓存键（任一输入变化即新键，旧缓存自然失效）。"""
    digest = hashlib.sha256()
    for part in (PRINT_CACHE_VERSION, record_id, version_id,
                 values_json or '', params_json or '', engine or ''):
        digest.update(str(part).encode('utf-8'))
        digest.update(b'\x1f')
    return digest.hexdigest()


def _cache_dir():
    return os.path.join(tempfile.gettempdir(), CACHE_DIR_NAME)


def load(key):
    """命中返回 PDF 字节，未命中/过期返回 None（不抛异常）。"""
    path = os.path.join(_cache_dir(), '%s.pdf' % key)
    try:
        if os.path.isfile(path) and \
                time.time() - os.path.getmtime(path) <= CACHE_TTL_SECONDS:
            with open(path, 'rb') as f:
                content = f.read()
            if content:
                return content
    except OSError:
        pass
    return None


def store(key, content):
    """写入缓存（尽力而为，失败不影响导出主流程），并做机会式清理。"""
    cache_dir = _cache_dir()
    try:
        os.makedirs(cache_dir, exist_ok=True)
        path = os.path.join(cache_dir, '%s.pdf' % key)
        with open(path, 'wb') as f:
            f.write(content)
        _cleanup(cache_dir)
    except OSError:
        pass


def _cleanup(cache_dir):
    """过期删除 + 超量淘汰最旧（缓存量小，同步清理成本可忽略）。"""
    try:
        entries = [os.path.join(cache_dir, name)
                   for name in os.listdir(cache_dir) if name.endswith('.pdf')]
    except OSError:
        return
    now = time.time()
    live = []
    for path in entries:
        try:
            if now - os.path.getmtime(path) > CACHE_TTL_SECONDS:
                os.remove(path)
            else:
                live.append((os.path.getmtime(path), path))
        except OSError:
            continue
    if len(live) <= CACHE_MAX_FILES:
        return
    live.sort()
    for _mtime, path in live[:len(live) - CACHE_MAX_FILES]:
        try:
            os.remove(path)
        except OSError:
            continue
