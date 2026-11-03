# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""ONLYOFFICE Docs 在线编辑服务层

职责（与 views_draft.py 的 multipart 契约端点完全独立）：
- 生成 DocsAPI.DocEditor 所需的编辑配置（含 document.key/权限/JWT）
- 编辑器文件下载地址（editor_token 自认证通道，见 views_draft.EditorFileView）
- 回调载荷校验（JWT + 手册/会话/角色/修订序号）
- 回调保存状态机：status 2/6 落盘，1/4 心跳静默吸收，2 幂等
- 收尾回调放行：discard=false 撤销的同一编辑实例（同 current_doc_key）
  的收尾 status-2/6 回调在撤销后仍允许落盘（DS 关闭编辑器时补发的
  收尾回调可能晚于"保存并结束编辑"的会话撤销到达，拒绝即丢失最后
  一次修改）；缺省撤销与批量失效一律照旧拒绝

安全边界：
- document.key 是"编辑器会话缓存键"，与草稿修订序号一一对应：
  修订号变 → 新 key → DS 强制丢弃旧文档缓存并重新拉取文件，
  杜绝 DS 用旧缓存覆盖新落盘内容。
- 回调 JWT 载荷必须含 status（真实 DS 回调对整个 body 签名必含）；
  编辑配置 token 等非回调签名重放一律 403。权威回调内容（status/
  key/url/users）只取自载荷，未签名 body 仅用于冲突检测。
- 回调文件下载 URL 仅允许本服务提供的编辑器下载通道（配置了
  ONLYOFFICE_PUBLIC_BASE_URL 时必须以其开头），禁止任意 URL 取回。
- 修订号/角色/会话在保存前复核（save_draft_file 内行锁二次复核），
  迟到与过期回调不得覆盖新内容。
