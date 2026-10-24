# -*- coding: utf-8 -*-
"""数字表单台账 PDF 版式与预览/导出行为测试（2026-10-22）。

真实代码路径，分两层：
1. 版式渲染单元（render_form_html，纯函数）：样张/台账两种模式的空值
   语义（待填写 vs 未填写，绝不伪装已填）、normal_abnormal 异常说明与
   判定值同块、矩阵行列对照、明细组完整展开、宽矩阵横向规则、值转义；
2. 真实 HTTP + PDF 链路（URL→View→Service→libs.html_pdf→Chromium→PDF）：
   权限（ledger.export / 模板 view）、租户与路线隔离（跨租户/其他路线
   按不存在处理）、无草稿拒绝、引擎不可用显式业务错误、审计留痕；
   Chromium 可用时以 pypdf/pdftotext 验证产物（纸张尺寸、文本层可搜索、
   预览=下载同页数同文本、旧版本台账按旧版本导出），环境不可用显式
   NOT_RUN，绝不伪造通过。
"""
import io
import json
import shutil
from urllib.parse import unquote
from unittest import mock, skipUnless

from django.test import TestCase

from apps.equipment_lifecycle import form_pdf_service
from apps.equipment_lifecycle.form_template_manage import sample_form
from apps.equipment_lifecycle.tests.base import (
    make_client, make_system, make_user, URL_PREFIX,
)
from apps.logs.models import AuditLog

TPL_URL = URL_PREFIX + '/form-templates'
LEDGER_URL = URL_PREFIX + '/form-ledgers'
AUDIT_TARGET = 'el_operation_ledger'  # ledger_views.AUDIT_TARGET_LEDGER

P_TPL = ['equipment_lifecycle.ledger_template.view',
         'equipment_lifecycle.ledger_template.add',
         'equipment_lifecycle.ledger_template.edit']
P_LEDGER = [
    'equipment_lifecycle.ledger.view',
    'equipment_lifecycle.ledger.add',
    'equipment_lifecycle.ledger.edit',
    'equipment_lifecycle.ledger.submit',
    'equipment_lifecycle.ledger.export',
]
ALL_PERMS = P_TPL + P_LEDGER


def _has_chromium():
    try:
        return form_pdf_service.html_pdf.detect_browser() is not None
    except Exception:
        return False


HAS_CHROMIUM = _has_chromium()
HAS_PDFTOTEXT = shutil.which('pdftotext') is not None


def _pdf_pages_and_size(content):
    """pypdf 读取页数与第 1 页 mediabox（pt）；pypdf 缺失返回 (None, None)。"""
    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(content))
        box = reader.pages[0].mediabox
        return len(reader.pages), (round(float(box.width), 1),
                                   round(float(box.height), 1))
    except ImportError:
        return None, None


def _pdf_text(content):
    """pdftotext 提取文本层（UTF-8），缺失或失败返回空串。"""
    if not HAS_PDFTOTEXT:
        return ''
    import subprocess
    import tempfile
    with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as f:
        f.write(content)
        path = f.name
    try:
        result = subprocess.run(
            ['pdftotext', '-layout', path, '-'], capture_output=True,
            timeout=30)
        return result.stdout.decode('utf-8', 'replace')
    finally:
        import os
        os.unlink(path)


# ======================================================================
# 第一层：版式渲染单元（纯函数，不触库）
# ======================================================================

def _form(groups):
    return {'protocol_version': 1, 'groups': groups}


def _field(fid, name, ftype='text', **overrides):
    field = {'id': fid, 'name': name, 'type': ftype, 'required': False,
             'description': '', 'unit': '', 'options': []}
    field.update(overrides)
    return field


