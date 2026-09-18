"""spug URL Configuration
# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/2.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('account/', include('apps.account.urls')),
    path('duty/', include('apps.duty.urls')),
    path('device/', include('apps.device.urls')),
    path('setting/', include('apps.setting.urls')),
    path('interference/', include('apps.interference.urls')),
    path('home/', include('apps.home.urls')),
    path('reminder/', include('apps.reminder.urls')),
    path('alert/', include('apps.alert.urls')),
    path('apis/', include('apps.apis.urls')),
    path('document/', include('apps.document.urls')),
    path('runlog/', include('apps.runlog.urls')),
    path('upgrade/', include('apps.upgrade.urls')),
    path('logs/', include('apps.logs.urls')),
    path('radio-license/', include('apps.radio_license.urls')),
    path('contract-agreement/', include('apps.contract_agreement.urls')),
    path('regulation/', include('apps.regulation.urls')),
    path('signature/', include('apps.signature.urls')),
    path('department-duty-log/', include('apps.department_duty_log.urls')),
    path('data-analysis/', include('apps.data_analysis.urls')),
    path('system/', include('apps.release.urls')),
]

# 延迟上线模块路由：与 settings.RELEASE_PENDING_APPS 配套，
# 清单中的模块不注册路由，生产环境不暴露其 API。
# 注意：include('字符串') 会在调用时立即导入目标模块，因此这里只存参数，
# 仅对未列入延迟清单的模块构建 path/include，避免启动时导入未安装模块。
_pending_app_urls = {
    'coop_task': ('coop-task/', 'apps.coop_task.urls'),
    'equipment_lifecycle': ('equipment-lifecycle/', 'apps.equipment_lifecycle.urls'),
}
urlpatterns += [
    path(prefix, include(urlconf))
    for name, (prefix, urlconf) in _pending_app_urls.items()
    if name not in settings.RELEASE_PENDING_APPS
]

# 在开发环境下提供media文件服务
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
