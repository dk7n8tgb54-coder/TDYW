"""Mock views for testing the backend parser"""
from django.views.generic import View
from libs import json_response, JsonParser, Argument, auth
from libs.mixins import AdminView


# View with PERM_MAP
class UserView(AdminView):
    PERM_MAP = {
        'GET': 'system.account.view',
        'POST': 'system.account.add',
        'PATCH': 'system.account.edit',
        'DELETE': 'system.account.del',
    }

    def get(self, request):
        return json_response([])

    def post(self, request):
        return json_response({})

    def patch(self, request):
        return json_response({})

    def delete(self, request):
        return json_response({})


# View with @auth decorator
class NoticeView(View):
    @auth('home.notice.view')
    def get(self, request):
        return json_response([])

    @auth('home.notice.add|home.notice.edit')
    def post(self, request):
        return json_response({})

    @auth('home.notice.del')
    def delete(self, request):
        return json_response({})


# View without any permission check
class UnprotectedView(View):
    def get(self, request):
        return json_response([])

    def post(self, request):
        return json_response({})


# AdminView without PERM_MAP (super only)
class SettingView(AdminView):
    def get(self, request):
        return json_response({})

    def post(self, request):
        return json_response({})


# View with mixed @auth - some methods protected, some not
class PartialView(View):
    @auth('module.resource.view')
    def get(self, request):
        return json_response([])

    def post(self, request):
        # No @auth - should be flagged
        return json_response({})
