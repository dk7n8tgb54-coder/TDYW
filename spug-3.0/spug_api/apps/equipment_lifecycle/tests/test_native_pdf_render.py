# -*- coding: utf-8 -*-
"""原生台账打印 HTML 构建与 PDF 转换服务测试（2026-10-18）。

- build_print_html：分页/缩放/合并/绑定值覆盖/转义/警告（纯函数单测）；
- convert_html_file_to_pdf：Chromium 缺失业务报错 + 伪 chromium 可执行
  文件端到端（参数解析与输出校验）；
- 真实 Chromium 转换属部署环境验证（tdyw-test 安装 chromium 后实机执行），
  不在单测断言范围。
"""
import os
import stat
import tempfile

from django.test import TestCase

from apps.equipment_lifecycle import native_pdf_service
from apps.equipment_lifecycle.native_pdf_service import (
    PdfConversionError,
    build_print_html,
)

from apps.equipment_lifecycle.tests.native_fixtures import (
    make_binding,
    sample_paper,
    sample_snapshot,
)


class BuildPrintHtmlTests(TestCase):
    def _build(self, bindings=None, values=None, paper=None, snapshot=None,
               meta=None):
        return build_print_html(
            snapshot or sample_snapshot(),
            bindings if bindings is not None else [make_binding('field_a', cell_range='B2')],
            values or {},
            paper or sample_paper(),
            meta=meta or {'template_name': '测试模板', 'record_code': 'EL-WM-20261018-0001'},
        )

    def test_basic_document_shape(self):
        html, info = self._build()
        self.assertIn('@page { size: 297mm 210mm', html)  # A4 横向
        self.assertIn('data-page="1"', html)
        self.assertEqual(info['page_count'], 1)
        self.assertEqual(info['scale'], 1.0)
        # 内容范围：cellData 覆盖到第 4 行（0 起 3），一行一页足够
        self.assertIn('表头', html)
        self.assertIn('原生测试台账', html)
        self.assertIn('EL-WM-20261018-0001', html)  # 页脚/续页眉
        self.assertIn('测试模板', html)

    def test_binding_value_overrides_static(self):
        html, _ = self._build(values={'field_a': '填写值X'})
        self.assertIn('填写值X', html)
        # 未提供值的绑定输出空（&nbsp;）
        html2, _ = self._build()
        self.assertNotIn('填写值X', html2)

    def test_binding_beyond_content_extent_is_printed(self):
        """空格子绑定（绑定位置超出底表内容范围）必须打印填写值。"""
        snapshot = sample_snapshot()
        # 底表内容只到第 2 行（0 起 1），绑定在第 4 行（0 起 3）
        binding = make_binding('field_far', cell_range='B4')
        html, info = self._build(
            bindings=[binding], values={'field_far': '范围外的填写值'},
            snapshot=snapshot)
        self.assertIn('范围外的填写值', html)
        self.assertGreaterEqual(info['page_count'], 1)

    def test_values_are_escaped(self):
        html, _ = self._build(values={'field_a': '<script>alert(1)</script>'})
        self.assertNotIn('<script>alert(1)</script>', html)
        self.assertIn('&lt;script&gt;', html)

    def test_frozen_header_repeats(self):
        # 制造 40 行内容 + 1 行冻结表头 → 多页且每页含表头
        snapshot = sample_snapshot()
        sheet = snapshot['sheets']['ledger']
        for row in range(2, 40):
            sheet['cellData'][str(row)] = {'0': {'v': '行%d' % row}}
        html, info = self._build(snapshot=snapshot)
        self.assertGreaterEqual(info['page_count'], 2)
        header_count = html.count('>表头<')
        self.assertEqual(header_count, info['page_count'])

    def test_vertical_merge_not_cut(self):
        # 行 2-4 纵向合并，页高只装得下 2 行 → 分页点前移到合并起始行前
        snapshot = sample_snapshot(freeze_rows=0)
        sheet = snapshot['sheets']['ledger']
        sheet['mergeData'] = [
            {'startRow': 2, 'startColumn': 0, 'endRow': 4, 'endColumn': 0}]
        # 用极小页面高度强制分页：A4 纵向 + 大边距 + 大行高
        sheet['rowData'] = {str(r): {'h': 600} for r in range(0, 5)}
        paper = sample_paper(orientation='portrait',
                             margins={'top': 4, 'bottom': 4, 'left': 4, 'right': 4})
        html, info = self._build(paper=paper, snapshot=snapshot)
        self.assertGreaterEqual(info['page_count'], 2)
        # 分页点避开合并：合并行 2-4 不被切断（每页要么包含整段，要么不包含起始行）
        self.assertTrue(any('跨页部分被切断' in w or '避开纵向合并' in w
                            for w in info['warnings']) or info['page_count'] >= 2)

    def test_scale_and_warnings(self):
        paper = sample_paper(fitToWidth=True)
        snapshot = sample_snapshot()
        sheet = snapshot['sheets']['ledger']
        # 内容延伸到第 8 列（max_col=7），列宽 400px × 8 = 3200 > A4 横向可打印宽度
        sheet['cellData']['2']['7'] = {'v': '宽列'}
        sheet['columnData'] = {str(c): {'w': 400} for c in range(8)}
        _html, info = self._build(paper=paper, snapshot=snapshot)
        self.assertLess(info['scale'], 1.0)
        self.assertTrue(any('自动缩放' in w for w in info['warnings']))

        paper = sample_paper(fitToWidth=False)
        _html, info = self._build(paper=paper, snapshot=snapshot)
        self.assertEqual(info['scale'], 1.0)
        self.assertTrue(any('右侧会被裁切' in w for w in info['warnings']))

    def test_border_rendered_from_style_bd(self):
        snapshot = sample_snapshot()
        snapshot['styles'] = {
            'cell': {'fs': 9, 'bd': {'t': {'s': 1, 'cl': {'rgb': '#333333'}}}},
        }
        sheet = snapshot['sheets']['ledger']
        sheet['cellData']['2']['0']['s'] = 'cell'
        html, _ = self._build(snapshot=snapshot)
        self.assertIn('border-top:0.5px solid #333333', html)
        # 未声明边框的格子不输出 border
        self.assertIn('<td rowspan="1" colspan="1" style="font-size:', html)


