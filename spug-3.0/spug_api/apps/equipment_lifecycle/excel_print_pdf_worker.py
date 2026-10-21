# Copyright: (c) OpenSpug Organization. https://github.com/openspug
# Released under the AGPL-3.0 License.
"""无头 Chromium 打印 worker（独立子进程运行，2026-10-21）。

由 excel_browser_pdf_service.render_html_to_pdf 以
`python -m apps.equipment_lifecycle.excel_print_pdf_worker` 方式调用。
独立进程的原因：gunicorn gevent worker 进程打过 monkey 补丁，playwright
sync API 的事件循环与信号处理必须运行在干净进程中；子进程按超时自杀、
随退出释放浏览器进程与临时资源，父进程在超时后强杀不残留。

用法：
  --html <path>   统一打印 HTML 文件（excel_print_html 渲染产物）
  --out <path>    PDF 输出路径
  --timeout <秒>  渲染超时（goto/fonts/pdf 共享预算）
  --probe         只探测浏览器可用性（launch + close），输出 OK

约定：成功输出 OK 并退出码 0；失败把 {'error': ...} JSON 打到 stderr
（末行）并退出非 0，父进程读取该明细转成业务错误。
"""
import argparse
import json
import os
import shutil
import sys


def _launch_kwargs():
    """Chromium 启动参数：容器 root 需要 --no-sandbox，/dev/shm 过小需要
    --disable-dev-shm-usage；EL_CHROMIUM_PATH / PATH 上的系统浏览器优先
    （与 detect_browser 的探测顺序一致，避免探测与使用不一致）。"""
    kwargs = {
        'headless': True,
        'args': [
            '--no-sandbox',
            '--disable-dev-shm-usage',
            '--disable-gpu',
            '--force-color-profile=srgb',
            '--font-render-hinting=none',
        ],
    }
    exe = (os.environ.get('EL_CHROMIUM_PATH') or '').strip()
    if not exe:
        for name in ('chromium', 'chromium-browser', 'google-chrome',
                     'google-chrome-stable'):
            exe = shutil.which(name)
            if exe:
                break
    if exe:
        kwargs['executable_path'] = exe
    return kwargs


def render(html_path, out_path, timeout_seconds):
    """打开 HTML → 等待字体就绪 → 按 @page CSS 页面尺寸打印 PDF。"""
    from playwright.sync_api import sync_playwright
    timeout_ms = int(timeout_seconds * 1000)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(**_launch_kwargs())
        try:
            page = browser.new_page()
            page.goto('file://' + html_path, wait_until='load',
                      timeout=timeout_ms)
            try:
                # 等待 WebFont/系统字体就绪，避免首帧用替换字体渲染
                page.evaluate('document.fonts.ready')
            except Exception:
                pass  # 字体等待失败不阻断（回退即时渲染）
            page.pdf(
                path=out_path,
                prefer_css_page_size=True,
                print_background=True,
                margin={'top': '0', 'bottom': '0', 'left': '0', 'right': '0'},
            )
        finally:
            browser.close()


def main():
    parser = argparse.ArgumentParser(description='Chromium print-to-PDF worker')
    parser.add_argument('--html', default='')
    parser.add_argument('--out', default='')
    parser.add_argument('--timeout', type=float, default=120)
    parser.add_argument('--probe', action='store_true')
    args = parser.parse_args()
    try:
        if args.probe:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(**_launch_kwargs())
                browser.close()
        else:
            if not args.html or not args.out:
                raise ValueError('--html 与 --out 必填')
            render(args.html, args.out, args.timeout)
            if not os.path.isfile(args.out) or os.path.getsize(args.out) == 0:
                raise ValueError('PDF 输出为空')
    except Exception as e:  # noqa: BLE001——明细回传父进程转业务错误
        sys.stderr.write(json.dumps(
            {'error': str(e)[:500]}, ensure_ascii=False) + '\n')
        sys.exit(2)
    sys.stdout.write('OK\n')


if __name__ == '__main__':
    main()
