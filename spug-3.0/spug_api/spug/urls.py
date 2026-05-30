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
    path('fault/', include('apps.fault.urls')),
    path('duty/', include('apps.duty.urls')),
    path('device/', include('apps.device.urls')),
    path('setting/', include('apps.setting.urls')),
    path('interference/', include('apps.interference.urls')),
    path('home/', include('apps.home.urls')),
    path('apis/', include('apps.apis.urls')),
    path('document/', include('apps.document.urls')),
    path('runlog/', include('apps.runlog.urls')),
    path('schedule/', include('apps.schedule.urls')),
    path('upgrade/', include('apps.upgrade.urls')),
    path('checksheet/', include('apps.checksheet.urls')),
    path('logs/', include('apps.logs.urls')),
]

# 在开发环境下提供media文件服务
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
