# Copyright: (c) OpenSpug Organization. https://github.com/openspug
# Released under the AGPL-3.0 License.
"""设备全生命周期——Excel 模板源文件存储（2026-09-28）。

边界与不变量：
- 目录布局：<base>/<template_id>/draft.xlsx 与 <base>/<template_id>/v<no>.xlsx，
  路径一律由模板主键（整数）与版本号派生，不接收外部路径；
- template_id 必须是正整数才允许拼接路径（fail-closed 防穿越）；
- 存储根目录默认 MEDIA_ROOT/excel_ledger_templates，测试可经
  override_settings(EL_EXCEL_TEMPLATE_BASE_DIR=...) 隔离；
- 草稿文件可覆盖（重新上传即替换），版本文件发布时一次性写入，之后只读；
- 写入顺序遵循项目规则：先写物理文件，成功后再写数据库记录。
"""
import os
import re
import shutil

from django.conf import settings

DRAFT_FILE_NAME = 'draft.xlsx'
_VERSION_FILE_PATTERN = re.compile(r'^v(\d+)\.xlsx$')


def base_dir():
    custom = getattr(settings, 'EL_EXCEL_TEMPLATE_BASE_DIR', '')
    return custom or os.path.join(settings.MEDIA_ROOT, 'excel_ledger_templates')


def _validate_template_id(template_id):
    if not isinstance(template_id, int) or template_id <= 0:
        raise ValueError('非法模板标识')
    return template_id


def _validate_version_no(version_no):
    if not isinstance(version_no, int) or version_no < 1:
        raise ValueError('非法版本号')
    return version_no


def _template_dir(template_id):
    return os.path.join(base_dir(), str(_validate_template_id(template_id)))


def draft_path(template_id):
    return os.path.join(_template_dir(template_id), DRAFT_FILE_NAME)


def version_path(template_id, version_no):
    return os.path.join(
        _template_dir(template_id),
        'v%d.xlsx' % _validate_version_no(version_no))


def write_draft(template_id, data):
    """写入/覆盖草稿源文件（先建目录再落盘）。"""
    target = draft_path(template_id)
    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(target, 'wb') as f:
        f.write(data)
    return target


def publish_draft_to_version(template_id, version_no):
    """发布：把草稿文件复制为版本文件（版本文件此前不存在）。

    返回版本文件路径；草稿缺失或版本文件已存在均属异常。
    """
    source = draft_path(template_id)
    if not os.path.isfile(source):
        raise FileNotFoundError('模板草稿源文件不存在')
    target = version_path(template_id, version_no)
    if os.path.exists(target):
        raise FileExistsError('模板版本文件已存在：%s' % target)
    os.makedirs(os.path.dirname(target), exist_ok=True)
    shutil.copyfile(source, target)
    return target


def read_source(path):
    """读取源文件字节；缺失抛 FileNotFoundError（调用方转业务错误）。"""
    with open(path, 'rb') as f:
        return f.read()


def list_version_files(template_id):
    """列出现存版本文件号（维护用，正常流程不依赖）。"""
    directory = _template_dir(template_id)
    if not os.path.isdir(directory):
        return []
    numbers = []
    for name in os.listdir(directory):
        match = _VERSION_FILE_PATTERN.match(name)
        if match:
            numbers.append(int(match.group(1)))
    return sorted(numbers)
