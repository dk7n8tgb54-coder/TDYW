# Copyright: (c) OpenSpug Organization. https://github.com/openspug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""
短时效预览令牌工具

替代将长期 x-token 放入 URL 的做法，
改用 Django 签名框架生成的短时效、文件作用域令牌。

令牌结构（签名前）：file_id:user_id:tenant_id:is_public_flag:system_folder
有效期：PREVIEW_TOKEN_MAX_AGE 秒（默认 5 分钟）

system_folder 绑定保证：
- 普通模式令牌不能用于党建文件预览
- 党建令牌不能用于普通文件预览
- 党建令牌去掉/替换请求中的 system_folder 后被拒绝
"""
import logging
from django.core.signing import TimestampSigner, BadSignature, SignatureExpired

logger = logging.getLogger(__name__)

# 预览令牌默认有效期（秒）
PREVIEW_TOKEN_MAX_AGE = 300

# 令牌分隔符（system_folder 内部不应包含冒号，编码层用空串表示普通模式）
_TOKEN_SEP = ':'


def generate_preview_token(file_id, user_id, tenant_id, is_public, system_folder=''):
    """生成短时效预览令牌（绑定 system_folder）

    Args:
        file_id: 文件 ID
        user_id: 用户 ID
        tenant_id: 租户 ID（公共空间可为 None 或空字符串）
        is_public: 是否公共空间
        system_folder: 规范化的系统目录编码；普通模式传空串

    Returns:
        str: 签名后的预览令牌
    """
    signer = TimestampSigner()
    sf = system_folder or ''
    data = f"{file_id}:{user_id}:{tenant_id or ''}:{1 if is_public else 0}:{sf}"
    return signer.sign(data)


def validate_preview_token(token, max_age=None):
    """验证预览令牌

    Args:
        token: 待验证的令牌字符串
        max_age: 最大有效时长（秒），默认 PREVIEW_TOKEN_MAX_AGE

    Returns:
        dict | None: 验证成功返回令牌数据，失败返回 None
            {'file_id': int, 'user_id': int, 'tenant_id': str|None,
             'is_public': bool, 'system_folder': str}
    """
    if max_age is None:
        max_age = PREVIEW_TOKEN_MAX_AGE

    signer = TimestampSigner()
    try:
        data = signer.unsign(token, max_age=max_age)
        parts = data.split(':')
        # 兼容：旧令牌无 system_folder 字段（4 段），新令牌 5 段。
        # 旧令牌按更严格策略处理：视为普通模式 system_folder=''，
        # 由视图层校验文件实际作用域——禁止旧令牌访问系统作用域文件。
        if len(parts) == 4:
            file_id, user_id, tenant_id, is_public_flag = parts
            system_folder = ''
        elif len(parts) == 5:
            file_id, user_id, tenant_id, is_public_flag, system_folder = parts
        else:
            return None

        return {
            'file_id': int(file_id),
            'user_id': int(user_id),
            'tenant_id': tenant_id if tenant_id else None,
            'is_public': bool(int(is_public_flag)),
            'system_folder': system_folder or '',
        }
    except (BadSignature, SignatureExpired, ValueError, IndexError):
        logger.debug('[PreviewToken] Invalid or expired preview token')
        return None
