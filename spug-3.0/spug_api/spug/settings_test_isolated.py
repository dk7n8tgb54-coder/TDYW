# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""测试专用 settings：使用独立命名的测试数据库

默认测试库 test_spug 与开发库 spug 同实例，多会话并行跑测试时会互相
DROP/重建导致 "Unknown table" 竞争失败。本文件仅把测试库名改为
test_spug_isolated，其余配置与 spug.settings 完全一致。

用法：
    python manage.py test <labels> --settings=spug.settings_test_isolated --noinput
"""
from spug.settings import *  # noqa: F401,F403

DATABASES['default']['TEST'] = {'NAME': 'test_spug_isolated'}
