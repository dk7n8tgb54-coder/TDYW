# Copyright: (c) OpenSpug Organization. https://github.com/openspug
# Released under the AGPL-3.0 License.
"""设备全生命周期——浏览器打印引擎 PDF 服务（2026-10-21）。

2026-10-22 上提公共层：本模块曾是 HTML→PDF 适配器的唯一真实调用场景，
数字表单台账 PDF（form_pdf_service）成为第二个场景后，实现整体上提为
公共适配器 libs.html_pdf（含 worker 子进程 libs.html_pdf_worker）。
本模块保留 Excel 路线侧的公开函数签名与异常类型（PdfConversionError），
内部委托公共层——既有调用方（excel_template_services / excel_pdf_service）
与测试补丁目标（detect_browser / render_html_to_pdf）不变。

- detect_browser：探测无头 Chromium（委托公共层，结果进程内缓存）；
- render_html_to_pdf：统一打印 HTML → 无头 Chromium 打印为 PDF，任何
  失败转 PdfConversionError（公共层明细透传），绝不伪造 PDF。

部署依赖与引擎选择见 excel_pdf_service / libs.html_pdf 模块注释。
"""
from apps.equipment_lifecycle.excel_pdf_service import (
    CONVERT_TIMEOUT_SECONDS,
    PdfConversionError,
)
from libs import html_pdf

BROWSER_PDF_TIMEOUT_SECONDS = CONVERT_TIMEOUT_SECONDS


def detect_browser():
    """探测无头 Chromium 可执行文件；不可用返回 None（结果进程内缓存）。"""
    return html_pdf.detect_browser()


def render_html_to_pdf(html_content, out_dir,
                       timeout=BROWSER_PDF_TIMEOUT_SECONDS):
    """统一打印 HTML → PDF 字节落盘，返回 pdf 路径（调用方负责清理目录）。"""
    try:
        return html_pdf.render_html_to_pdf(html_content, out_dir,
                                           timeout=timeout)
    except html_pdf.HtmlPdfConversionError as e:
        raise PdfConversionError(str(e))