"""
import json
import logging
import os
import re
import tempfile
import uuid
from urllib.parse import urlparse, urlunparse

import requests as requests_lib
from django.conf import settings
from django.http import JsonResponse
from django.utils import timezone

from apps.account.models import User

from . import services, storage
from .authorization_services import can_edit_file
from .models import ManualDraft, ManualEditSession
from .onlyoffice_jwt import sign_payload, verify_token
from .services import (ACTION_SAVE_DRAFT, log_operation, save_file_draft,
                       touch_session)

logger = logging.getLogger(__name__)

# 回调状态（ONLYOFFICE 官方协议）
CB_STATUS_EDITING = 1            # 用户正在编辑（连接后周期性心跳）
CB_STATUS_FORCE_SAVE = 2         # 强制保存（forcesave）或文档关闭且有修改（最终版）
CB_STATUS_FORCE_SAVE_ERROR = 3   # 强制保存出错
CB_STATUS_CLOSED_NO_CHANGES = 4  # 文档关闭且无修改
CB_STATUS_SAVE = 6               # 文档关闭且有修改
CB_STATUS_SAVE_ERROR = 7         # 文档关闭且修改保存出错

# 回调 body 最大字节数（真实回调只含元数据不含文件内容；
# 防伪造超大请求）
MAX_CALLBACK_BODY_BYTES = 1024 * 1024

# document.key 格式：oo-<manual_id>-f<file_id>-r<revision>-<uuid8>
DOC_KEY_RE = re.compile(r'^oo-(\d+)-f(\d+)-r(\d+)-[0-9a-f]{8}$')

# 回调文件下载超时与块大小
CALLBACK_DOWNLOAD_TIMEOUT_SECONDS = 60


def is_editor_configured():
    """ONLYOFFICE 服务地址与 JWT 密钥均已配置才视为可用"""
    return bool(
        getattr(settings, 'ONLYOFFICE_DOCS_URL', '') and
        getattr(settings, 'ONLYOFFICE_JWT_SECRET', ''))


def build_document_key(manual_id, file_id, revision):
    """制度+文件+草稿修订号 -> 编辑器文档缓存键（公开可曝光，不含敏感信息）"""
    return f'oo-{manual_id}-f{file_id}-r{revision}-{uuid.uuid4().hex[:8]}'


def parse_document_key(doc_key):
    """从 document.key 还原 (manual_id, file_id, revision)；非法返回 None"""
    match = DOC_KEY_RE.match(doc_key or '')
    if not match:
        return None
    return int(match.group(1)), int(match.group(2)), int(match.group(3))


def public_base_url(request):
    """回调/下载用的对外可达基址（DS 容器回源地址）

    优先 ONLYOFFICE_PUBLIC_BASE_URL；未配置时按请求 Host 推导。
    DS 在容器网络内，生产必须显式配置（compose 已默认）。
    """
    configured = getattr(settings, 'ONLYOFFICE_PUBLIC_BASE_URL', '')
    if configured:
        return configured.rstrip('/')
    scheme = 'https' if request.is_secure() else 'http'
    return f'{scheme}://{request.get_host()}'


def build_editor_download_url(request, manual, file_entry, draft):
    """生成编辑器取文件地址（绝对 URL，DS 容器需能访问）

    editor_token 绑定 制度+文件+草稿修订序号+签发人，走专用认证通道
    （AUTHENTICATION_EXCLUDES + 视图内校验），有效期取
    ONLYOFFICE_EDITOR_TOKEN_TTL_SECONDS（默认 1h，覆盖长编辑会话；
    修订号变化即失效）。
    """
    from .views_draft import build_editor_token
    token = build_editor_token(manual, file_entry, draft, request.user)
    return (
        f'{public_base_url(request)}/api/institution/manuals/{manual.id}/'
        f'files/{file_entry.id}/attachments/oo-editor-file/?token={token}'
    )


def build_editor_config(request, manual, file_entry, draft, session):
    """生成前端 DocsAPI.DocEditor(config) 所需配置（含 JWT）

    全链路绑定具体文件：document.key 含文件 ID，取文件与回调 URL 均为
    文件级路由。document.key 记录到会话（current_doc_key）：同一会话
    重新取配置即换 key，旧编辑实例的迟到回调因 key 不匹配被拒；同一
    编辑实例的后续 forcesave 回调携带同一 key，不受中间修订号变化影响。
    """
    revision = draft.revision
    doc_key = build_document_key(manual.id, file_entry.id, revision)
    session.current_doc_key = doc_key
    session.save(update_fields=['current_doc_key'])
    config = {
        'documentType': 'word',
        'document': {
            'fileType': 'docx',
            'key': doc_key,
            'title': file_entry.display_name or 'draft.docx',
            'url': build_editor_download_url(request, manual, file_entry, draft),
            'permissions': {
                'edit': True,
                'download': True,
                'print': True,
            },
        },
        'editorConfig': {
            'callbackUrl': (
                f'{public_base_url(request)}/api/institution/manuals/'
                f'{manual.id}/files/{file_entry.id}/attachments/'
                f'oo-editor-callback/'),
            'lang': getattr(request, 'LANGUAGE_CODE', None) or 'zh-CN',
            'mode': 'edit',
            'customization': {
                'forcesave': True,
                'compactHeader': True,
                'hideRightMenu': True,
            },
            'user': {
                'id': str(session.user_id),
                'name': session.user.username if session.user else '',
            },
        },
    }
    token = sign_payload(
        {'document': config['document'], 'editorConfig': config['editorConfig']},
        settings.ONLYOFFICE_JWT_SECRET)
    return {
        'editor_available': True,
        'editor_type': 'onlyoffice',
        'editor_api_url': (
            f"{settings.ONLYOFFICE_DOCS_URL.rstrip('/')}/web-apps/apps/api/"
            f'documents/api.js'),
        'document_key': doc_key,
        'revision': revision,
        'config': config,
        'token': token,
        'expires_in': getattr(settings, 'ONLYOFFICE_EDITOR_TOKEN_TTL_SECONDS', 3600),
    }


def _unwrap_ds_header_payload(payload):
    """按签名为准解包 DS Authorization 头令牌的 {"payload": {...}} 包裹

    DS（10.0 延续此形态）的头令牌把回调内容包一层 payload 并附 iat/exp（body.token 才是
    平铺签名）。两种格式均为 DS 对回调内容的签名；不含 status 且不满足
    包裹格式的签名（如编辑配置 token 重放）原样返回、由调用方拒绝。
    """
    if 'status' not in payload and isinstance(payload.get('payload'), dict):
        return payload['payload']
    return payload


def parse_callback_request(request):
    """解析回调请求：JSON body + JWT（Authorization: Bearer 优先，body.token 兜底）

    ONLYOFFICE 对整个回调 body 签名，真实回调的 JWT 载荷必含 status。
    不含 status 的合法签名（典型如编辑配置 token 被重放）一律 403 拒绝，
    杜绝"以未签名 body 冒充回调内容"的绕过。
    Returns:
        tuple: (jwt_payload dict（必含 status）, body dict, 错误 JsonResponse 或 None)
    """
    content_type = (request.content_type or '').lower()
    if content_type and 'application/json' not in content_type:
        return None, None, JsonResponse({'error': 1}, status=400)
    if len(request.body or b'') > MAX_CALLBACK_BODY_BYTES:
        logger.warning('[InstitutionEditor] callback body too large: %s',
                       len(request.body))
        return None, None, JsonResponse({'error': 1}, status=400)
    try:
        body = json.loads(request.body.decode('utf-8'))
    except (ValueError, UnicodeDecodeError):
        return None, None, JsonResponse({'error': 1}, status=400)
    if not isinstance(body, dict):
        return None, None, JsonResponse({'error': 1}, status=400)
    auth_header = request.headers.get('Authorization', '')
    token = ''
    if auth_header.lower().startswith('bearer '):
        token = auth_header[7:].strip()
    if not token:
        token = str(body.get('token') or '')
    payload = verify_token(token, settings.ONLYOFFICE_JWT_SECRET) if token else None
    if payload is None:
        logger.warning('[InstitutionEditor] callback JWT invalid or missing')
        return None, None, JsonResponse({'error': 1}, status=403)
    payload = _unwrap_ds_header_payload(payload)
    if 'status' not in payload:
        logger.warning('[InstitutionEditor] callback JWT payload without status '
                       'rejected (config token replay or forged scope)')
        return None, None, JsonResponse({'error': 1}, status=403)
    return payload, body, None


def authoritative_callback_body(payload, body):
    """以 JWT payload 为权威回调内容；body 与 payload 的 status 冲突即拒绝

    前置：parse_callback_request 已保证 payload 含 status。users/key/url
    等回调字段一律取自载荷（签名为准），不读未签名 body。
    Returns:
        tuple: (权威 body dict 或 None, None 或 JsonResponse)
    """
    if 'status' in body and str(body.get('status')) != str(payload.get('status')):
        logger.warning('[InstitutionEditor] callback status mismatch between '
                       'body and JWT payload')
        return None, JsonResponse({'error': 1}, status=400)
    return payload, None


def _parse_callback_user_ids(payload):
    """从 JWT 载荷解析参与者账号 ID（官方协议 users 数组，uid- 前缀剥离）

    载荷即 DS 签名的完整回调 body，归属账号以签名为准。
    """
    ids = []
    for raw in payload.get('users') or []:
        text = str(raw)
        if text.startswith('uid-'):
            text = text[len('uid-'):]
        try:
            ids.append(int(text))
        except ValueError:
            continue
    return ids


def _allowed_callback_origins():
    """回调文件下载允许的主机名集合（按主机名比较，忽略端口）

    ONLYOFFICE 回调的 url 指向文档服务器自己的缓存文件；允许来源取
    ONLYOFFICE_ALLOWED_URL_HOSTS（显式配置，须含 DS 容器自身主机名）
    及 ONLYOFFICE_DOCS_URL / ONLYOFFICE_PUBLIC_BASE_URL 的主机名。
    """
    hosts = set(getattr(settings, 'ONLYOFFICE_ALLOWED_URL_HOSTS', None) or [])
    for attr in ('ONLYOFFICE_DOCS_URL', 'ONLYOFFICE_PUBLIC_BASE_URL'):
        value = getattr(settings, attr, '')
        if value:
            host = urlparse(value).hostname
            if host:
                hosts.add(host.lower())
    return hosts


def _callback_direct_url(url, parsed):
    """把回调 url 改写为 compose 网络内 DS 容器直连地址（http）。

    回调 url 的 host 是 DS 从浏览器请求推断的外部地址——浏览器经 HTTPS
    自签证书访问时，该 url 即 https+自签形态，后端容器内回流下载会撞
    证书校验（SSLCertVerificationError），dev 为 HTTP 故历史上未暴露。
    DS 缓存路径固定带浏览器同源代理前缀（/onlyoffice/），DS 容器自身
    nginx 无此前缀，改写 = scheme 换 http、host 换 DS 容器名、path 去前缀。
    调用前原 url 已过 _allowed_callback_origins 白名单（SSRF 防线）；
    改写目标仅为受信内网 DS 容器，md5/expires/shardkey 等防篡改参数
    原样保留。非同源代理形态（path 无前缀）不改写、按原 url 下载。
    """
    path = parsed.path
    prefix = '/onlyoffice'
    if path != prefix and not path.startswith(prefix + '/'):
        return url
    base = (getattr(settings, 'ONLYOFFICE_DIRECT_DOWNLOAD_BASE_URL', '')
            or 'http://tdyw-onlyoffice')
    parsed_base = urlparse(base)
    path = path[len(prefix):] or '/'
    return urlunparse(('http', parsed_base.netloc, path, parsed.params,
                       parsed.query, ''))


def _extract_callback_file(body):
    """把回调 url 指向的文档内容取回本地临时文件

    安全约束：url 仅允许来自 ONLYOFFICE 文档服务自身主机（scheme
    限 http/https），禁止任意 URL 取回/SSRF；大小受 MAX_FILE_SIZE 限制。
    Returns:
        tuple: (临时文件绝对路径 或 None, 错误消息 或 None)
    """
    url = str(body.get('url') or '')
    if not url:
        return None, '回调缺少文件地址'
    parsed = urlparse(url)
    if parsed.scheme not in ('http', 'https'):
        logger.warning('[InstitutionEditor] callback url bad scheme: %s',
                       url[:200])
        return None, '回调文件地址不合法'
    allowed = _allowed_callback_origins()
    if not allowed or (parsed.hostname or '').lower() not in allowed:
        logger.warning('[InstitutionEditor] callback url outside DS origin: %s',
                       url[:200])
        return None, '回调文件地址不合法'
    try:
        download_url = _callback_direct_url(url, parsed)
        resp = requests_lib.get(download_url,
                                timeout=CALLBACK_DOWNLOAD_TIMEOUT_SECONDS,
                                stream=True, allow_redirects=False)
    except requests_lib.RequestException as e:
        logger.warning('[InstitutionEditor] download callback file failed: %s', e)
        return None, '下载编辑器文件失败'
    if resp.status_code != 200:
        resp.close()
        return None, '下载编辑器文件失败'
    tmp = tempfile.NamedTemporaryFile(prefix='oo_cb_', suffix='.docx',
                                      delete=False)
    size = 0
    keep = False
    try:
        for chunk in resp.iter_content(chunk_size=512 * 1024):
            if not chunk:
                continue
            size += len(chunk)
            if size > storage.MAX_FILE_SIZE:
                return None, '编辑器文件超过大小限制'
            tmp.write(chunk)
        tmp.close()
        keep = True
        return tmp.name, None
    finally:
        # 连接始终释放；未成功返回路径的临时文件一律清理（防 /tmp 残留）
        resp.close()
        if not keep:
            try:
                tmp.close()
                os.remove(tmp.name)
            except OSError:
                pass


class _CallbackFileWrapper:
    """把已落盘的临时文件包装成 Django UploadedFile 语义（name/chunks）"""

    def __init__(self, path, name='callback.docx'):
        self.path = path
        self.name = name

    def chunks(self, chunk_size=64 * 1024):
        with open(self.path, 'rb') as f:
            while True:
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                yield chunk


def _resolve_final_callback_session(file_entry, payload, user_ids):
    """撤销后收尾回调的受控放行（discard=false 撤销的同一编辑实例）

    DS 在编辑器关闭时会补发一次收尾回调（status 2/6）；当它晚于
    "保存并结束编辑"确认成功后的会话撤销到达（实测约 1 秒）时，
    若撤销时声明 discard=False，允许该回调落盘——否则用户在 forcesave
    复核之后、编辑器销毁之前的最后一次修改将丢失（重开后 document key
    已轮换，丢失不可恢复）。防线全部保留：

    - 仅收尾状态 status 2/6（调用方状态机已筛，此处防御性复核）；
    - 回调 key == 该已撤销会话的 current_doc_key（同一编辑实例；
      会话最终签发的 key，多标签轮换后的旧 key 不放行）；
    - 该会话仍是本文件最新一条会话记录（撤销后本人/他人重开产生新
      会话则旧回调照旧拒绝，防陈旧实例覆盖）；
    - 会话归属账号在回调 users 载荷内且当前有效（is_active）。

    批量失效（密码重置/整套回退/草稿恢复）不置 final_callback_allowed，
    收尾回调照旧拒绝。
    Returns:
        tuple: (user, session) 或 (None, None)
    """
    if str(payload.get('status')) not in (str(CB_STATUS_FORCE_SAVE),
                                          str(CB_STATUS_SAVE)):
        return None, None
    callback_key = str(payload.get('key') or '')
    if not callback_key:
        return None, None
    latest = ManualEditSession.objects.filter(
        file=file_entry).order_by('-id').first()
    if (not latest or latest.revoked_at is None
            or not latest.final_callback_allowed
            or latest.current_doc_key != callback_key
            or latest.user_id not in user_ids):
        return None, None
    return User.objects.filter(
        pk=latest.user_id, is_active=True).first(), latest


def _resolve_callback_writer(manual, file_entry, payload):
    """回调归属与会话/角色/归档/key 防护校验（全部以 JWT 载荷为准）

    会话按 制度+文件+账号 定位：同一制度不同文件的会话互不干扰，
    同一文件同时仅一个活跃会话。无活跃会话时尝试收尾回调放行
    （discard=false 撤销的同一编辑实例，见
    _resolve_final_callback_session）。
    Returns:
        tuple: (user, session, 错误 JsonResponse 或 None)
    """
    # 参与者归属：users 数组（JWT 载荷签名保证不可伪造）；无活跃会话不得落盘
    user_ids = _parse_callback_user_ids(payload)
    now = timezone.now()
    user = session = None
    for user_id in user_ids:
        candidate = User.objects.filter(pk=user_id, is_active=True).first()
        if not candidate:
            continue
        found = ManualEditSession.objects.filter(
            manual=manual, file=file_entry, user=candidate,
            revoked_at__isnull=True, expires_at__gt=now,
        ).order_by('-id').first()
        if found:
            user, session = candidate, found
            break
    if not user:
        # 收尾回调放行：discard=false 撤销的同一编辑实例（同 key）的
        # 收尾 status-2/6 回调仍允许落盘；其余情况照旧拒绝
        user, session = _resolve_final_callback_session(
            file_entry, payload, user_ids)
    if not user:
        logger.warning('[InstitutionEditor] callback without active session '
                       'manual=%s file=%s users=%s',
                       manual.id, file_entry.id, user_ids)
        return None, None, JsonResponse({'error': 1}, status=403)
    if not can_edit_file(user, manual, file_entry):
        logger.warning('[InstitutionEditor] callback user %s lost edit '
                       'grant or file ownership on manual %s file %s',
                       user.id, manual.id, file_entry.id)
        return None, None, JsonResponse({'error': 1}, status=403)
    if manual.status != 'active':
        logger.warning('[InstitutionEditor] callback on archived manual %s',
                       manual.id)
        return None, None, JsonResponse({'error': 1}, status=409)

    # 迟到/旧编辑实例防护：回调 key 以 JWT 载荷为准（签名的 body 才可信），
    # 且必须等于该文件会话当前签发的 key。
    # 会话重新取配置（多标签/刷新）即换 key，旧实例回调在此被拒；
    # 同一编辑实例的重复/后续 forcesave 携带同一 key，不受影响。
    callback_key = str(payload.get('key') or '')
    if not callback_key or callback_key != session.current_doc_key:
        logger.warning('[InstitutionEditor] stale callback key rejected '
                       'manual=%s file=%s key=%s expected=%s',
                       manual.id, file_entry.id, callback_key[:40],
                       session.current_doc_key[:40])
        return None, None, JsonResponse({'error': 1}, status=409)
    return user, session, None


def _warn_notmodified_hash_mismatch(body, draft, new_hash):
    """notmodified:true 但交付字节哈希不等的观测告警（缺陷 B，纯日志）

    DS 自我声明无新修改（notmodified:true）但交付字节哈希与已落盘草稿
    不等——DS 侧组装不确定性的直接信号（dev 实测该形态被当新内容虚增
    修订号）。记录 key/修订号/双哈希前 12 位供根因定位；落盘判定仍以
    内容哈希为唯一权威，是否保存与修订号行为不受本日志影响。
    """
    if body.get('notmodified') is not True:
        return
    logger.warning(
        '[InstitutionEditor] callback bytes differ despite '
        'notmodified=true: key=%s revision=%s landed_hash=%s '
        'incoming_hash=%s notmodified=%s',
        body.get('key'), draft.revision,
        str(draft.file_hash or '')[:12], str(new_hash or '')[:12],
        body.get('notmodified'))


def process_editor_callback(manual, file_entry, payload, body):
    """处理已通过 JWT 校验的回调 body（状态机 + 文件级保存）

    调用方必须先核对 payload.key 解析出的 manual/file 与路由一致。
    返回 JsonResponse（ONLYOFFICE 期望 {"error": 0} 表示成功）。
    """
    body, err = authoritative_callback_body(payload, body)
    if err:
        return err
    try:
        status = int(body.get('status'))
    except (TypeError, ValueError):
        return JsonResponse({'error': 1}, status=400)

    if status in (CB_STATUS_EDITING, CB_STATUS_CLOSED_NO_CHANGES,
                  CB_STATUS_FORCE_SAVE_ERROR, CB_STATUS_SAVE_ERROR):
        # 1=编辑心跳（频繁，只回成功）；3/7=DS 侧保存失败（无内容可落盘），
        # 记录日志供排查，不作为业务失败返回。
        if status in (CB_STATUS_FORCE_SAVE_ERROR, CB_STATUS_SAVE_ERROR):
            logger.warning('[InstitutionEditor] DS reported save failure '
                           'status=%s manual=%s file=%s',
                           status, manual.id, file_entry.id)
        return JsonResponse({'error': 0})

    if status not in (CB_STATUS_FORCE_SAVE, CB_STATUS_SAVE):
        return JsonResponse({'error': 1}, status=400)

    user, session, err = _resolve_callback_writer(manual, file_entry, payload)
    if err:
        return err

    # 冻结门（2026-11-03）：该文件已提交待发布核对时，任何回调内容都不得
    # 写入草稿或覆盖快照（含"保存并结束编辑"后的迟到收尾回调）。在下载
    # 回调文件前拒绝，避免无谓外呼与临时文件；save_file_draft 行锁内还有
    # 二次冻结复核，双保险。
    if services.file_is_frozen(file_entry):
        logger.warning('[InstitutionEditor] callback rejected, submission '
                       'pending manual=%s file=%s', manual.id, file_entry.id)
        return JsonResponse({'error': 1}, status=409)

    file_path, fetch_err = _extract_callback_file(body)
    if fetch_err:
        logger.warning('[InstitutionEditor] callback file fetch rejected: %s',
                       fetch_err)
        return JsonResponse({'error': 1}, status=400)
    try:
        draft = ManualDraft.objects.filter(file=file_entry).first()
        if not draft:
            return JsonResponse({'error': 1}, status=409)
        # 重复回调幂等：内容哈希与该文件当前草稿一致则不重复保存
        # （修订号不虚增）
        new_hash = storage.compute_file_hash(file_path)
        if new_hash and new_hash == draft.file_hash:
            touch_session(session)
            return JsonResponse({'error': 0})
        # 缺陷 B 观测增强（2026-10-31，纯日志零行为变化）：见助手 docstring
        _warn_notmodified_hash_mismatch(body, draft, new_hash)
        # expected_revision 在此处读取，save_file_draft 内 select_for_update
        # 行锁下二次复核修订号，并发回调不会交错覆盖
        draft, save_err = save_file_draft(
            file_entry, user,
            _CallbackFileWrapper(
                file_path,
                name=storage.display_name(f'{file_entry.display_name}')),
            draft.revision)
        if save_err:
            # 修订号已被推进（如同账号另一标签页 multipart 保存）：
            # 本次内容按旧修订处理拒绝；回 error:0 终止 DS 重试风暴
            logger.warning('[InstitutionEditor] callback save rejected: %s',
                           save_err)
            return JsonResponse({'error': 0})
        touch_session(session)
        log_operation(manual, user, ACTION_SAVE_DRAFT, file=file_entry,
                      file_id=file_entry.id, via='onlyoffice_callback',
                      file_revision=draft.revision)
        return JsonResponse({'error': 0})
    finally:
        try:
            os.remove(file_path)
        except (OSError, UnboundLocalError):
            pass


# ---------------------------------------------------------------------------
# Command Service forcesave（"保存并结束编辑"的落盘确认起点）

# DS Command Service 端点（2026-10-31 起 10.0 专用）：DS 8.2+ 为 /command。
# 应用层不再兼容 8.1 等旧版的 /coauthoring/CommandService.ashx——回退到
# 8.1 需连同后端代码一起回退（旧数据卷仍保留，仅作数据保险）。
COMMAND_PATH = '/command'
COMMAND_TIMEOUT_SECONDS = 10

# Command Service 响应错误码（官方协议）
CMD_ERROR_OK = 0                # forcesave 已受理，随后经回调链路落盘
CMD_ERROR_NO_CHANGES = 4        # 文档自上次保存后无修改，无需落盘
CMD_ERROR_KEY_NOT_FOUND = 1     # 文档键不存在（文档已在 DS 侧关闭/失效）


def command_base_url():
    """后端调用 DS Command Service 的可达基址

    显式 ONLYOFFICE_COMMAND_BASE_URL 优先；否则 ONLYOFFICE_DOCS_URL 为绝对
    地址时直接使用；为 /onlyoffice 等 nginx 同源代理路径时取
    ONLYOFFICE_PUBLIC_BASE_URL + 该路径（代理会剥离前缀转发到 DS）。
    不可推导返回 ''（调用方按未配置降级，不发起请求）。
    """
    explicit = getattr(settings, 'ONLYOFFICE_COMMAND_BASE_URL', '')
    if explicit:
        return explicit.rstrip('/')
    docs_url = (getattr(settings, 'ONLYOFFICE_DOCS_URL', '') or '').rstrip('/')
    if not docs_url:
        return ''
    if docs_url.startswith(('http://', 'https://')):
        return docs_url
    public_base = (getattr(settings, 'ONLYOFFICE_PUBLIC_BASE_URL', '') or '').rstrip('/')
    if not public_base:
        return ''
    return f'{public_base}{docs_url}'


def _post_command(base_url, payload):
    """POST Command Service /command 请求（DS 8.2+/10.x 端点）

    返回 (data dict 或 None, 错误消息或 None)。网络失败/非 JSON 响应
    一律视为失败，由调用方决定降级文案；应答语义以 JSON 内 error 码
    为准（HTTP 状态不冒充成功）。
    """
    body = dict(payload)
    try:
        token = sign_payload(
            {'c': payload['c'], 'key': payload['key']},
            settings.ONLYOFFICE_JWT_SECRET)
    except Exception:
        return None, '文档服务签名失败，请检查 ONLYOFFICE_JWT_SECRET 配置'
    body['token'] = token
    headers = {'Authorization': f'Bearer {token}'}
    try:
        resp = requests_lib.post(
            f'{base_url}{COMMAND_PATH}', json=body, headers=headers,
            timeout=COMMAND_TIMEOUT_SECONDS)
    except requests_lib.RequestException as e:
        logger.warning('[InstitutionEditor] command request failed: %s', e)
        return None, '文档服务保存请求失败，请检查文档服务后重试'
    try:
        return resp.json(), None
    except ValueError:
        logger.warning('[InstitutionEditor] command response not JSON '
                       'status=%s', resp.status_code)
        return None, '文档服务保存请求响应异常，请稍后重试'


def request_forcesave(session):
    """请求 DS 立即保存当前编辑文档（Command Service forcesave）

    DS 受理后向文档的 callbackUrl 发送 status=2 回调，由既有回调链路
    落盘并推进修订号——落盘确认由前端轮询修订号完成，本函数只负责
    触发与传达 DS 的即时应答。

    Returns:
        tuple: ({'forcesave': 'requested'|'no_changes'}, None) 或
               (None, 错误消息)。'no_changes'=DS 报告无修改，可安全结束。
    """
    base_url = command_base_url()
    if not base_url:
        return None, '在线编辑服务未配置，无法请求文档服务保存'
    doc_key = (session.current_doc_key or '').strip()
    if not doc_key:
        return None, '该会话没有进行中的在线编辑文档，无需保存确认'
    data, err = _post_command(base_url, {'c': 'forcesave', 'key': doc_key})
    if err:
        return None, err
    code = data.get('error') if isinstance(data, dict) else None
    if code == CMD_ERROR_OK:
        return {'forcesave': 'requested'}, None
    if code == CMD_ERROR_NO_CHANGES:
        return {'forcesave': 'no_changes'}, None
    # 1=文档键不存在（编辑器已关闭/DS 重启，无法再确认）等：不得冒充成功
    logger.warning('[InstitutionEditor] forcesave command rejected code=%s '
                   'key=%s', code, doc_key[:40])
    return None, '文档服务无法受理保存请求，请在编辑器内按 Ctrl+S 保存后重试'
