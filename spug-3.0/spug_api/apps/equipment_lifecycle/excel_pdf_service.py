# Copyright: (c) OpenSpug Organization. https://github.com/openspug
# Released under the AGPL-3.0 License.
"""设备全生命周期——Excel 台账 LibreOffice headless PDF 转换（2026-09-28）。

由验证原型 apps/ledger_prototype/pdf_service.py 提取的稳定实现（正式路线
唯一转换服务，原型经兼容外壳委托到本模块）：

- 环境检测：soffice / libreoffice 任一在 PATH 即视为可用；
- 不可用时抛 PdfConversionError，调用方返回明确业务错误，
  绝不返回伪造的 PDF 成功结果；
- 转换使用独立 UserInstallation 配置目录，避免并发转换互相锁 profile；
- 输出文件缺失或空文件均视为失败；
- detector 参数用于注入环境检测函数（原型外壳由此保持既有测试补丁
  目标不变），缺省使用本模块检测。

部署依赖（PDF 转换前提，生产镜像/测试容器需一并安装）：
- libreoffice-calc（headless 转换引擎）；
- 中文字体（如 fonts-noto-cjk）：未安装时中文渲染为方框/替换字体，
  不产生报错，模板详情兼容性检查会提示 LibreOffice 可用性；
- 转换超时默认 120 秒（CONVERT_TIMEOUT_SECONDS）。

高保真引擎扩展位：settings.EXCEL_PDF_ENGINE（缺省/当前唯一支持
'libreoffice'；配置为其他值时显式报错，不静默回退）。
"""
import os
import shutil
import subprocess

from django.conf import settings


class PdfConversionError(Exception):
    """PDF 转换失败（环境不可用 / 转换出错 / 输出为空）。"""


CONVERT_TIMEOUT_SECONDS = 120


def configured_engine():
    return getattr(settings, 'EXCEL_PDF_ENGINE', None) or 'libreoffice'


def detect_soffice():
    return shutil.which('soffice') or shutil.which('libreoffice')


def convert_xlsx_to_pdf(xlsx_path, out_dir, timeout=CONVERT_TIMEOUT_SECONDS, detector=None):
    """把 xlsx 转换为同目录同名 pdf，返回 pdf 路径。"""
    engine = configured_engine()
    if engine != 'libreoffice':
        raise PdfConversionError(
            'EXCEL_PDF_ENGINE=%s 暂未接入，当前仅支持 libreoffice' % engine)
    soffice = (detector or detect_soffice)()
    if not soffice:
        raise PdfConversionError(
            'LibreOffice 不可用，无法生成 PDF（请在部署环境中安装 libreoffice-calc）')
    profile_dir = os.path.join(out_dir, 'lo_profile')
    os.makedirs(profile_dir, exist_ok=True)
    command = [
        soffice, '--headless', '--norestore', '--nolockcheck', '--nodefault',
        '-env:UserInstallation=file://%s' % profile_dir,
        '--convert-to', 'pdf', '--outdir', out_dir, str(xlsx_path),
    ]
    env = dict(os.environ, HOME=out_dir)
    try:
        process = subprocess.run(
            command, capture_output=True, timeout=timeout, env=env)
    except subprocess.TimeoutExpired:
        raise PdfConversionError('PDF 转换超时（%d 秒）' % timeout)
    pdf_path = os.path.join(
        out_dir,
        os.path.splitext(os.path.basename(xlsx_path))[0] + '.pdf')
    if not os.path.isfile(pdf_path) or os.path.getsize(pdf_path) == 0:
        detail = (process.stderr or b'').decode('utf-8', 'replace').strip()
        raise PdfConversionError('PDF 转换失败：%s' % (detail[-300:] or '未知错误'))
    return pdf_path