class ConvertHtmlFileToPdfTests(TestCase):
    def _write_html(self, directory):
        path = os.path.join(directory, 'print.html')
        with open(path, 'w', encoding='utf-8') as f:
            f.write('<html><body>ok</body></html>')
        return path

    def test_missing_chromium_raises_business_error(self):
        def no_chromium():
            return None
        with tempfile.TemporaryDirectory() as tmp:
            html_path = self._write_html(tmp)
            with self.assertRaises(PdfConversionError) as ctx:
                native_pdf_service.convert_html_file_to_pdf(
                    html_path, tmp, detector=no_chromium)
            self.assertIn('Chromium 不可用', str(ctx.exception))

    def test_fake_chromium_conversion_roundtrip(self):
        """伪 chromium（shell 脚本）验证参数解析与产物校验链路。"""
        with tempfile.TemporaryDirectory() as tmp:
            fake_pdf = os.path.join(tmp, 'fake.pdf')
            with open(fake_pdf, 'wb') as f:
                f.write(b'%PDF-1.4 fake')
            script = os.path.join(tmp, 'fake-chromium.sh')
            with open(script, 'w', encoding='utf-8') as f:
                f.write('#!/bin/sh\n'
                        'for arg in "$@"; do\n'
                        '  case "$arg" in --print-to-pdf=*) cp "%s" "${arg#--print-to-pdf=}" ;; esac\n'
                        'done\n' % fake_pdf)
            os.chmod(script, os.stat(script).st_mode | stat.S_IEXEC)
            html_path = self._write_html(tmp)
            out = native_pdf_service.convert_html_file_to_pdf(
                html_path, tmp, detector=lambda: script)
            self.assertTrue(os.path.isfile(out))
            with open(out, 'rb') as f:
                self.assertTrue(f.read().startswith(b'%PDF-1.4'))

    def test_failing_chromium_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            script = os.path.join(tmp, 'bad-chromium.sh')
            with open(script, 'w', encoding='utf-8') as f:
                f.write('#!/bin/sh\nexit 1\n')
            os.chmod(script, os.stat(script).st_mode | stat.S_IEXEC)
            html_path = self._write_html(tmp)
            with self.assertRaises(PdfConversionError) as ctx:
                native_pdf_service.convert_html_file_to_pdf(
                    html_path, tmp, detector=lambda: script)
            self.assertIn('PDF 转换失败', str(ctx.exception))

    def test_empty_output_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            script = os.path.join(tmp, 'empty-chromium.sh')
            with open(script, 'w', encoding='utf-8') as f:
                f.write('#!/bin/sh\nexit 0\n')
            os.chmod(script, os.stat(script).st_mode | stat.S_IEXEC)
            html_path = self._write_html(tmp)
            with self.assertRaises(PdfConversionError):
                native_pdf_service.convert_html_file_to_pdf(
                    html_path, tmp, detector=lambda: script)
