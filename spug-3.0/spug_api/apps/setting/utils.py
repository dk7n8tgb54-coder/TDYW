# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
from functools import lru_cache
from apps.setting.models import Setting, KEYS_DEFAULT
from apps.logs.audit import record_audit_event
import json


class AppSetting:
    @classmethod
    @lru_cache(maxsize=64)
    def get(cls, key):
        info = Setting.objects.filter(key=key).first()
        if not info:
            raise KeyError(f'no such key for {key!r}')
        return info.real_val

    @classmethod
    def get_default(cls, key, default=None):
        info = Setting.objects.filter(key=key).first()
        if not info:
            return default
        return info.real_val

    @classmethod
    def set(cls, key, value, desc=''):
        if key in KEYS_DEFAULT:
            value = json.dumps(value)
            Setting.objects.update_or_create(key=key, defaults={'value': value, 'desc': desc or ''})
            # R5 修复：清除 lru_cache，避免 get 返回旧值
            cls.get.cache_clear()
        else:
            raise KeyError('invalid key')

    @classmethod
    def delete(cls, key, request=None):
        """删除系统配置项

        Args:
            key: 配置键名
            request: 可选，传入则记录审计日志（含变更前值）
        """
        info = Setting.objects.filter(key=key).first()
        Setting.objects.filter(key=key).delete()
        # R5 修复：清除 lru_cache
        cls.get.cache_clear()
        if request and info:
            # R7/R11/R12 修复：改用 record_audit_event，记录变更前值
            record_audit_event(
                request=request,
                action='delete',
                target_type='setting',
                target_id=key,
                target_name=f'配置项-{key}',
                detail={'key': key, 'desc': info.desc},
                before_value={'value': info.real_val} if info.real_val else None,
            )
