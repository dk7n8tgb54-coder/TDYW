# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
from django.conf import settings
from django_redis import get_redis_connection
from asgiref.sync import async_to_sync
from consumer.utils import BaseConsumer
from libs.utils import str_decode
from threading import Thread
import time
import json


class ComConsumer(BaseConsumer):
    # Channels 3.x 不再在 __init__ 时设置 self.scope，
    # 改用 BaseConsumer.connect() 中的 init() 钩子（验证用户后调用）
    def init(self):
        token = self.scope['url_route']['kwargs']['token']
        module = self.scope['url_route']['kwargs']['module']
        if module == 'build':
            self.key = f'{settings.BUILD_KEY}:{token}'
        elif module == 'request':
            self.key = f'{settings.REQUEST_KEY}:{token}'
        else:
            raise TypeError(f'unknown module for {module}')
        self.rds = get_redis_connection()

    def disconnect(self, code):
        if hasattr(self, 'rds') and self.rds:
            self.rds.close()

    def get_response(self, index):
        counter = 0
        while counter < 30:
            response = self.rds.lindex(self.key, index)
            if response:
                return response.decode()
            counter += 1
            time.sleep(0.2)

    def receive(self, text_data='', **kwargs):
        if text_data.isdigit():
            index = int(text_data)
            response = self.get_response(index)
            while response:
                index += 1
                self.send(text_data=response)
                response = self.get_response(index)
        self.send(text_data='pong')


class PubSubConsumer(BaseConsumer):
    # Channels 3.x 不再在 __init__ 时设置 self.scope，
    # 改用 BaseConsumer.connect() 中的 init() 钩子（验证用户后调用）
    def init(self):
        self.token = self.scope['url_route']['kwargs']['token']
        self.rds = get_redis_connection()
        self.p = self.rds.pubsub(ignore_subscribe_messages=True)
        self.p.subscribe(self.token)

    def disconnect(self, code):
        if hasattr(self, 'p') and self.p:
            self.p.close()
        if hasattr(self, 'rds') and self.rds:
            self.rds.close()

    def receive(self, **kwargs):
        response = self.p.get_message(timeout=10)
        while response:
            data = str_decode(response['data'])
            self.send(text_data=data)
            response = self.p.get_message(timeout=10)
        self.send(text_data='pong')
