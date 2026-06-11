# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""
短时效预览令牌工具

替代将长期 x-token 放入 URL 的做法，
改用 Django 签名框架生成的短时效、文件作用域令牌。

令牌结构（签名前）：file_id:user_id:tenant_id:is_public_flag
有效期：PREVIEW_TOKEN_MAX_AGE 秒（默认 5 分钟）
"""
import logging
from django.core.signing import TimestampSigner, BadSignature, SignatureExpired

logger = logging.getLogger(__name__)

# 预览令牌默认有效期（秒）
PREVIEW_TOKEN_MAX_AGE = 300


def generate_preview_token(file_id, user_id, tenant_id, is_public):
    """
    生成短时效预览令牌

    Args:
        file_id: 文件 ID
        user_id: 用户 ID
        tenant_id: 租户 ID（公共空间可为 None 或空字符串）
        is_public: 是否公共空间

    Returns:
        str: 签名后的预览令牌
    """
    signer = TimestampSigner()
    data = f"{file_id}:{user_id}:{tenant_id or ''}:{1 if is_public else 0}"
    return signer.sign(data)


def validate_preview_token(token, max_age=None):
    """
    验证预览令牌

    Args:
        token: 待验证的令牌字符串
        max_age: 最大有效时长（秒），默认 PREVIEW_TOKEN_MAX_AGE

    Returns:
        dict | None: 验证成功返回令牌数据，失败返回 None
            {'file_id': int, 'user_id': int, 'tenant_id': str|None, 'is_public': bool}
    """
    if max_age is None:
        max_age = PREVIEW_TOKEN_MAX_AGE

    signer = TimestampSigner()
    try:
        data = signer.unsign(token, max_age=max_age)
        parts = data.split(':')
        if len(parts) != 4:
            return None

        file_id = int(parts[0])
        user_id = int(parts[1])
        tenant_id = parts[2] if parts[2] else None
        is_public = bool(int(parts[3]))

        return {
            'file_id': file_id,
            'user_id': user_id,
            'tenant_id': tenant_id,
            'is_public': is_public,
        }
    except (BadSignature, SignatureExpired, ValueError, IndexError):
        logger.debug('[PreviewToken] Invalid or expired preview token')
        return None
