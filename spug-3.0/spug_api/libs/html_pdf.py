# Copyright: (c) OpenSpug Organization. https://github.com/openspug
# Released under the AGPL-3.0 License.
"""公共 HTML→PDF 适配器（无头 Chromium 打印；2026-10-22 自
equipment_lifecycle/excel_browser_pdf_service 上提为公共层）。

上提背景：该适配器此前仅服务 Excel 台账统一打印一个场景；数字表单台账
PDF（form_pdf_service）成为第二个真实调用场景后，按项目解耦规则
（"新增公共抽象必须有至少两个真实调用场景"）上提到 libs。

render_html_to_pdf 是 HTML 打印为 PDF 的唯一公共入口：写临时 HTML →
独立 worker 子进程（libs.html_pdf_worker）以无头 Chromium 按 @page CSS
打印 → 校验输出存在且非空。适配层不解释 HTML 内容：纸张/方向/分页/
边距等版式语义由调用方在 HTML（@page CSS）与可选参数中定义。

进程模型（沿用 Excel 路线 2026-10-21 方案）：gunicorn gevent worker 进程
打过 monkey 补丁，playwright sync API 的事件循环必须运行在干净进程中，
故 Chromium 由独立 worker 子进程启动：按超时强杀、随进程退出释放全部
资源；临时文件由调用方的 TemporaryDirectory 统一清理，绝不污染业务文件。

- detect_browser：EL_CHROMIUM_PATH → PATH（chromium/chrome）→ playwright
  自带浏览器（PLAYWRIGHT_BROWSERS_PATH 或默认缓存目录），进程内缓存
  （EL_ 前缀为历史部署环境名，保持兼容，含义=无头浏览器可执行文件路径）；
- render_html_to_pdf(html_content, out_dir, timeout, footer_template,
  margin, paper)：footer_template 为 Chromium 页脚 HTML（含 pageNumber/
  totalPages 占位符，须自带内联样式与显式 font-size），传入即启用
  display_header_footer；margin 参数定义内容边距（页脚绘制在下边距
  区域；margin 生效时调用方 HTML 的 @page margin 必须为 0，避免双重
  边距）；paper 为显式纸张参数 {'format': 'A4', 'landscape': bool}，
  提供时经打印参数定纸张（format 与 margin 同用行为确定）并忽略
  @page size，缺省走 prefer_css_page_size（纸张完全由 @page CSS 定义，
  Excel 统一打印 HTML 的既有语义；注意 prefer_css_page_size 与 margin
  同用时 Chromium 忽略 margin，故需要内容边距的场景必须传 paper）；
- 并发：模块级信号量限制同时运行的 Chromium 子进程数
  （HTML_PDF_CONCURRENCY，兼容旧名 EL_BROWSER_PDF_CONCURRENCY，缺省 2）；
- 任何失败抛 HtmlPdfConversionError（含 worker 回传错误明细），绝不伪造
  PDF；调用方负责把业务错误语义转成各自的异常类型。

部署依赖：pip playwright + chromium 浏览器（docker 镜像构建时
playwright install chromium --with-deps）+ 中文字体（fonts-noto-cjk，
未安装时中文渲染为替换字体，不产生报错）。
"""
import glob
import json
import os
import shutil
import subprocess
import sys
import threading

from django.conf import settings


class HtmlPdfConversionError(Exception):
    """HTML→PDF 转换失败（浏览器不可用 / 渲染出错 / 输出为空）。"""


DEFAULT_TIMEOUT_SECONDS = 120
_BROWSER_PATH_ENV = 'EL_CHROMIUM_PATH'
_CONCURRENCY_ENV = 'HTML_PDF_CONCURRENCY'
_CONCURRENCY_ENV_LEGACY = 'EL_BROWSER_PDF_CONCURRENCY'
_DEFAULT_CONCURRENCY = 2
# PATH 上的常见 Chromium 可执行名（Linux 容器为主）
_CANDIDATE_BINARIES = (
    'chromium', 'chromium-browser', 'google-chrome', 'google-chrome-stable',
)
_concurrency_semaphore = None
_concurrency_lock = threading.Lock()
_detected = None  # 进程内缓存：None=未探测 / ''=不可用 / 路径


def _concurrency():
    raw = (os.environ.get(_CONCURRENCY_ENV)
           or os.environ.get(_CONCURRENCY_ENV_LEGACY)
           or getattr(settings, 'HTML_PDF_CONCURRENCY', 0)
           or getattr(settings, 'EL_BROWSER_PDF_CONCURRENCY', 0))
    try:
        value = int(raw)
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


def _worker_command(html_path, pdf_path, timeout, footer_path, margins,
                    paper):
    command = [
        sys.executable, '-m', 'libs.html_pdf_worker',
        '--html', html_path, '--out', pdf_path, '--timeout', str(int(timeout)),
    ]
    if footer_path:
        command += ['--footer-template-file', footer_path]
    for side in ('top', 'bottom', 'left', 'right'):
        value = (margins or {}).get(side)
        if value:
            command += ['--margin-%s' % side, str(value)]
    if paper and paper.get('format'):
        command += ['--paper-format', str(paper['format'])]
        if paper.get('landscape'):
            command += ['--paper-landscape']
    return command


def _worker_env():
    """worker 子进程环境：注入 spug_api 到 PYTHONPATH（保证可导入 libs 与
    apps），并把父进程探测到的浏览器路径显式传给 worker（EL_CHROMIUM_PATH）
    —— playwright 默认按 PLAYWRIGHT_BROWSERS_PATH/版本目录解析，gunicorn 等
    运行环境的变量与安装时不一致会导致漂移；探测结果权威。"""
    env = dict(os.environ)
    api_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
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


def render_html_to_pdf(html_content, out_dir, timeout=DEFAULT_TIMEOUT_SECONDS,
                       footer_template=None, margin=None, paper=None):
    """HTML 内容 → PDF 字节落盘，返回 pdf 路径（调用方负责清理目录）。

    footer_template：Chromium 页脚 HTML（None=不启用页眉页脚）；margin：
    {'top','bottom','left','right'} CSS 长度（None=全 0，配合 @page margin 0
    的整页固定尺寸版式）。启用页脚时内容边距必须经本参数定义。
    paper：{'format': 'A4', 'landscape': bool}，显式纸张模式（margin 生效
    的前提）；缺省按 @page CSS 纸张打印（prefer_css_page_size）。
    """
    html_path = os.path.join(out_dir, 'print.html')
    pdf_path = os.path.join(out_dir, 'print.pdf')
    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(html_content)
    footer_path = ''
    if footer_template:
        footer_path = os.path.join(out_dir, 'footer.html')
        with open(footer_path, 'w', encoding='utf-8') as f:
            f.write(footer_template)
    command = _worker_command(html_path, pdf_path, timeout, footer_path,
                              margin, paper)
    with _semaphore():
        try:
            process = subprocess.run(
                command, capture_output=True, timeout=timeout + 10,
                env=_worker_env())
        except subprocess.TimeoutExpired:
            raise HtmlPdfConversionError('浏览器打印超时（%d 秒）' % timeout)
        except OSError as e:
            raise HtmlPdfConversionError('浏览器打印进程启动失败：%s' % e)
    if process.returncode != 0 or not os.path.isfile(pdf_path) \
            or os.path.getsize(pdf_path) == 0:
        detail = _error_detail(process.stderr) or '未知错误'
        raise HtmlPdfConversionError('浏览器打印失败：%s' % detail)
    return pdf_path
