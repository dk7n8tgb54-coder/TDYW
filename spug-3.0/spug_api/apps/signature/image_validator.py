# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""签名图片安全校验与标准化

第一期仅接受 PNG，规则：
- 扩展名 .png
- 声明 MIME image/png（不信任请求头，以 Pillow 实际解码为准）
- 最大文件 2 MB
- 宽高均在 100～2000 像素之间
- Pillow 实际解码并 verify() 完整性
- 服务端重新编码为 PNG，剥离元数据和附加内容
- 返回重新编码后的字节流和 SHA256

所有校验失败抛出 ValueError，调用方捕获后转成用户可读错误。
"""
import hashlib
import io
import logging

logger = logging.getLogger(__name__)

# 签名图片限制
SIGNATURE_MAX_SIZE = 2 * 1024 * 1024  # 2 MB
SIGNATURE_MIN_DIM = 100
SIGNATURE_MAX_DIM = 2000
SIGNATURE_FORMAT = 'PNG'
SIGNATURE_EXT = '.png'

# Pillow 解压炸弹最大像素数（2000x2000 留余量）
SIGNATURE_MAX_PIXELS = 2000 * 2000 * 2


class SignatureImageError(ValueError):
    """签名图片校验错误，消息可直接展示给用户"""


def _decode_and_load_png(raw_bytes):
    """Pillow 解码、verify 完整性、二次 load 并校验格式为 PNG。

    Returns:
        Image 对象（已 load，可操作像素）
    Raises:
        SignatureImageError: 任一步骤失败
    """
    from PIL import Image
    try:
        img = Image.open(io.BytesIO(raw_bytes))
    except Exception:
        logger.warning('[Signature] 签名图片解码失败：不是有效图片')
        raise SignatureImageError('签名图片解码失败，请上传有效的 PNG 图片')

    try:
        img.verify()
    except Exception:
        logger.warning('[Signature] 签名图片完整性校验失败')
        raise SignatureImageError('签名图片已损坏，请重新上传')

    # verify() 后需要重新打开才能操作像素
    try:
        img = Image.open(io.BytesIO(raw_bytes))
        img.load()
    except Exception:
        logger.warning('[Signature] 签名图片二次解码失败')
        raise SignatureImageError('签名图片解码失败，请重新上传')

    if img.format != SIGNATURE_FORMAT:
        raise SignatureImageError('签名图片仅支持 PNG 格式')
    return img


def _re_encode_png(img):
    """将图片重新编码为 PNG（剥离元数据），并校验可再次解码。

    Returns:
        tuple: (normalized_bytes, sha256_hex)
    Raises:
        SignatureImageError: 重新编码或二次校验失败
    """
    from PIL import Image
    mode = img.mode
    if mode not in ('RGBA', 'RGB', 'L', 'LA', 'P'):
        img = img.convert('RGBA')
    # P 模式带透明度时转 RGBA，避免调色板丢失透明通道
    if mode == 'P':
        img = img.convert('RGBA')

    out = io.BytesIO()
    img.save(out, format=SIGNATURE_FORMAT, optimize=True)
    normalized_bytes = out.getvalue()

    # 重新编码后再次确认可解码（防御性）
    try:
        recheck = Image.open(io.BytesIO(normalized_bytes))
        recheck.verify()
    except Exception:
        logger.error('[Signature] 重新编码后的 PNG 校验失败')
        raise SignatureImageError('签名图片处理异常，请重试')

    sha256 = hashlib.sha256(normalized_bytes).hexdigest()
    return normalized_bytes, sha256


def validate_and_normalize_signature_image(uploaded_file):
    """校验并标准化签名图片

    Args:
        uploaded_file: Django UploadedFile 对象

    Returns:
        tuple: (normalized_bytes, sha256_hex)
        normalized_bytes 为服务端重新编码后的 PNG 字节流
        sha256_hex 为重新编码后实际字节的 SHA256

    Raises:
        SignatureImageError: 任何校验失败
    """
    # 1. 扩展名校验
    import os
    _, ext = os.path.splitext(uploaded_file.name or '')
    ext = ext.lower()
    if ext != SIGNATURE_EXT:
        raise SignatureImageError('签名图片仅支持 PNG 格式')

    # 2. 大小校验（提前拒绝，避免 Pillow 处理超大文件）
    if uploaded_file.size > SIGNATURE_MAX_SIZE:
        raise SignatureImageError('签名图片大小不能超过 2MB')
    if uploaded_file.size == 0:
        raise SignatureImageError('签名图片文件为空')

    # 3. Pillow 实际解码
    try:
        from PIL import Image
    except ImportError:
        logger.error('[Signature] Pillow 未安装，无法校验签名图片')
        raise SignatureImageError('图片处理服务不可用，请联系管理员')

    # 限制解压炸弹
    Image.MAX_IMAGE_PIXELS = SIGNATURE_MAX_PIXELS

    raw_bytes = uploaded_file.read()
    uploaded_file.seek(0)

    img = _decode_and_load_png(raw_bytes)

    # 4. 尺寸校验
    width, height = img.size
    if width < SIGNATURE_MIN_DIM or height < SIGNATURE_MIN_DIM:
        raise SignatureImageError(
            f'签名图片尺寸过小，宽高均需在 {SIGNATURE_MIN_DIM}～{SIGNATURE_MAX_DIM} 像素之间')
    if width > SIGNATURE_MAX_DIM or height > SIGNATURE_MAX_DIM:
        raise SignatureImageError(
            f'签名图片尺寸过大，宽高均需在 {SIGNATURE_MIN_DIM}～{SIGNATURE_MAX_DIM} 像素之间')

    # 5. 服务端重新编码为 PNG，剥离元数据和附加内容
    return _re_encode_png(img)
