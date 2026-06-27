# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
from django.urls import path
from channels.routing import URLRouter
from consumer.consumers import *

# Channels 4.x 要求 consumer 类通过 as_asgi() 注册为 single-callable ASGI 应用
ws_router = URLRouter([
    path('ws/subscribe/<str:token>/', PubSubConsumer.as_asgi()),
    path('ws/<str:module>/<str:token>/', ComConsumer.as_asgi()),
])
