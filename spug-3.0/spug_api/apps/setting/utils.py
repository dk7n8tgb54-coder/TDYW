# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
from functools import lru_cache
from apps.setting.models import Setting, KEYS_DEFAULT
from apps.logs.audit import save_audit_log
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
        else:
            raise KeyError('invalid key')

    @classmethod
    def delete(cls, key, request=None):
        """删除系统配置项

        Args:
            key: 配置键名
            request: 可选，传入则记录审计日志
        """
        info = Setting.objects.filter(key=key).first()
        Setting.objects.filter(key=key).delete()
        if request and info:
            save_audit_log(
                user_id=request.user.id,
                username=request.user.username,
                action='delete',
                target_type='setting',
                target_id=key,
                target_name=f'配置项-{key}',
                detail=json.dumps({'key': key, 'desc': info.desc}, ensure_ascii=False),
            )
