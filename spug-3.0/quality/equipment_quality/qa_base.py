# -*- coding: utf-8 -*-
"""设备管理质量专项测试公共夹具（quality/equipment_quality）。

复用既有业务测试夹具（apps.equipment_lifecycle.tests.base /
stable_contract.ledger_base），不复制业务逻辑；
所有断言走真实 HTTP（Django test Client）+ 数据库状态断言。
"""
import json
import os
import shutil
import tempfile
import uuid

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings

from apps.equipment_lifecycle.excel_sample_template import (
    build_acceptance_sample_xlsx,
)
from apps.equipment_lifecycle.tests.base import (  # noqa: F401
    ALL_OPERATION_PERMS, ALL_SYSTEM_PERMS, P_OP_ADD, P_OP_ADD_FAULT,
    P_OP_DEL, P_OP_EDIT, P_OP_EXPORT, P_OP_PROGRESS, P_OP_VIEW,
    P_SYS_ADD, P_SYS_DEACT, P_SYS_DEL, P_SYS_EDIT, P_SYS_EXPORT, P_SYS_VIEW,
    RECORDS_URL, URL_PREFIX, make_client, make_record, make_system,
    make_user, system_payload,
)
from apps.equipment_lifecycle.tests.stable_contract.ledger_base import (  # noqa: F401
    ALL_LEDGER_PERMS, ALL_TEMPLATE_PERMS, LEDGER_URL, P_LED_ADD, P_LED_DEL,
    P_LED_EDIT, P_LED_EXPORT, P_LED_SUBMIT, P_LED_VIEW,
    P_TPL_ADD, P_TPL_DEL, P_TPL_EDIT, P_TPL_VIEW, create_ledger_ok,
    entry_payload, item_payload, ledger_payload, post_json, put_json,
)

TPL_URL = URL_PREFIX + '/excel-templates'
EXCEL_LEDGER_URL = URL_PREFIX + '/excel-ledgers'
GENERATE_URL = URL_PREFIX + '/ledgers/period-generate/'
SYSTEMS_URL = URL_PREFIX + '/systems'
CANDIDATES_URL = URL_PREFIX + '/records/candidate-systems/'
UPGRADE_URL = '/upgrade'

UPGRADE_ALL = ['upgrade.upgrade.view', 'upgrade.upgrade.add',
               'upgrade.upgrade.edit', 'upgrade.upgrade.del']

# 升级类型枚举（views/record/create.py 校验：功能升级/Bug修复/安全补丁/性能优化）
UPGRADE_TYPE = '功能升级'

# 残留数据的隔离测试库中不存在的主键（自增远达不到该量级）
NONEXISTENT_ID = 99999999


def uniq(prefix):
    return '%s_%s' % (prefix, uuid.uuid4().hex[:8])


class IsoStorageMixin:
    """把 Excel 模板存储与附件 MEDIA_ROOT 隔离到临时目录，测试结束清理。

    模板存储布局为 {EL_EXCEL_TEMPLATE_BASE_DIR}/{template_id}/...（draft 与
    v{N} 版本同目录），因此"文件缺失"场景直接按目录删除物理文件即可。
    """

    def setUp(self):
        super().setUp()
        self._storage_dir = tempfile.mkdtemp(prefix='el_qa_storage_')
        self._media_dir = tempfile.mkdtemp(prefix='el_qa_media_')
        self._storage_override = override_settings(
            EL_EXCEL_TEMPLATE_BASE_DIR=self._storage_dir,
            MEDIA_ROOT=self._media_dir,
        )
        self._storage_override.enable()
        self.addCleanup(self._storage_override.disable)
        self.addCleanup(shutil.rmtree, self._storage_dir, ignore_errors=True)
        self.addCleanup(shutil.rmtree, self._media_dir, ignore_errors=True)

    def template_files(self, template_id):
        base = os.path.join(self._storage_dir, str(template_id))
        found = []
        if os.path.isdir(base):
            for root, _dirs, files in os.walk(base):
                found.extend(os.path.join(root, name) for name in files)
        return found

    def remove_template_files(self, template_id):
        for path in self.template_files(template_id):
            os.remove(path)

    def media_files(self):
        found = []
        for root, _dirs, files in os.walk(self._media_dir):
            found.extend(os.path.join(root, name) for name in files)
        return found


class ExcelTemplateFlowMixin:
    """Excel 模板全流程 API 夹具（上传→绑定→发布→生成配置→Excel 台账）。"""

    def make_binding(self, coordinate, field_name, sheet_name='信道维护记录'):
        return {
            'field_id': str(uuid.uuid4()), 'sheet_name': sheet_name,
            'cell_coordinate': coordinate, 'field_name': field_name,
            'input_type': 'text', 'is_required': True, 'unit': '',
            'options': [],
        }

    def upload_template(self, client=None, name=None, ledger_type='week_month'):
        client = client or self.client
        response = client.post(TPL_URL + '/', {
            'file': SimpleUploadedFile('channel.xlsx', build_acceptance_sample_xlsx()),
            'name': name or uniq('信道Excel台账'),
            'ledger_type': ledger_type,
        })
        payload = response.json()
        assert not payload.get('error'), payload
        return payload['data']['data']

    def save_bindings(self, template_id, bindings, client=None):
        client = client or self.client
        response = client.put(
            '%s/%s/bindings/' % (TPL_URL, template_id),
            json.dumps({'field_bindings': bindings}),
            content_type='application/json')
        payload = response.json()
        assert not payload.get('error'), payload

    def publish(self, template_id, client=None):
        client = client or self.client
        response = client.post('%s/%s/publish/' % (TPL_URL, template_id))
        payload = response.json()
        assert not payload.get('error'), payload
        return payload['data']['data']

    def set_generation_config(self, template_id, system,
                              generation_period='weekly', client=None):
        client = client or self.client
        response = client.put(
            '%s/%s/generation-config/' % (TPL_URL, template_id),
            json.dumps({'system': system.id,
                        'generation_period': generation_period}),
            content_type='application/json')
        payload = response.json()
        assert not payload.get('error'), payload

    def create_excel_ledger(self, version_id, client=None):
        client = client or self.client
        response = client.post(
            EXCEL_LEDGER_URL + '/',
            json.dumps({'version_id': version_id, 'ledger_type': 'week_month'}),
            content_type='application/json')
        payload = response.json()
        assert not payload.get('error'), payload
        return payload['data']['data']

    def fill_excel_ledger(self, ledger_id, field_ids, value='正常', client=None):
        """填写必填字段（导出/完成前置）。"""
        client = client or self.client
        response = client.put(
            '%s/%s/' % (EXCEL_LEDGER_URL, ledger_id),
            json.dumps({'values': {fid: value for fid in field_ids}}),
            content_type='application/json')
        payload = response.json()
        assert not payload.get('error'), payload
        return payload


def upload_json(client, url, filename, content, extra=None):
    """multipart 文件上传辅助。"""
    data = dict(extra or {})
    data['file'] = SimpleUploadedFile(filename, content)
    return client.post(url, data)


def inner(response):
    """取 json_response 双层包装的业务数据层（payload['data']）。

    项目约定：json_response({'data': [...], 'total': n}) 实际响应为
    {"error": "", "data": {"data": [...], "total": n}}；本助手返回内层
    dict/list，并先行断言无业务错误。
    """
    payload = response.json()
    assert not payload.get('error'), payload
    return payload['data']


def assert_no_500(response, context=''):
    """任何异常/容错场景都不允许 5xx。"""
    assert response.status_code < 500, (
        '%s: HTTP %s\n%s' % (context, response.status_code,
                             response.content[:400]))
