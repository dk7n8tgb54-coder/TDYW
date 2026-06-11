# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""
文件预览视图
提供文件预览功能（图片、PDF、视频流、音频、文本、Office文档）
"""

import os
import re
import logging
from django.views.generic import View
from django.http import HttpResponse
from django.conf import settings

from libs import json_response, JsonParser, Argument, auth
from libs.tenant_utils import apply_tenant_filter
from ...libs.document_utils import get_file_model, is_safe_path

logger = logging.getLogger(__name__)

# 文本预览最大文件大小（默认2MB）
TEXT_PREVIEW_MAX_SIZE = getattr(settings, 'TEXT_PREVIEW_MAX_SIZE', 2 * 1024 * 1024)

# Office文件MIME类型
OFFICE_MIME_TYPES = {
    'application/msword',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'application/vnd.ms-excel',
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    'application/vnd.ms-powerpoint',
    'application/vnd.openxmlformats-officedocument.presentationml.presentation',
}

# 通过扩展名识别的代码/文本文件（MIME可能是application/octet-stream）
CODE_EXTENSIONS = {
    '.py', '.js', '.jsx', '.ts', '.tsx', '.java', '.c', '.cpp', '.h', '.hpp',
    '.go', '.rs', '.rb', '.php', '.vue', '.sh', '.bash', '.zsh', '.yaml', '.yml',
    '.toml', '.sql', '.md', '.csv', '.log', '.ini', '.cfg', '.conf', '.env',
    '.dockerfile', '.tf', '.proto', '.lua', '.r', '.scala', '.kt', '.swift',
    '.dart', '.ps1', '.bat', '.makefile', '.gitignore',
}

# Office文件扩展名
OFFICE_EXTENSIONS = {
    '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx',
}


class FilePreviewView(View):
    """文件预览视图 - 支持图片、PDF、视频流、音频、文本"""

    @auth('document.document.view')
    def get(self, request):
        form, error = JsonParser(
            Argument('id', type=int, help='参数错误'),
            Argument('is_public', type=bool, required=False, default=False),
            Argument('thumbnail', type=bool, required=False, default=False)
        ).parse(request.GET)

        if error is not None:
            return json_response(error=error)

        # 【H-2修复】preview_token 作用域校验：令牌绑定的文件必须与请求文件一致
        if hasattr(request, 'preview_token_data'):
            token_data = request.preview_token_data
            if token_data['file_id'] != form.id:
                logger.warning(f'[Preview] preview_token file_id mismatch: token={token_data["file_id"]}, request={form.id}')
                return json_response(error='预览令牌与请求文件不匹配')
            if token_data['is_public'] != form.is_public:
                return json_response(error='预览令牌与请求空间不匹配')

        file = self._get_file(form, request.user)
        if file is None:
            return json_response(error='文件不存在')

        # 【路径安全校验】验证 file_path 在 storage/documents 下
        document_storage_base = os.path.join(settings.BASE_DIR, 'storage', 'documents')
        if not is_safe_path(document_storage_base, file.file_path):
            logger.error(f'[Preview] Unsafe file path detected: {file.file_path}')
            return json_response(error='文件不存在')

        # 【性能优化】缩略图模式：优先返回缩略图路径
        if form.thumbnail and file.thumbnail_path:
            # 【路径安全校验】缩略图必须在 storage/documents 下
            if is_safe_path(document_storage_base, file.thumbnail_path):
                if os.path.exists(file.thumbnail_path):
                    return self._stream_file_response(file.thumbnail_path, 'image/jpeg')
                else:
                    logger.warning(f'[Preview] Thumbnail not found: {file.thumbnail_path}, falling back to original')
                    # 缩略图不存在时回退到原图
            else:
                logger.error(f'[Preview] Unsafe thumbnail path detected: {file.thumbnail_path}')
                return json_response(error='文件不存在')

        if not os.path.exists(file.file_path):
            logger.warning(f'[Preview] File path not exists: id={form.id}, path={file.file_path}')
            return json_response(error='文件不存在')

        # 根据文件类型路由到对应预览处理
        return self._route_preview(request, file, form)

    def _get_file(self, form, user):
        """获取文件对象"""
        FileModel = get_file_model(is_public=form.is_public)
        file_query = FileModel.objects.filter(pk=form.id)
        if not form.is_public:
            file_query = apply_tenant_filter(file_query, user, strict_mode=True)
        file = file_query.select_related('created_by').first()
        if not file:
            logger.warning(f'[Preview] File not found: id={form.id}, is_public={form.is_public}')
        return file

    def _route_preview(self, request, file, form):
        """根据文件类型路由到对应的预览处理器"""
        logger.info(f'[Preview] id={form.id}, name={file.name}, file_type={file.file_type}, '
                     f'is_office={self.is_office_file(file)}, is_text={self._is_text_file(file)}, '
                     f'is_image={file.file_type.startswith("image/") if file.file_type else False}')

        if file.file_type and file.file_type.startswith('image/'):
            return self._stream_file_response(file.file_path, file.file_type)

        if file.file_type and ('application/pdf' in file.file_type):
            return self._stream_file_response(
                file.file_path, 
                'application/pdf',
                content_disposition=f'inline; filename="{file.name}"'
            )

        if file.file_type and file.file_type.startswith('video/'):
            return self._handle_media_stream(request, file)

        if file.file_type and file.file_type.startswith('audio/'):
            return self._handle_media_stream(request, file)

        if self._is_text_file(file):
            file_size = os.path.getsize(file.file_path)
            if file_size > TEXT_PREVIEW_MAX_SIZE:
                return json_response(error='文本文件过大，无法在线预览（最大支持2MB）')
            return self._stream_file_response(file.file_path, file.file_type)

        if self.is_office_file(file):
            from urllib.parse import quote
            file_name = file.display_name or file.name or 'download'
            return self._stream_file_response(
                file.file_path,
                file.file_type or 'application/octet-stream',
                content_disposition=f'attachment; filename*=UTF-8\'\'{quote(file_name)}'
            )

        logger.warning(f'[Preview] UNSUPPORTED file type: id={form.id}, name={file.name}, '
                       f'file_type={file.file_type}, is_office={self.is_office_file(file)}, '
                       f'is_text={self._is_text_file(file)}')
        return json_response(error='该文件类型不支持在线预览')

    @staticmethod
    def _is_text_file(file):
        """判断是否为文本/代码文件"""
        # MIME类型以text/开头
        if file.file_type.startswith('text/'):
            return True
        # 常见的应用类型文本格式
        text_app_types = {
            'application/json',
            'application/xml',
            'application/javascript',
            'application/x-javascript',
        }
        if file.file_type in text_app_types:
            return True
        # 通过扩展名判断（处理application/octet-stream等情况）
        file_name = file.display_name or file.name or ''
        _, ext = os.path.splitext(file_name.lower())
        if ext in CODE_EXTENSIONS:
            return True
        # 无扩展名的常见文本文件名
        basename = os.path.basename(file_name.lower())
        if basename in {'makefile', 'dockerfile', '.gitignore', '.env', 'readme', 'license'}:
            return True
        return False

    @staticmethod
    def is_office_file(file):
        """判断是否为Office文件"""
        if file.file_type in OFFICE_MIME_TYPES:
            return True
        file_name = file.display_name or file.name or ''
        _, ext = os.path.splitext(file_name.lower())
        return ext in OFFICE_EXTENSIONS

    def _handle_media_stream(self, request, file):
        """处理媒体流请求（支持Range请求，适用于视频和音频）"""
        response = HttpResponse()
        response['Content-Type'] = file.file_type
        response['X-Content-Type-Options'] = 'nosniff'
        response['Accept-Ranges'] = 'bytes'

        range_header = request.META.get('HTTP_RANGE', '').strip()
        file_size = os.path.getsize(file.file_path)

        if range_header:
            try:
                range_match = re.match(r'bytes=(\d+)-(\d*)', range_header)
                if range_match:
                    start = int(range_match.group(1))
                    end = int(range_match.group(2)) if range_match.group(2) else file_size - 1
                    content_length = end - start + 1
                    response.status_code = 206
                    response['Content-Range'] = f'bytes {start}-{end}/{file_size}'
                    response['Content-Length'] = str(content_length)

                    with open(file.file_path, 'rb') as f:
                        f.seek(start)
                        response.content = f.read(content_length)
            except Exception as e:
                logger.error(f'[Document] Error parsing range header: {e}')
                with open(file.file_path, 'rb') as f:
                    response.status_code = 200
                    response['Content-Length'] = str(file_size)
                    response.content = f.read()
        else:
            with open(file.file_path, 'rb') as f:
                response.status_code = 200
                response['Content-Length'] = str(file_size)
                response.content = f.read()
        return response

    def _stream_file_response(self, file_path, content_type, content_disposition=None):
        """
        流式文件响应，避免大文件占用过多内存
        
        Args:
            file_path: 文件路径
            content_type: MIME类型
            content_disposition: Content-Disposition头（可选）
            
        Returns:
            StreamingHttpResponse: 流式响应对象
        """
        from django.http import StreamingHttpResponse
        
        def file_iterator(file_path, chunk_size=1024*1024):
            """文件迭代器，每次读取1MB"""
            with open(file_path, 'rb') as f:
                while True:
                    chunk = f.read(chunk_size)
                    if not chunk:
                        break
                    yield chunk
        
        file_size = os.path.getsize(file_path)
        response = StreamingHttpResponse(
            file_iterator(file_path),
            content_type=content_type
        )
        response['Content-Length'] = str(file_size)
        # 【H-2修复】防止预览 URL 通过 Referer 泄露
        response['Referrer-Policy'] = 'no-referrer'
        if content_disposition:
            response['Content-Disposition'] = content_disposition
        return response


class FileTextContentView(View):
    """文件文本内容视图 - 返回文本/代码文件内容（用于代码高亮渲染）"""

    @auth('document.document.view')
    def get(self, request):
        form, error = JsonParser(
            Argument('id', type=int, help='参数错误'),
            Argument('is_public', type=bool, required=False, default=False)
        ).parse(request.GET)
        
        if error is not None:
            return json_response(error=error)

        # 【H-2修复】preview_token 作用域校验
        if hasattr(request, 'preview_token_data'):
            token_data = request.preview_token_data
            if token_data['file_id'] != form.id:
                return json_response(error='预览令牌与请求文件不匹配')
            if token_data['is_public'] != form.is_public:
                return json_response(error='预览令牌与请求空间不匹配')
            
        FileModel = get_file_model(is_public=form.is_public)

        file_query = FileModel.objects.filter(pk=form.id)
        if not form.is_public:
            file_query = apply_tenant_filter(file_query, request.user, strict_mode=True)
        file = file_query.select_related('created_by').first()
        
        if not file:
            return json_response(error='文件不存在')

        # 【路径安全校验】验证 file_path 在 storage/documents 下
        document_storage_base = os.path.join(settings.BASE_DIR, 'storage', 'documents')
        if not is_safe_path(document_storage_base, file.file_path):
            logger.error(f'[TextContent] Unsafe file path detected: {file.file_path}')
            return json_response(error='文件不存在')

        if not os.path.exists(file.file_path):
            return json_response(error='文件不存在')

        # 检查文件大小
        file_size = os.path.getsize(file.file_path)
        if file_size > TEXT_PREVIEW_MAX_SIZE:
            return json_response(error=f'文件过大，无法在线预览（最大支持{TEXT_PREVIEW_MAX_SIZE // 1024 // 1024}MB）')

        # 读取文本内容（尝试多种编码）
        content = self._read_text_content(file.file_path)
        if content is None:
            return json_response(error='无法解析文件内容，可能是二进制文件')

        # 获取文件语言（用于语法高亮）
        language = self._detect_language(file)

        return json_response(data={
            'content': content,
            'language': language,
            'file_name': file.display_name or file.name,
            'file_size': file_size,
            'is_truncated': False,
        })

    @staticmethod
    def _read_text_content(file_path):
        """读取文本文件内容，尝试多种编码"""
        # 按优先级尝试编码
        encodings = ['utf-8', 'utf-8-sig', 'gbk', 'gb2312', 'gb18030', 'latin-1']
        
        for encoding in encodings:
            try:
                with open(file_path, 'r', encoding=encoding) as f:
                    content = f.read()
                # 验证内容不含过多控制字符（二进制文件检测）
                if content:
                    control_chars = sum(1 for c in content[:1000] if ord(c) < 32 and c not in '\n\r\t')
                    if control_chars > 100:
                        return None
                return content
            except (UnicodeDecodeError, UnicodeError):
                continue
            except Exception:
                continue
        
        return None

    @staticmethod
    def _detect_language(file):
        """根据文件扩展名检测语言（用于Ace Editor语法高亮）"""
        EXT_TO_MODE = {
            '.py': 'python', '.js': 'javascript', '.jsx': 'javascript',
            '.ts': 'typescript', '.tsx': 'typescript', '.java': 'java',
            '.c': 'c_cpp', '.cpp': 'c_cpp', '.h': 'c_cpp', '.hpp': 'c_cpp',
            '.go': 'golang', '.rs': 'rust', '.rb': 'ruby', '.php': 'php',
            '.html': 'html', '.css': 'css', '.json': 'json', '.xml': 'xml',
            '.yaml': 'yaml', '.yml': 'yaml', '.toml': 'toml',
            '.sh': 'sh', '.bash': 'sh', '.zsh': 'sh',
            '.sql': 'sql', '.md': 'markdown', '.csv': 'csv',
            '.vue': 'html', '.ini': 'ini', '.cfg': 'ini', '.conf': 'ini',
            '.lua': 'lua', '.r': 'r', '.scala': 'scala', '.kt': 'kotlin',
            '.swift': 'swift', '.dart': 'dart', '.ps1': 'powershell',
            '.bat': 'batchfile', '.tf': 'sh', '.proto': 'protobuf',
            '.txt': 'text', '.log': 'text', '.env': 'text',
        }
        
        file_name = file.display_name or file.name or ''
        _, ext = os.path.splitext(file_name.lower())
        
        # 特殊文件名
        basename = os.path.basename(file_name.lower())
        if basename in {'makefile', 'dockerfile'}:
            return 'sh'
        if basename == '.gitignore':
            return 'gitignore'
        
        return EXT_TO_MODE.get(ext, 'text')


class OfficePreviewUrlView(View):
    """Office文档预览URL视图 - 生成kkFileView预览链接"""

    @auth('document.document.view')
    def get(self, request):
        form, error = JsonParser(
            Argument('id', type=int, help='参数错误'),
            Argument('is_public', type=bool, required=False, default=False)
        ).parse(request.GET)
        
        if error is not None:
            return json_response(error=error)

        # 检查kkFileView是否已配置
        kkfileview_api_url = getattr(settings, 'KKFILEVIEW_API_URL', '')
        if not kkfileview_api_url:
            return json_response(error='Office文档预览服务未配置，请联系管理员配置KKFILEVIEW_API_URL')

        kkfileview_server_url = getattr(settings, 'KKFILEVIEW_SERVER_URL', '')
        if not kkfileview_server_url:
            return json_response(error='Office文档预览服务未配置，请联系管理员配置KKFILEVIEW_SERVER_URL')
            
        FileModel = get_file_model(is_public=form.is_public)

        file_query = FileModel.objects.filter(pk=form.id)
        if not form.is_public:
            file_query = apply_tenant_filter(file_query, request.user, strict_mode=True)
        file = file_query.select_related('created_by').first()
        
        if not file:
            logger.warning(f'[OfficePreviewUrl] File not found: id={form.id}, is_public={form.is_public}')
            return json_response(error='文件不存在')

        # 【路径安全校验】验证 file_path 在 storage/documents 下
        document_storage_base = os.path.join(settings.BASE_DIR, 'storage', 'documents')
        if not is_safe_path(document_storage_base, file.file_path):
            logger.error(f'[OfficePreviewUrl] Unsafe file path detected: {file.file_path}')
            return json_response(error='文件不存在')

        if not os.path.exists(file.file_path):
            logger.warning(f'[OfficePreviewUrl] File path not exists: id={form.id}, path={file.file_path}')
            return json_response(error='文件不存在')

        # [DEBUG] 诊断日志
        logger.info(f'[OfficePreviewUrl] id={form.id}, name={file.name}, file_type={file.file_type}, '
                     f'is_office={FilePreviewView.is_office_file(file)}, token={request.META.get("HTTP_X_TOKEN", "")[:8]}...')

        # 验证是Office文件
        if not FilePreviewView.is_office_file(file):
            logger.warning(f'[OfficePreviewUrl] NOT office file: name={file.name}, file_type={file.file_type}')
            return json_response(error='该文件不是Office文档')

        # 构建kkFileView预览URL
        import base64
        from urllib.parse import urlencode, quote
        from ...libs.preview_token import generate_preview_token
        
        # 【H-2修复】使用短时效 preview_token 替代长期 x-token
        # kkFileView 通过此 URL 回调下载文件，preview_token 有效期 5 分钟
        tenant_id = getattr(request.user, 'tenant_id', None)
        preview_token = generate_preview_token(
            file_id=file.id,
            user_id=request.user.id,
            tenant_id=tenant_id,
            is_public=form.is_public
        )
        params = {
            'id': file.id,
            'preview_token': preview_token,
            'is_public': str(form.is_public).lower(),
        }
        file_url = f"{kkfileview_server_url}/api/document/preview/?{urlencode(params)}"
        
        # kkFileView 官方文档要求：当下载URL不含文件扩展名时，
        # 必须将 fullfilename 参数拼接到源文件URL中，再整体 base64 编码
        # 参考：http://www.kkview.cn/zh-cn/docs/usage.html （第2节：HTTP/HTTPS下载流URL预览）
        # 错误写法：onlinePreview?url=<base64>&fullfilename=xxx  （fullfilename 作为独立参数会崩溃）
        # 正确写法：onlinePreview?url=<base64 of "源URL&fullfilename=xxx">
        file_name = file.display_name or file.name or ''
        if file_name:
            file_url = f"{file_url}&fullfilename={quote(file_name)}"
        
        # kkFileView 3.x+ 要求 url 参数使用 base64 编码
        encoded_url = base64.b64encode(file_url.encode('utf-8')).decode('utf-8')
        preview_url = f"{kkfileview_api_url}/onlinePreview?url={encoded_url}"

        return json_response(data={
            'preview_url': preview_url,
            'file_name': file_name,
        })


class PreviewTokenView(View):
    """【H-2修复】生成短时效预览令牌

    前端请求此接口获取 preview_token，用于构造图片/视频/音频/PDF 预览 URL，
    避免将长期 x-token 暴露在 URL 中。
    """

    @auth('document.document.view')
    def get(self, request):
        form, error = JsonParser(
            Argument('id', type=int, help='参数错误'),
            Argument('is_public', type=bool, required=False, default=False)
        ).parse(request.GET)

        if error is not None:
            return json_response(error=error)

        from ...libs.preview_token import generate_preview_token

        tenant_id = getattr(request.user, 'tenant_id', None)
        token = generate_preview_token(
            file_id=form.id,
            user_id=request.user.id,
            tenant_id=tenant_id,
            is_public=form.is_public
        )

        return json_response(data={'preview_token': token})
