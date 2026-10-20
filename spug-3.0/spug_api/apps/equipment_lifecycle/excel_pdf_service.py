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
import io
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


def merge_pdf_bytes(pdf_contents):
    """按给定顺序合并多份 PDF 字节，返回合并后的 PDF 字节。

    批量导出用（模板组"导出本模板台账"）：逐页原样并入（pypdf），不缩放、
    不重排，各份 PDF 的纸张尺寸、方向、边距与分页全部保留。pypdf 延迟
    导入：组件缺失时抛 PdfConversionError，不影响既有单条转换链路。
    """
    if not pdf_contents:
        raise PdfConversionError('没有可合并的 PDF 内容')
    try:
        from pypdf import PdfReader, PdfWriter
    except ImportError:
        raise PdfConversionError('PDF 合并组件 pypdf 不可用（请在部署环境安装 pypdf）')
    writer = PdfWriter()
    for index, content in enumerate(pdf_contents):
        try:
            for page in PdfReader(io.BytesIO(content)).pages:
                writer.add_page(page)
        except Exception as e:
            raise PdfConversionError('第 %d 份 PDF 读取失败：%s' % (index + 1, e))
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


# 已知纸张物理尺寸 mm（纵向：宽, 高）；第 1 页尺寸匹配容差
_PAPER_MM = {
    'A4': (210, 297), 'A3': (297, 420), 'A5': (148, 210),
    'B4': (257, 364), 'B5': (176, 250),
    'letter': (216, 279), 'legal': (216, 356),
}
_PAPER_MATCH_TOLERANCE_MM = 2


def pdf_page_info(pdf_content):
    """读取真实生成的 PDF 的页数与第 1 页纸张尺寸（预览反馈用）。

    返回 {'pages': int|None, 'paper': 文本|None}；paper 形如
    'A4 210x297mm'（label 按第 1 页宽高匹配已知纸张，±2mm，未匹配只给
    尺寸）。pypdf 缺失或解析失败返回 None 值（预览本身不受影响，反馈
    缺失优于伪造）。多工作表可能混排页面尺寸，此处以第 1 页为准。
    """
    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(pdf_content))
        pages = len(reader.pages)
        box = reader.pages[0].mediabox
        width_mm = round(float(box.width) * 25.4 / 72)
        height_mm = round(float(box.height) * 25.4 / 72)
    except Exception:
        return {'pages': None, 'paper': None}
    label = ''
    for name, (w, h) in _PAPER_MM.items():
        if (abs(width_mm - w) <= _PAPER_MATCH_TOLERANCE_MM
                and abs(height_mm - h) <= _PAPER_MATCH_TOLERANCE_MM):
            label = name
            break
        # 横向输出（宽高互换）同样按纸张名匹配
        if (abs(width_mm - h) <= _PAPER_MATCH_TOLERANCE_MM
                and abs(height_mm - w) <= _PAPER_MATCH_TOLERANCE_MM):
            label = name
            break
    paper = '%s %dx%dmm' % (label, width_mm, height_mm) if label \
        else '%dx%dmm' % (width_mm, height_mm)
    return {'pages': pages, 'paper': paper}
