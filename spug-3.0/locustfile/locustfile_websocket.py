#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
WebSocket 推送压测脚本(上线后可补 🟡)

风险:系统用 Django Channels 做 WebSocket 实时通知(公告/上传进度/签名状态)。
大量并发连接会占用 Redis(channels 用 DB0)、内存(channel layer 状态)。

注意:locust 原生不支持 WebSocket,需 websockets 库(pip install websockets)。
未安装时脚本自动跳过(声明为 abstract)。

前置条件:
- Channels consumer 运行中
- Redis DB0 可用
- WebSocket 路径 /ws/notifications/(按实际路由调整)

运行:
    python -m locust -f locustfile/locustfile_websocket.py -H http://localhost
    python -m locust -f locustfile/locustfile_websocket.py -H http://localhost \\
        --headless -u 50 -r 10 -t 5m --csv=websocket

关注: 连接成功率、握手 P95、Redis DB0 内存
"""

import asyncio
import time
import logging

from locust import User, task, between, events

from _common import login_shared, next_account, refresh_token

logger = logging.getLogger(__name__)

try:
    import websockets
    HAS_WEBSOCKETS = True
except ImportError:
    HAS_WEBSOCKETS = False
    logger.warning("websockets 未安装,WebSocket 压测跳过。pip install websockets")


class WebSocketUser(User):
    """WebSocket 推送压测用户"""

    wait_time = between(1, 3)
    abstract = not HAS_WEBSOCKETS

    def on_start(self):
        if not HAS_WEBSOCKETS:
            return
        self.username, self.token = login_shared(self.client)
        self.loop = asyncio.new_event_loop()

    def _build_ws_url(self, host):
        ws_host = host.replace("http://", "ws://").replace("https://", "wss://")
        # 真实路由: consumer/routing.py 定义 ws/subscribe/<token>/ 和 ws/<module>/<token>/
        return f"{ws_host}/ws/subscribe/{self.token}/"

    @task(5)
    def connect_and_listen(self):
        if not HAS_WEBSOCKETS:
            return
        url = self._build_ws_url(self.environment.host)
        try:
            self.loop.run_until_complete(self._connect_and_listen(url, timeout=5))
        except Exception as e:
            events.request.fire(
                request_type="WS-CONNECT", name="WebSocket 连接",
                response_time=0, response_length=0, exception=e, context={},
            )

    async def _connect_and_listen(self, url, timeout=5):
        start = time.time()
        try:
            async with websockets.connect(url, close_timeout=1) as ws:
                elapsed = int((time.time() - start) * 1000)
                events.request.fire(
                    request_type="WS-CONNECT", name="WebSocket 连接",
                    response_time=elapsed, response_length=0, exception=None, context={},
                )
                try:
                    await asyncio.wait_for(ws.recv(), timeout=timeout)
                    events.request.fire(
                        request_type="WS-RECV", name="WebSocket 接收消息",
                        response_time=int((time.time() - start) * 1000),
                        response_length=0, exception=None, context={},
                    )
                except asyncio.TimeoutError:
                    pass
        except Exception as e:
            events.request.fire(
                request_type="WS-CONNECT", name="WebSocket 连接",
                response_time=int((time.time() - start) * 1000),
                response_length=0, exception=e, context={},
            )

    def on_stop(self):
        if hasattr(self, "loop"):
            try:
                self.loop.close()
            except Exception:
                pass


@events.test_start.add_listener
def on_test_start(environment, **kwargs):
    print("=" * 60)
    print("WebSocket 推送压测开始")
    if not HAS_WEBSOCKETS:
        print("⚠️  websockets 库未安装,无用户实例化。pip install websockets")
    else:
        print("⚠️  关注: 连接成功率、握手 P95、Redis DB0 内存")
    print("=" * 60)