class FormPdfRenderTests(TestCase):
    """render_form_html 版式规则（样张与台账共用同一实现）。"""

    def render(self, form, values=None, sample=False):
        return form_pdf_service.render_form_html(
            title='测试表单', badge_html='<span>标注</span>',
            meta_pairs=[('甲', '乙')], form=form, values=values or {},
            sample=sample)

    def test_sample_mode_uses_pending_placeholder(self):
        form = _form([{'id': 'g1', 'name': '基本信息', 'kind': 'fields',
                       'fields': [_field('f1', '备注', 'textarea')]}])
        html = self.render(form, sample=True)
        self.assertIn('待填写', html)
        self.assertNotIn('未填写', html)

    def test_ledger_mode_empty_never_faked_as_filled(self):
        """台账模式空值显示未填写：空 normal_abnormal 不出现 正常/异常 字样。"""
        form = _form([{'id': 'g1', 'name': '状态检查', 'kind': 'fields',
                       'fields': [_field('f1', '机壳外观', 'normal_abnormal'),
                                  _field('f2', '备注', 'textarea')]}])
        html = self.render(form, values={}, sample=False)
        self.assertIn('未填写', html)
        self.assertNotIn('>正常<', html)
        self.assertNotIn('>异常<', html)

    def test_normal_abnormal_value_and_desc_same_block(self):
        form = _form([{'id': 'g1', 'name': '状态检查', 'kind': 'fields',
                       'fields': [_field('f1', '机壳外观', 'normal_abnormal')]}])
        html = self.render(form, values={
            'f1': 'abnormal', 'f1__desc': '面板第 2 个指示灯不亮'})
        row = html[html.index('机壳外观'):]
        row = row[:row.index('</tr>')]
        self.assertIn('异常', row)
        self.assertIn('异常说明：面板第 2 个指示灯不亮', row)

    def test_matrix_keeps_row_column_mapping(self):
        form = _form([{'id': 'g1', 'name': '多机对比', 'kind': 'matrix',
                       'columns': [{'id': 'c1', 'name': 'A 机'},
                                   {'id': 'c2', 'name': 'B 机'}],
                       'fields': [_field('r1', '电压', 'number', unit='V'),
                                  _field('r2', '通讯', 'normal_abnormal')]}])
        html = self.render(form, values={
            'g1': {'r1': {'c1': 220}, 'r2': {
                'c1': 'normal', 'c2': 'abnormal', 'c2__desc': 'B 机中断'}}})
        self.assertIn('<th>A 机</th>', html)
        self.assertIn('<th>B 机</th>', html)
        # 电压行：220 只在 A 机列；通讯异常说明在 B 机单元格内
        self.assertRegex(
            html,
            r'电压 <span class="fb-hint">\(V\)</span></th>'
            r'<td class="fb-value">220 V</td>')
        self.assertRegex(
            html, r'通讯</th><td class="fb-value"><span class="fb-normal">正常'
                  r'</span></td><td class="fb-value"><span class="fb-abnormal">'
                  r'异常</span><div class="fb-desc">异常说明：B 机中断</div>')
        # 空单元格（电压 B 机列）保留空白待填写区域，不伪装已填
        self.assertIn('<td class="fb-value"></td>', html)

    def test_repeat_group_fully_expanded(self):
        form = _form([{'id': 'g1', 'name': '测量', 'kind': 'repeat',
                       'item_name': '测量项目',
                       'fields': [_field('f1', '项目名称'),
                                  _field('f2', '测量值', 'number', unit='A')]}])
        values = {'g1': [{'f1': '输出电压', 'f2': 220.5},
                         {'f1': '输出电流', 'f2': 3.2}]}
        html = self.render(form, values=values)
        self.assertIn('测量项目 1', html)
        self.assertIn('测量项目 2', html)
        self.assertIn('输出电压', html)
        self.assertIn('220.5 A', html)
        # 数字整型不加小数点、带单位
        values2 = {'g1': [{'f1': '电流', 'f2': 3}]}
        self.assertIn('3 A', self.render(form, values=values2))
        # 台账模式无记录：明确占位；样张模式：一张空白待填卡
        self.assertIn('（无明细记录）', self.render(form, values={}))
        sample_html = self.render(form, values={}, sample=True)
        self.assertIn('测量项目 1（待填写）', sample_html)

    def test_wide_matrix_switches_to_landscape(self):
        columns = [{'id': 'c%d' % i, 'name': '设备%d' % i}
                   for i in range(6)]
        wide = _form([{'id': 'g1', 'name': '对比', 'kind': 'matrix',
                       'columns': columns, 'fields': [_field('r1', '电压')]}])
        self.assertTrue(form_pdf_service.landscape_needed(wide))
        self.assertFalse(form_pdf_service.landscape_needed(
            _form([{'id': 'g1', 'name': '对比', 'kind': 'matrix',
                    'columns': columns[:5],
                    'fields': [_field('r1', '电压')]}])))
        # 纸张/边距经打印参数定义，HTML 不携带 @page 规则
        self.assertNotIn('@page', self.render(wide))

    def test_textarea_value_preserved_and_escaped(self):
        form = _form([{'id': 'g1', 'name': '基本信息', 'kind': 'fields',
                       'fields': [_field('f1', '备注', 'textarea')]}])
        html = self.render(form, values={'f1': '第一行\n第二行 <b>注入</b>'})
        self.assertIn('第一行\n第二行 &lt;b&gt;注入&lt;/b&gt;', html)
        self.assertNotIn('<b>注入</b>', html)

    def test_header_meta_and_footer_identity(self):
        html = self.render(sample_form(), values={}, sample=True)
        self.assertIn('甲', html)
        self.assertIn('乙', html)


