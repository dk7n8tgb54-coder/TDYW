# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
import re

# 可打印 ASCII 字符范围（0x21-0x7E），不含空格和控制字符。
# 用于拒绝中文、emoji 等 Unicode 字符混入密码。
_PRINTABLE_ASCII = r'[!-~]+'


def verify_password(password):
    """校验密码强度。

    要求：
    1. 仅包含可打印 ASCII 字符（英文、数字、符号），拒绝中文/emoji/空格；
    2. 长度至少 8 位；
    3. 必须同时包含数字、小写字母、大写字母和特殊字符。
    """
    if not isinstance(password, str) or len(password) < 8:
        return False
    # 拒绝非 ASCII 字符（中文、emoji 等），它们不属于合法密码字符集
    if not re.fullmatch(_PRINTABLE_ASCII, password):
        return False
    if not all(re.search(p, password) for p in ['[0-9]', '[a-z]', '[A-Z]', '[^a-zA-Z0-9]']):
        return False
    return True
