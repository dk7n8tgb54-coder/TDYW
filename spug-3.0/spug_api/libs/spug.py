# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under AGPL-3.0 License.
import requests


class Notification:
    @staticmethod
    def handle_request(url, data, mode=None):
        try:
            res = requests.post(url, json=data, timeout=15)
        except Exception as e:
            return
        if res.status_code != 200:
            return

        if mode in ['dd', 'wx']:
            res = res.json()
            if res.get('errcode') == 0:
                return
        elif mode == 'spug':
            res = res.json()
            if not res.get('error'):
                return
        elif mode == 'fs':
            res = res.json()
            if res.get('StatusCode') == 0:
                return
        else:
            raise NotImplementedError
