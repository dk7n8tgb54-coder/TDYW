# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""
ASGI entrypoint. Configures Django and then runs the application
defined in the ASGI_APPLICATION setting.

Channels 4.x 移除了 get_default_application()，直接引用 routing.application。
"""


import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')
django.setup()

from spug.routing import application  # noqa: E402