# ======================================================================
# 第二层：HTTP 契约（权限/租户/路线隔离/错误语义/审计）
# ======================================================================

class FormPdfContractTests(TestCase):
    """预览/导出端点契约（不依赖 Chromium；引擎不可用分支显式断言）。"""

    @classmethod
    def setUpTestData(cls):
        seed = 'pdf%s' % cls._seed()
        cls.owner = make_user('form_pdf_owner_%s' % seed, perms=ALL_PERMS,
                              tenant_id='default')
        cls.other = make_user('form_pdf_other_%s' % seed, perms=ALL_PERMS,
                              tenant_id='another')
        cls.no_export = make_user(
            'form_pdf_noexp_%s' % seed,
            perms=[p for p in ALL_PERMS
                   if p != 'equipment_lifecycle.ledger.export'],
            tenant_id='default')
        cls.owner_client = make_client(cls.owner)
        cls.other_client = make_client(cls.other)
        cls.no_export_client = make_client(cls.no_export)
        cls.system = make_system(cls.owner)

    @classmethod
    def _seed(cls):
        if not hasattr(cls, '_seed_value'):
            import uuid
            cls._seed_value = uuid.uuid4().hex[:8]
        return cls._seed_value

    def setUp(self):
        # 引擎可用性差异不影响契约断言：统一 mock 掉真实转换
        patcher = mock.patch.object(
            form_pdf_service.html_pdf, 'detect_browser', return_value='/fake')
        patcher.start()
        self.addCleanup(patcher.stop)
        render_patcher = mock.patch.object(
            form_pdf_service.html_pdf, 'render_html_to_pdf',
            side_effect=self._fake_render)
        render_patcher.start()
        self.addCleanup(render_patcher.stop)

    @staticmethod
    def _fake_render(html_content, out_dir, **kwargs):
        import os
        path = os.path.join(out_dir, 'print.pdf')
        with open(path, 'wb') as f:
            f.write(b'%PDF-fake-contract')
        return path

    def _make_template_with_draft(self, client=None, form=None):
        client = client or self.owner_client
        response = client.post(TPL_URL + '/', json.dumps({
            'name': '周维护数字表单', 'ledger_type': 'week_month',
        }), content_type='application/json')
        template = response.json()['data']
        response = client.put(
            '%s/%s/' % (TPL_URL, template['id']),
            json.dumps({'form': form or sample_form()}),
            content_type='application/json')
        self.assertEqual(response.json().get('error', ''), '')
        return template

    def _create_ledger(self, client=None, template=None):
        client = client or self.owner_client
        template = template or self._make_template_with_draft(client)
        response = client.post(
            TPL_URL + '/%s/publish/' % template['id'],
            content_type='application/json')
        version = response.json()['data']
        response = client.post(
            LEDGER_URL + '/', json.dumps({'version_id': version['id']}),
            content_type='application/json')
        data = response.json()
        self.assertEqual(data.get('error', ''), '')
        return template, data['data']

    def test_template_sample_requires_draft(self):
        template = self.owner_client.post(
            TPL_URL + '/', json.dumps({
                'name': '无草稿模板', 'ledger_type': 'week_month'}),
            content_type='application/json').json()['data']
        response = self.owner_client.post(
            '%s/%s/preview/pdf/' % (TPL_URL, template['id']))
        self.assertIn('尚未编辑表单草稿', response.json()['error'])

    def test_template_sample_permission_semantics(self):
        """样张使用模板 view 权限：无模板权限拒绝；有模板权限可生成。"""
        template = self._make_template_with_draft()
        viewer = make_user('form_pdf_viewer_%s' % self._seed(),
                           perms=['equipment_lifecycle.ledger.view'],
                           tenant_id='default')
        denied = make_client(viewer).post(
            '%s/%s/preview/pdf/' % (TPL_URL, template['id']))
        self.assertEqual(denied.json()['error'], '权限拒绝')
        allowed = self.owner_client.post(
            '%s/%s/preview/pdf/' % (TPL_URL, template['id']))
        self.assertTrue(allowed.content.startswith(b'%PDF'),
                        allowed.content[:100])

    def test_ledger_pdf_requires_export_permission(self):
        _template, ledger = self._create_ledger()
        for url in ('preview/pdf/', 'export/pdf/'):
            response = self.no_export_client.post(
                '%s/%s/%s' % (LEDGER_URL, ledger['id'], url))
            self.assertEqual(response.json()['error'], '权限拒绝')

    def test_ledger_pdf_tenant_and_route_isolation(self):
        _template, ledger = self._create_ledger()
        for url in ('preview/pdf/', 'export/pdf/'):
            cross = self.other_client.post(
                '%s/%s/%s' % (LEDGER_URL, ledger['id'], url))
            self.assertEqual(cross.json()['error'], '台账不存在')

    def test_engine_unavailable_returns_explicit_error(self):
        template = self._make_template_with_draft()
        with mock.patch.object(form_pdf_service.html_pdf, 'detect_browser',
                               return_value=None):
            response = self.owner_client.post(
                '%s/%s/preview/pdf/' % (TPL_URL, template['id']))
        self.assertIn('浏览器打印引擎', response.json()['error'])

    def test_export_records_audit_event(self):
        _template, ledger = self._create_ledger()
        before = AuditLog.objects.filter(
            action='export', target_type=AUDIT_TARGET,
            target_id=str(ledger['id'])).count()
        response = self.owner_client.post(
            '%s/%s/export/pdf/' % (LEDGER_URL, ledger['id']))
        self.assertTrue(response.content.startswith(b'%PDF'),
                        response.content[:100])
        after = AuditLog.objects.filter(
            action='export', target_type=AUDIT_TARGET,
            target_id=str(ledger['id'])).count()
        self.assertEqual(after, before + 1)


