#!/usr/bin/env python3
"""Docker sidecar 中执行的外部 HTTP 探活与日志轮转。"""
import json
import os
import shutil
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

URL = os.environ.get('HEALTH_PROBE_URL', 'http://tdyw/api/document/health/')
OUTPUT = os.environ.get('HEALTH_PROBE_LOG', '/var/log/tdyw/health-probe.jsonl')
TIMEOUT = float(os.environ.get('HEALTH_PROBE_TIMEOUT', '10'))
INTERVAL = int(os.environ.get('HEALTH_PROBE_INTERVAL', '60'))
PROBE_MAX_BYTES = int(os.environ.get('HEALTH_PROBE_MAX_BYTES', str(50 * 1024 * 1024)))
NGINX_LOG = os.environ.get('NGINX_LOG', '/var/log/nginx/run_metrics.log')
NGINX_MAX_BYTES = int(os.environ.get('NGINX_MAX_BYTES', str(200 * 1024 * 1024)))


def _rotate(path, max_bytes, keep):
    """copytruncate 轮转，保证 Nginx 仍持有的文件描述符继续可写。"""
    try:
        if not os.path.exists(path):
            return
        marker = f'{path}.last_rotation'
        today = datetime.now(timezone.utc).date().isoformat()
        try:
            with open(marker, encoding='ascii') as marker_file:
                last_rotation = marker_file.read().strip()
        except OSError:
            last_rotation = ''
        if last_rotation == today and os.path.getsize(path) <= max_bytes:
            return
        for index in range(keep, 1, -1):
            source = f'{path}.{index - 1}'
            target = f'{path}.{index}'
            if os.path.exists(target):
                os.remove(target)
            if os.path.exists(source):
                os.replace(source, target)
        shutil.copy2(path, f'{path}.1')
        with open(path, 'w', encoding='utf-8'):
            pass
        with open(marker, 'w', encoding='ascii') as stream:
            stream.write(today)
        cutoff = time.time() - keep * 86400
        prefix = f'{os.path.basename(path)}.'
        directory = os.path.dirname(path) or '.'
        for name in os.listdir(directory):
            candidate = os.path.join(directory, name)
            if name.startswith(prefix) and not name.endswith('last_rotation'):
                try:
                    if os.path.getmtime(candidate) < cutoff:
                        os.remove(candidate)
                except OSError:
                    pass
    except OSError:
        # 日志轮转失败不能阻塞探活或改变健康结果。
        pass


def probe_once():
    started = time.monotonic()
    status = None
    success = False
    error_type = ''
    try:
        request = urllib.request.Request(URL, method='GET', headers={'Accept': 'application/json'})
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            status = response.status
            success = 200 <= status < 300
            body = response.read(65536)
            if success:
                try:
                    payload = json.loads(body.decode('utf-8'))
                    if payload.get('error'):
                        success = False
                        error_type = 'business_error'
                except (UnicodeDecodeError, json.JSONDecodeError, AttributeError):
                    pass
            if not success:
                error_type = error_type or 'http_status'
    except urllib.error.HTTPError as exc:
        status = exc.code
        error_type = 'http_status'
    except urllib.error.URLError as exc:
        error_type = 'network'
        if getattr(exc, 'reason', None):
            error_type = f'network:{type(exc.reason).__name__}'
    except TimeoutError:
        error_type = 'timeout'
    except Exception:
        error_type = 'probe_error'
    record = {
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'success': success,
        'http_status': status,
        'duration_ms': round((time.monotonic() - started) * 1000),
        'error_type': error_type,
    }
    os.makedirs(os.path.dirname(OUTPUT) or '.', exist_ok=True)
    with open(OUTPUT, 'a', encoding='utf-8') as stream:
        stream.write(json.dumps(record, ensure_ascii=True) + '\n')
    _rotate(OUTPUT, PROBE_MAX_BYTES, 7)
    _rotate(NGINX_LOG, NGINX_MAX_BYTES, 7)
    return 0 if success else 1


def main():
    if os.environ.get('HEALTH_PROBE_ONCE', '').lower() in ('1', 'true', 'yes'):
        return probe_once()
    while True:
        probe_once()
        time.sleep(INTERVAL)


if __name__ == '__main__':
    raise SystemExit(main())
