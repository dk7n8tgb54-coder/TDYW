# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""通用附件预览令牌工具

替代将长期 x-token 放入 kkFileView URL 的做法，
改用 Django 签名框架生成的短时效、附件作用域令牌。

令牌结构（签名前）：attachment_id:user_id:tenant_id:module:object_type:object_id
有效期：ATTACHMENT_PREVIEW_TOKEN_MAX_AGE 秒（默认 5 分钟）

绑定项：
- attachment_id  限制令牌只能访问指定附件
- user_id        标识发起预览的用户
- tenant_id      防止跨租户访问
- module         防止跨模块复用
- object_type / object_id  防止令牌被换目标对象使用
"""
import logging
from django.core.signing import TimestampSigner, BadSignature, SignatureExpired

logger = logging.getLogger(__name__)

# 附件预览令牌默认有效期（秒）
ATTACHMENT_PREVIEW_TOKEN_MAX_AGE = 300


def generate_attachment_preview_token(attachment_id, user_id, tenant_id,
                                      module, object_type, object_id):
    """生成短时效附件预览令牌

    Args:
        attachment_id: 附件 ID
        user_id: 用户 ID
        tenant_id: 租户 ID（可为 None 或空字符串）
        module: 模块英文名
        object_type: 业务对象类型
        object_id: 业务对象 ID

    Returns:
        str: 签名后的预览令牌
    """
    signer = TimestampSigner()
    data = f"{attachment_id}:{user_id}:{tenant_id or ''}:{module}:{object_type}:{object_id}"
    return signer.sign(data)


def validate_attachment_preview_token(token, max_age=None):
    """验证附件预览令牌

    Args:
        token: 待验证的令牌字符串
        max_age: 最大有效时长（秒），默认 ATTACHMENT_PREVIEW_TOKEN_MAX_AGE

    Returns:
        dict | None: 验证成功返回令牌数据，失败返回 None
            {'attachment_id': int, 'user_id': int, 'tenant_id': str|None,
             'module': str, 'object_type': str, 'object_id': str}
    """
    if max_age is None:
        max_age = ATTACHMENT_PREVIEW_TOKEN_MAX_AGE

    signer = TimestampSigner()
    try:
        data = signer.unsign(token, max_age=max_age)
        parts = data.split(':')
        if len(parts) != 6:
            return None

        return {
            'attachment_id': int(parts[0]),
            'user_id': int(parts[1]),
            'tenant_id': parts[2] if parts[2] else None,
            'module': parts[3],
            'object_type': parts[4],
            'object_id': parts[5],
        }
    except (BadSignature, SignatureExpired, ValueError, IndexError):
        logger.debug('[AttachmentPreviewToken] Invalid or expired attachment preview token')
        return None
