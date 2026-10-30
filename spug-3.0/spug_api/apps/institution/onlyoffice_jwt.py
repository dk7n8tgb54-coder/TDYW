# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""ONLYOFFICE Docs JWT（HS256）最小实现

项目依赖未包含 PyJWT；ONLYOFFICE 文档服务（DS）与业务端的互信仅需
HS256 签名，此处用 hmac/hashlib/base64 实现签名与校验，避免为单一
集成引入新依赖。格式与 ONLYOFFICE 官方约定一致：

  base64url(header).base64url(payload).base64url(HMAC-SHA256(secret))

- 配置签名：payload 为 {"document": ..., "editorConfig": ...}，
  由前端随 DocsAPI.DocEditor 的 config.token 提交，DS 校验。
- 回调签名：DS 对整个回调 body 签名，置于 Authorization: Bearer
  （默认）或 body.token 字段；业务端校验后才信任 body 内容。

安全说明：签名比较使用 hmac.compare_digest 恒时比较；校验失败一律
返回 None，不区分失效原因（不向调用方泄露细节）。
"""
import base64
import hashlib
import hmac
import json


class OnlyOfficeJwtError(Exception):
    """JWT 校验失败"""


def _b64url_encode(data):
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode('ascii')


def _b64url_decode(data):
    padding = '=' * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def sign_payload(payload, secret):
    """对 payload dict 生成 HS256 JWT；secret 为空时抛错（fail-closed）"""
    if not secret:
        raise OnlyOfficeJwtError('ONLYOFFICE JWT secret 未配置')
    header = {'alg': 'HS256', 'typ': 'JWT'}
    segments = [
        _b64url_encode(json.dumps(header, separators=(',', ':')).encode('utf-8')),
        _b64url_encode(json.dumps(payload, separators=(',', ':')).encode('utf-8')),
    ]
    signing_input = '.'.join(segments).encode('ascii')
    signature = hmac.new(
        secret.encode('utf-8'), signing_input, hashlib.sha256).digest()
    segments.append(_b64url_encode(signature))
    return '.'.join(segments)


def verify_token(token, secret):
    """校验 HS256 JWT 并返回 payload dict；失败返回 None

    - alg 必须为 HS256（拒绝 none/其他算法的降级攻击）
    - 签名恒时比较
    """
    if not token or not secret:
        return None
    try:
        header_b64, payload_b64, signature_b64 = token.split('.')
        header = json.loads(_b64url_decode(header_b64))
        # header 段可能被构造为 JSON 标量/数组，先验类型再取键（防 AttributeError）
        if not isinstance(header, dict) or header.get('alg') != 'HS256':
            return None
        signing_input = f'{header_b64}.{payload_b64}'.encode('ascii')
        expected = hmac.new(
            secret.encode('utf-8'), signing_input, hashlib.sha256).digest()
        actual = _b64url_decode(signature_b64)
        if not hmac.compare_digest(expected, actual):
            return None
        payload = json.loads(_b64url_decode(payload_b64))
        return payload if isinstance(payload, dict) else None
    except (ValueError, TypeError, json.JSONDecodeError):
        return None
