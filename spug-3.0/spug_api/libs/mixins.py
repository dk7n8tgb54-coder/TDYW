# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
from django.views.generic import View
from .utils import json_response


# 混入类，提供Model实例to_dict方法
class ModelMixin(object):
    __slots__ = ()

    def to_dict(self, excludes: tuple = None, selects: tuple = None) -> dict:
        if not hasattr(self, '_meta'):
            raise TypeError('<%r> does not a django.db.models.Model object.' % self)
        elif selects:
            return {f: getattr(self, f) for f in selects}
        elif excludes:
            return {f.attname: getattr(self, f.attname) for f in self._meta.fields if f.attname not in excludes}
        else:
            return {f.attname: getattr(self, f.attname) for f in self._meta.fields}

    def update_by_dict(self, data):
        for key, value in data.items():
            if value is not None:
                setattr(self, key, value)
        self.save()


class AdminView(View):
    # 权限键映射：HTTP方法 → 需要的权限
    # 子类可覆盖此映射，如 UserView 需要细粒度权限控制
    PERM_MAP = {}

    def dispatch(self, request, *args, **kwargs):
        if hasattr(request, 'user'):
            # 超管：放行
            if request.user.is_supper:
                return super().dispatch(request, *args, **kwargs)
            # 非超管：如果子类定义了权限映射，按映射校验
            if self.PERM_MAP:
                perm_key = self.PERM_MAP.get(request.method)
                if perm_key and request.user.has_perms({perm_key}):
                    return super().dispatch(request, *args, **kwargs)
        return json_response(error='权限拒绝')
