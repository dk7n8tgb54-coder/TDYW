# Copyright: (c) OpenSpug Organization. https://github.com/openspug
# Released under the AGPL-3.0 License.
"""设备全生命周期——浏览器打印引擎 PDF 服务（2026-10-21）。

统一打印 HTML（excel_print_html，与网页同一布局规则）→ 无头 Chromium
打印为 PDF。与 LibreOffice 路线（excel_pdf_service.convert_xlsx_to_pdf）
并列为 EXCEL_PDF_ENGINE 的两个引擎；浏览器引擎不经 LibreOffice，网页与
PDF 的纸张/边距/缩放/分页由 excel_print_layout 唯一定义。

进程模型：Chromium 由独立 worker 子进程（excel_print_pdf_worker）启动——
gunicorn gevent worker 打过 monkey 补丁，playwright 的事件循环必须隔离在
干净进程里；子进程按超时强杀、随进程退出释放全部资源，临时文件由
调用方的 TemporaryDirectory 统一清理，绝不污染用户源文件。

- detect_browser：EL_CHROMIUM_PATH → PATH（chromium/chrome）→ playwright
  自带浏览器（PLAYWRIGHT_BROWSERS_PATH 或默认缓存目录），进程内缓存；
- render_html_to_pdf：写临时 HTML → 子进程渲染 → 校验输出存在且非空；
  任何失败抛 PdfConversionError（含子进程回传的错误明细），绝不伪造 PDF；
- 并发：模块级信号量限制同时运行的 Chromium 子进程数
  （EL_BROWSER_PDF_CONCURRENCY，缺省 2），批量导出串行调用时互不影响。

部署依赖（与 LibreOffice 路线同口径）：pip playwright + chromium 浏览器
（docker 镜像构建时 playwright install chromium --with-deps）+ 中文字体
（fonts-noto-cjk，未安装时中文渲染为替换字体，不产生报错）。
"""
import glob
import json
import os
import shutil
import subprocess
import sys
import threading

from django.conf import settings

from apps.equipment_lifecycle.excel_pdf_service import (
    CONVERT_TIMEOUT_SECONDS,
    PdfConversionError,
)

BROWSER_PDF_TIMEOUT_SECONDS = CONVERT_TIMEOUT_SECONDS
_BROWSER_PATH_ENV = 'EL_CHROMIUM_PATH'
_CONCURRENCY_ENV = 'EL_BROWSER_PDF_CONCURRENCY'
_DEFAULT_CONCURRENCY = 2
# PATH 上的常见 Chromium 可执行名（Linux 容器为主）
_CANDIDATE_BINARIES = (
    'chromium', 'chromium-browser', 'google-chrome', 'google-chrome-stable',
)
_concurrency_semaphore = None
_concurrency_lock = threading.Lock()
_detected = None  # 进程内缓存：None=未探测 / ''=不可用 / 路径


def _concurrency():
    try:
        value = int(os.environ.get(_CONCURRENCY_ENV) or
                    getattr(settings, 'EL_BROWSER_PDF_CONCURRENCY', 0))
    except (TypeError, ValueError):
        value = 0
    return value if value > 0 else _DEFAULT_CONCURRENCY


def _semaphore():
    global _concurrency_semaphore
    with _concurrency_lock:
        if _concurrency_semaphore is None:
            _concurrency_semaphore = threading.BoundedSemaphore(_concurrency())
        return _concurrency_semaphore


def _playwright_chromium():
    """playwright 自带浏览器目录中的 Chromium 可执行文件（Linux 路径形态）。"""
    roots = [os.environ.get('PLAYWRIGHT_BROWSERS_PATH'),
             os.path.expanduser('~/.cache/ms-playwright')]
    for root in roots:
        if not root or not os.path.isdir(root):
            continue
        patterns = [
            os.path.join(root, 'chromium-*', 'chrome-linux*', 'chrome'),
            os.path.join(root, 'chromium_headless_shell-*',
                         'chrome-linux*', 'headless_shell'),
        ]
        for pattern in patterns:
            matches = sorted(glob.glob(pattern))
            if matches:
                return matches[-1]
    return None


def detect_browser():
    """探测无头 Chromium 可执行文件；不可用返回 None（结果进程内缓存）。"""
    global _detected
    if _detected is not None:
        return _detected or None
    detected = ''
    exe = (os.environ.get(_BROWSER_PATH_ENV) or '').strip()
    if exe and os.path.isfile(exe):
        detected = exe
    if not detected:
        for name in _CANDIDATE_BINARIES:
            found = shutil.which(name)
            if found:
                detected = found
                break
    if not detected:
        found = _playwright_chromium()
        if found and os.path.isfile(found):
            detected = found
    _detected = detected
    return detected or None


def _worker_command(html_path, pdf_path, timeout):
    return [
        sys.executable, '-m',
        'apps.equipment_lifecycle.excel_print_pdf_worker',
        '--html', html_path, '--out', pdf_path, '--timeout', str(int(timeout)),
    ]


def _worker_env():
    """worker 子进程环境：注入 spug_api 到 PYTHONPATH（保证可导入 apps），
    并把父进程探测到的浏览器路径显式传给 worker（EL_CHROMIUM_PATH）——
    playwright 默认按 PLAYWRIGHT_BROWSERS_PATH/版本目录解析，gunicorn 等
    运行环境的变量与安装时不一致会导致漂移；探测结果权威。"""
    env = dict(os.environ)
    api_root = os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))  # apps/equipment_lifecycle/*.py → spug_api
    python_path = env.get('PYTHONPATH')
    env['PYTHONPATH'] = api_root + (os.pathsep + python_path
                                    if python_path else '')
    if not env.get(_BROWSER_PATH_ENV):
        detected = detect_browser()
        if detected:
            env[_BROWSER_PATH_ENV] = detected
    return env


def _error_detail(stderr_bytes):
    """从 worker stderr 读取错误明细（末行 JSON {'error': ...}）。"""
    try:
        text = (stderr_bytes or b'').decode('utf-8', 'replace').strip()
        for line in reversed(text.splitlines()):
            line = line.strip()
            if line.startswith('{'):
                return str(json.loads(line).get('error') or line)
        return text[-300:]
    except Exception:
        return ''


def render_html_to_pdf(html_content, out_dir,
                       timeout=BROWSER_PDF_TIMEOUT_SECONDS):
    """统一打印 HTML → PDF 字节落盘，返回 pdf 路径（调用方负责清理目录）。"""
    html_path = os.path.join(out_dir, 'print.html')
    pdf_path = os.path.join(out_dir, 'print.pdf')
    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(html_content)
    command = _worker_command(html_path, pdf_path, timeout)
    with _semaphore():
        try:
            process = subprocess.run(
                command, capture_output=True, timeout=timeout + 10,
                env=_worker_env())
        except subprocess.TimeoutExpired:
            raise PdfConversionError('浏览器打印超时（%d 秒）' % timeout)
        except OSError as e:
            raise PdfConversionError('浏览器打印进程启动失败：%s' % e)
    if process.returncode != 0 or not os.path.isfile(pdf_path) \
            or os.path.getsize(pdf_path) == 0:
        detail = _error_detail(process.stderr) or '未知错误'
        raise PdfConversionError('浏览器打印失败：%s' % detail)
    return pdf_path
