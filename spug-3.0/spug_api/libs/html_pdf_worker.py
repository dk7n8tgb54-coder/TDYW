# Copyright: (c) OpenSpug Organization. https://github.com/openspug
# Released under the AGPL-3.0 License.
"""无头 Chromium 打印 worker（独立子进程运行）。

由 libs.html_pdf.render_html_to_pdf 以 `python -m libs.html_pdf_worker`
方式调用。独立进程的原因：gunicorn gevent worker 进程打过 monkey 补丁，
playwright sync API 的事件循环与信号处理必须运行在干净进程中；子进程按
超时自杀、随退出释放浏览器进程与临时资源，父进程在超时后强杀不残留。

用法：
  --html <path>   打印 HTML 文件
  --out <path>    PDF 输出路径
  --timeout <秒>  渲染超时（goto/fonts/pdf 共享预算）
  --probe         只探测浏览器可用性（launch + close），输出 OK
  --footer-template-file <path>  Chromium 页脚模板（启用页眉页脚；
                  模板可含 pageNumber/totalPages 占位符，须自带内联样式）
  --margin-top/--margin-bottom/--margin-left/--margin-right <长度>
                  内容边距（CSS 长度；启用页脚时下边距须容纳页脚）

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


def render(html_path, out_path, timeout_seconds, footer_template_path=None,
           margins=None, paper=None):
    """打开 HTML → 等待字体就绪 → 按页面 CSS/参数打印 PDF。

    paper 提供显式纸张（{'format': 'A4', 'landscape': bool}）时经打印
    参数定纸张（margin 参数由此确定生效）；缺省 prefer_css_page_size，
    纸张完全由调用方 HTML 的 @page CSS 定义（margin 缺省全 0）。
    """
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
            margin = {'top': '0', 'bottom': '0', 'left': '0', 'right': '0'}
            for side in ('top', 'bottom', 'left', 'right'):
                if (margins or {}).get(side):
                    margin[side] = margins[side]
            pdf_kwargs = {
                'path': out_path,
                'print_background': True,
                'margin': margin,
            }
            if paper and paper.get('format'):
                pdf_kwargs['format'] = paper['format']
                pdf_kwargs['landscape'] = bool(paper.get('landscape'))
            else:
                pdf_kwargs['prefer_css_page_size'] = True
            if footer_template_path:
                with open(footer_template_path, encoding='utf-8') as f:
                    pdf_kwargs['display_header_footer'] = True
                    pdf_kwargs['footer_template'] = f.read()
                    # Chromium 启用页脚时会渲染默认页眉（日期+标题），
                    # 仅需要页脚的调用方须显式置空页眉
                    pdf_kwargs['header_template'] = '<span></span>'
            page.pdf(**pdf_kwargs)
        finally:
            browser.close()


def main():
    parser = argparse.ArgumentParser(description='Chromium print-to-PDF worker')
    parser.add_argument('--html', default='')
    parser.add_argument('--out', default='')
    parser.add_argument('--timeout', type=float, default=120)
    parser.add_argument('--probe', action='store_true')
    parser.add_argument('--footer-template-file', default='')
    parser.add_argument('--margin-top', default='')
    parser.add_argument('--margin-bottom', default='')
    parser.add_argument('--margin-left', default='')
    parser.add_argument('--margin-right', default='')
    parser.add_argument('--paper-format', default='')
    parser.add_argument('--paper-landscape', action='store_true')
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
            margins = {side: getattr(args, 'margin_%s' % side)
                       for side in ('top', 'bottom', 'left', 'right')}
            paper = None
            if args.paper_format:
                paper = {'format': args.paper_format,
                         'landscape': args.paper_landscape}
            render(args.html, args.out, args.timeout,
                   footer_template_path=args.footer_template_file or None,
                   margins=margins, paper=paper)
            if not os.path.isfile(args.out) or os.path.getsize(args.out) == 0:
                raise ValueError('PDF 输出为空')
    except Exception as e:  # noqa: BLE001——明细回传父进程转业务错误
        sys.stderr.write(json.dumps(
            {'error': str(e)[:500]}, ensure_ascii=False) + '\n')
        sys.exit(2)
    sys.stdout.write('OK\n')


if __name__ == '__main__':
    main()
