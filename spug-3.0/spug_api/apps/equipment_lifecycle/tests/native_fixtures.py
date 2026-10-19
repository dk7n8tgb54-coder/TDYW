# -*- coding: utf-8 -*-
"""原生维护台账测试夹具（模板/版本/台账，ORM 直建）。

快照为最小合法 Univer 结构：1 个工作表（首行冻结作重复表头、标题格、
数据行），供模板生命周期与台账流程测试复用。
"""
import json

from apps.equipment_lifecycle.models import (
    LEDGER_FROM_NATIVE,
    OperationLedger,
)
from apps.equipment_lifecycle.native_models import (
    OperationLedgerNativeRecord,
    OperationLedgerNativeTemplate,
    OperationLedgerNativeTemplateVersion,
)


def make_binding(key, label='字段', cell_range='B2', ftype='text',
                 required=False, section='测试'):
    return {
        'id': 'bind-%s' % key,
        'key': key,
        'label': label,
        'section': section,
        'range': cell_range,
        'type': ftype,
        'placeholder': '',
        'is_required': required,
    }


def sample_snapshot(title='原生测试台账', freeze_rows=1):
    """最小快照：第 1 行冻结表头，第 2 行标题，第 3~5 行数据行。"""
    cell_data = {
        '0': {'0': {'v': '表头'}},
        '1': {'0': {'v': title}},
        '2': {'0': {'v': '结论'}, '1': {'v': '底表静态值'}},
        '3': {'0': {'v': '备注'}},
    }
    return {
        'id': 'native-test-snapshot',
        'name': '维护台账',
        'appVersion': '1.1.0',
        'locale': 'zhCN',
        'styles': {},
        'sheetOrder': ['ledger'],
        'sheets': {
            'ledger': {
                'id': 'ledger',
                'name': '维护台账',
                'hidden': 0,
                'freeze': {'xSplit': 0, 'ySplit': freeze_rows,
                           'startRow': freeze_rows, 'startColumn': 0},
                'rowCount': 20,
                'columnCount': 8,
                'zoomRatio': 0.8,
                'defaultColumnWidth': 88,
                'defaultRowHeight': 32,
                'mergeData': [],
                'cellData': cell_data,
                'rowData': {},
                'columnData': {},
                'showGridlines': 0,
            },
        },
    }


def sample_paper(**overrides):
    paper = {
        'size': 'A4',
        'orientation': 'landscape',
        'fitToWidth': True,
        'margins': {'top': 12, 'right': 10, 'bottom': 12, 'left': 10},
    }
    paper.update(overrides)
    return paper


def make_native_template(user, ledger_type='week_month', name='原生测试模板',
                         is_active=True, **kwargs):
    defaults = dict(
        tenant_id=user.tenant_id,
        name=name,
        ledger_type=ledger_type,
        created_by=user,
        is_active=is_active,
    )
    defaults.update(kwargs)
    return OperationLedgerNativeTemplate.objects.create(**defaults)


def make_published_version(template, user, bindings=None, snapshot=None,
                           paper=None, version_no=None, **kwargs):
    """发布版本夹具（ORM 直建，发布级校验由服务层测试另行覆盖）。"""
    if version_no is None:
        version_no = OperationLedgerNativeTemplateVersion.objects.filter(
            template_id=template.id).count() + 1
    bindings = [make_binding('field_a')] if bindings is None else bindings
    defaults = dict(
        tenant_id=user.tenant_id,
        template=template,
        version_no=version_no,
        template_name_snapshot=template.name,
        snapshot=json.dumps(snapshot or sample_snapshot(), ensure_ascii=False),
        bindings=json.dumps(bindings, ensure_ascii=False),
        paper=json.dumps(paper or sample_paper(), ensure_ascii=False),
        field_count=len(bindings) if isinstance(bindings, list) else 1,
        published_by=user,
    )
    defaults.update(kwargs)
    return OperationLedgerNativeTemplateVersion.objects.create(**defaults)


def make_native_ledger(user, version, status='draft', values=None, **kwargs):
    """原生路线台账夹具（表头 + 填写记录；编号手动给定避免依赖生成器）。"""
    from itertools import count

    if not hasattr(make_native_ledger, '_seq'):
        make_native_ledger._seq = count(1)
    seq = next(make_native_ledger._seq)
    prefix = {'week_month': 'EL-WM', 'seasonal': 'EL-SE'}[version.template.ledger_type]
    defaults = dict(
        tenant_id=user.tenant_id,
        ledger_no='%s-20261018-%04d' % (prefix, seq),
        ledger_type=version.template.ledger_type,
        status=status,
        created_from=LEDGER_FROM_NATIVE,
        created_by=user,
    )
    defaults.update(kwargs)
    ledger = OperationLedger.objects.create(**defaults)
    OperationLedgerNativeRecord.objects.create(
        tenant_id=user.tenant_id,
        ledger=ledger,
        version=version,
        values=json.dumps(values or {}, ensure_ascii=False),
    )
    return ledger