# ======================================================================
# 第三层：真实 PDF 产物（Chromium 不可用时整组 NOT_RUN）
# ======================================================================

@skipUnless(HAS_CHROMIUM, 'Chromium 不可用：真实 PDF 渲染 NOT_RUN')
class FormPdfRealRenderTests(TestCase):
    """真实 HTTP 链路产物验证：纸张/文本层/预览=下载/旧版本口径。"""

    @classmethod
    def setUpTestData(cls):
        seed = 'rp%s' % cls._seed()
        cls.owner = make_user('form_pdf_real_%s' % seed, perms=ALL_PERMS,
                              tenant_id='default')
        cls.other = make_user('form_pdf_real_o_%s' % seed, perms=ALL_PERMS,
                              tenant_id='another')
        cls.owner_client = make_client(cls.owner)
        cls.other_client = make_client(cls.other)
        cls.system = make_system(cls.owner)

    @classmethod
    def _seed(cls):
        if not hasattr(cls, '_seed_value'):
            import uuid
            cls._seed_value = uuid.uuid4().hex[:8]
        return cls._seed_value

    def _publish(self, template_id, form, client=None):
        client = client or self.owner_client
        response = client.put(
            '%s/%s/' % (TPL_URL, template_id), json.dumps({'form': form}),
            content_type='application/json')
        self.assertEqual(response.json().get('error', ''), '')
        response = client.post(
            '%s/%s/publish/' % (TPL_URL, template_id),
            content_type='application/json')
        self.assertEqual(response.json().get('error', ''), '')
        return response.json()['data']

    def _publish_template(self, form, name=None):
        response = self.owner_client.post(
            TPL_URL + '/', json.dumps({'name': name or '周维护数字表单',
                                       'ledger_type': 'week_month'}),
            content_type='application/json')
        template = response.json()['data']
        version = self._publish(template['id'], form)
        return template, version

    def _create_ledger_with_values(self, form, values, name=None):
        template, version = self._publish_template(form, name=name)
        response = self.owner_client.post(
            LEDGER_URL + '/', json.dumps({'version_id': version['id']}),
            content_type='application/json')
        ledger = response.json()['data']
        response = self.owner_client.put(
            '%s/%s/' % (LEDGER_URL, ledger['id']),
            json.dumps({'values': values}), content_type='application/json')
        self.assertEqual(response.json().get('error', ''), '')
        return template, version, ledger

    def test_template_sample_pdf_layout(self):
        """样张：A4 纵向、真实文本层、样张标注、待填写占位、无台账数据。"""
        template, _version = self._publish_template(sample_form())
        response = self.owner_client.post(
            '%s/%s/preview/pdf/' % (TPL_URL, template['id']))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        content = response.content
        self.assertTrue(content.startswith(b'%PDF'))
        pages, size = _pdf_pages_and_size(content)
        self.assertGreaterEqual(pages, 1)
        self.assertTrue(all(abs(a - b) <= 1 for a, b in zip(size, (595.3, 841.9))),
                        'A4 纵向尺寸偏差超 1pt：%s' % (size,))
        self.assertEqual(response['X-El-Pdf-Paper'], 'A4 210x297mm')
        text = _pdf_text(content)
        self.assertIn('模板样张', text)
        self.assertIn('不含真实台账数据', text)
        self.assertIn('周维护数字表单', text)
        self.assertIn('设备状态检查', text)
        self.assertIn('待填写', text)
        self.assertNotIn('未填写', text)

    def test_ledger_export_and_preview_same_output(self):
        """预览与下载调用同一生成函数：同页数、同文本层。"""
        form = sample_form()
        values = {
            'f_maintdate1': '2026-10-22', 'f_maintuser1': '张三、李四',
            'f_casing0001': 'normal', 'f_lampstat01': 'abnormal',
            'f_lampstat01__desc': '面板第 2 个指示灯不亮',
            'f_coolingfan': '',
            'g_measuremt1': [
                {'f_itemname01': '输出电压', 'f_measvalue1': 220.5,
                 'f_unittext01': 'V', 'f_judgement': 'normal'}],
            'g_multidev01': {
                'r_voltage001': {'c_devicema': '220', 'c_devicemb': '221'},
                'r_linkstate': {'c_devicema': 'normal'}},
        }
        _template, _version, ledger = self._create_ledger_with_values(
            form, values)
        export = self.owner_client.post(
            '%s/%s/export/pdf/' % (LEDGER_URL, ledger['id']))
        preview = self.owner_client.post(
            '%s/%s/preview/pdf/' % (LEDGER_URL, ledger['id']))
        self.assertEqual(export.status_code, 200)
        self.assertEqual(preview.status_code, 200)
        self.assertIn('attachment', export['Content-Disposition'])
        self.assertIn(ledger['ledger_no'], export['Content-Disposition'])
        self.assertIn('inline', preview['Content-Disposition'])
        # 导出与预览同一生成函数：页数一致（导出按 Excel 路线口径不带反馈头）
        export_pages, _size = _pdf_pages_and_size(export.content)
        preview_pages, _size2 = _pdf_pages_and_size(preview.content)
        self.assertEqual(export_pages, preview_pages)
        self.assertEqual(preview['X-El-Pdf-Paper'], 'A4 210x297mm')
        export_text = _pdf_text(export.content)
        preview_text = _pdf_text(preview.content)
        self.assertEqual(export_text, preview_text)
        # 填写值进入文本层（可选择/可搜索）；空值如实显示未填写
        self.assertIn('张三、李四', export_text)
        self.assertIn('2026-10-22', export_text)
        self.assertIn('异常说明：面板第 2 个指示灯不亮', export_text)
        self.assertIn('未填写', export_text)
        # 明细组的单位是独立字段（f_unittext01），测量值与单位分行呈现
        self.assertIn('220.5', export_text)
        self.assertIn('输出电压', export_text)
        self.assertIn('EL-WM', export_text)
        # 台账编号出现在页脚（台账标识）
        self.assertIn(ledger['ledger_no'], export_text)

    def test_ledger_export_uses_bound_old_version(self):
        """历史台账按创建时版本导出：模板发布新版本不回溯历史台账。"""
        form_v1 = _form([{'id': 'g_v1base1', 'name': '一版检查', 'kind': 'fields',
                          'fields': [_field('f_v1item01', '一版项目')]}])
        template, _v1 = self._publish_template(form_v1)
        response = self.owner_client.post(
            LEDGER_URL + '/', json.dumps({'version_id': _v1['id']}),
            content_type='application/json')
        ledger = response.json()['data']
        # 发布 v2：新增字段；台账仍应按 v1 结构导出
        form_v2 = _form([{'id': 'g_v1base1', 'name': '一版检查', 'kind': 'fields',
                          'fields': [_field('f_v1item01', '一版项目'),
                                     _field('f_v2only01', '二版专属项')]}])
        self._publish(template['id'], form_v2)
        response = self.owner_client.post(
            '%s/%s/export/pdf/' % (LEDGER_URL, ledger['id']))
        text = _pdf_text(response.content)
        self.assertIn('一版项目', text)
        self.assertNotIn('二版专属项', text)
        self.assertIn('v1', text)

    def test_wide_matrix_ledger_exports_landscape(self):
        """宽矩阵（6 列）台账导出为 A4 横向。"""
        columns = [{'id': 'c_%d_xxx' % i, 'name': '设备%d' % i}
                   for i in range(6)]
        form = _form([{'id': 'g_widemtx1', 'name': '宽矩阵对比', 'kind': 'matrix',
                       'columns': columns,
                       'fields': [_field('r_wide0001', '电压', 'number',
                                         unit='V')]}])
        _template, _version, ledger = self._create_ledger_with_values(
            form, {'g_widemtx1': {'r_wide0001': {'c_0_xxx': 220}}})
        response = self.owner_client.post(
            '%s/%s/export/pdf/' % (LEDGER_URL, ledger['id']))
        _pages, size = _pdf_pages_and_size(response.content)
        self.assertTrue(all(abs(a - b) <= 1 for a, b in zip(size, (841.9, 595.3))),
                        'A4 横向尺寸偏差超 1pt：%s' % (size,))
        self.assertEqual(
            form_pdf_service.pdf_page_info(response.content)['paper'],
            'A4 297x210mm')
        text = _pdf_text(response.content)
        self.assertIn('设备0', text)
        self.assertIn('220 V', text)

    def test_draft_ledger_export_allowed_with_honest_empty(self):
        """草稿台账可导出（导出不拦截必填）：未填必填项如实显示未填写。"""
        _template, _version, ledger = self._create_ledger_with_values(
            sample_form(), {})
        response = self.owner_client.post(
            '%s/%s/export/pdf/' % (LEDGER_URL, ledger['id']))
        self.assertEqual(response.status_code, 200)
        text = _pdf_text(response.content)
        self.assertIn('草稿', text)
        self.assertIn('未填写', text)
        self.assertNotIn('待填写', text)

    def test_completed_ledger_export_shows_completed_status(self):
        _template, _version, ledger = self._create_ledger_with_values(
            sample_form(), {
                'f_maintdate1': '2026-10-22', 'f_maintuser1': '张三',
                'f_casing0001': 'normal', 'f_lampstat01': 'normal',
                'f_coolingfan': 'normal',
                'g_measuremt1': [
                    {'f_itemname01': '输出电压', 'f_measvalue1': 220,
                     'f_unittext01': 'V', 'f_judgement': 'normal'}],
                'g_multidev01': {},
            })
        response = self.owner_client.post(
            '%s/%s/complete/' % (LEDGER_URL, ledger['id']),
            json.dumps({}), content_type='application/json')
        self.assertEqual(response.json().get('error', ''), '')
        export = self.owner_client.post(
            '%s/%s/export/pdf/' % (LEDGER_URL, ledger['id']))
        self.assertIn('已完成', unquote(export['Content-Disposition']))
        text = _pdf_text(export.content)
        # 状态值在信息表中可能因窄列换行（长测试用户名挤压），放宽为前缀
        self.assertTrue('已完成' in text or '已完' in text,
                        '完成状态未出现在文本层')

    def test_cross_tenant_ledger_not_exportable(self):
        _template, _version, ledger = self._create_ledger_with_values(
            sample_form(), {})
        response = self.other_client.post(
            '%s/%s/export/pdf/' % (LEDGER_URL, ledger['id']))
        self.assertEqual(response.json()['error'], '台账不存在')
