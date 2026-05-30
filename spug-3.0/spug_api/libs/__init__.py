# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
from .parser import JsonParser, Argument
from .decorators import *
from .validators import *
from .mixins import *
from .utils import *

# ==================== Django MySQL 后端兼容性补丁 ====================
# 问题：Django 2.2.28 在 Python 3.10 + mysqlclient 1.4.6 下，
#       last_executed_query 中对已经是 str 的 query 调用 .decode() 导致 AttributeError
# 方案：Monkey Patch 该方法，先判断类型再决定是否 decode
import django.db.backends.mysql.operations as _mysql_ops

_original_last_executed_query = _mysql_ops.DatabaseOperations.last_executed_query


def _patched_last_executed_query(self, cursor, sql, params):
    query = getattr(cursor, '_executed', None)
    if query is not None and isinstance(query, bytes):
        query = query.decode(errors='replace')
    return query


_mysql_ops.DatabaseOperations.last_executed_query = _patched_last_executed_query
