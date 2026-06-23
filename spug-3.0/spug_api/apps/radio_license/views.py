# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
import os
import logging
from django.views.generic import View
from django.utils import timezone
from django.conf import settings
from django.http import FileResponse
from urllib.parse import quote
from libs import json_response, JsonParser, Argument, human_datetime, auth
from libs.tenant_utils import apply_tenant_filter, assign_tenant_id
from apps.radio_license.models import (
    RadioLicense, RadioLicenseFrequency, RadioLicenseAttachment,
    RadioLicenseReminder, LicenseReminderAck, REMIND_TYPE_MAP,
    ALLOWED_FILE_EXTENSIONS, MAX_FILE_SIZE_MB,
    EXPIRING_DAYS_THRESHOLD,
)
from apps.radio_license.tasks import scan_single_license
import json

logger = logging.getLogger(__name__)


class RadioLicenseView(View):
    """执照列表 / 新增编辑 / 删除"""

    @auth('radio_license.license.view')
    def get(self, request):
        records = apply_tenant_filter(RadioLicense.objects.all(), request.user)

        # 筛选参数
        station_name = request.GET.get('station_name', '')
        purpose = request.GET.get('purpose', '')
        status = request.GET.get('status', '')
        valid_to_start = request.GET.get('valid_to_start', '')
        valid_to_end = request.GET.get('valid_to_end', '')

        if station_name:
            records = records.filter(station_name__icontains=station_name)
        if purpose:
            records = records.filter(purpose__icontains=purpose)
        if status:
            records = records.filter(status=status)
        if valid_to_start:
            records = records.filter(valid_to__gte=valid_to_start)
        if valid_to_end:
            records = records.filter(valid_to__lte=valid_to_end)

        # 分页
        page = int(request.GET.get('page', 1))
        page_size = int(request.GET.get('page_size', 20))

        records = records.select_related('created_by', 'updated_by')
        total_count = records.count()
        offset = (page - 1) * page_size
        records = records[offset:offset + page_size]

        # 构造返回数据，附带频率信息和计算字段
        data = []
        for record in records:
            item = record.to_view()
            # 附加频率列表
            freqs = RadioLicenseFrequency.objects.filter(license=record).order_by('sort_order', 'id')
            item['frequencies'] = [f.to_view() for f in freqs]
            # 附件数量
            item['attachment_count'] = RadioLicenseAttachment.objects.filter(license=record).count()
            # 计算剩余天数和状态（与 BadgeView 的 60 天规则保持一致）
            today = timezone.now().date()
            days_left = (record.valid_to - today).days
            if days_left < 0:
                computed_status = 'expired'
            elif days_left <= EXPIRING_DAYS_THRESHOLD:
                computed_status = 'expiring'
            else:
                computed_status = 'normal'
            item['days_left'] = days_left
            item['computed_status'] = computed_status
            data.append(item)

        return json_response({
            'records': data,
            'total': total_count,
            'page': page,
            'page_size': page_size,
        })

    @auth('radio_license.license.add|radio_license.license.edit')
    def post(self, request):
        form, error = JsonParser(
            Argument('id', type=int, required=False),
            Argument('station_name', help='请输入台站名称'),
            Argument('purpose', help='请输入用途'),
            Argument('valid_from', help='请选择起始日期'),
            Argument('valid_to', help='请选择截止日期'),
            Argument('responsible_user_id', type=int, help='请选择责任人'),
            Argument('responsible_user_name', help='请选择责任人'),
            Argument('remark', required=False),
            Argument('frequencies', type=list, required=False, help='频率列表'),
        ).parse(request.body)

        if error is None:
            # 责任人账号存在性校验（强绑定，不允许填错或填已禁用的用户）
            from apps.account.models import User as UserModel
            if not UserModel.objects.filter(
                pk=form.responsible_user_id, is_active=True
            ).exists():
                return json_response(error='责任人不存在或已禁用，请重新选择')
            # 自动用当前真实姓名回填（避免前端拼错或传旧名字）
            user = UserModel.objects.get(pk=form.responsible_user_id)
            form.responsible_user_name = user.nickname or user.username

            # 日期校验：起始日期不能晚于截止日期
            if form.valid_from and form.valid_to:
                if form.valid_from > form.valid_to:
                    return json_response(error='起始日期不能晚于截止日期')

            frequencies = form.pop('frequencies', []) if hasattr(form, 'frequencies') else []

            if form.id:
                # 编辑模式：先取旧 valid_to，用于判断是否需要作废旧提醒
                qs = apply_tenant_filter(RadioLicense.objects.all(), request.user)
                old_license = qs.filter(pk=form.id).only('valid_to').first()
                old_valid_to = old_license.valid_to if old_license else None

                form.updated_at = human_datetime()
                form.updated_by = request.user
                record_id = form.pop('id')
                form.pop('remark', None)
                updated_count = qs.filter(pk=record_id).update(**form)
                if updated_count == 0:
                    error = '编辑失败：记录不存在或无权限编辑'
                else:
                    # 更新频率明细
                    _update_frequencies(record_id, frequencies, request.user)
                    license_obj = RadioLicense.objects.get(pk=record_id)
                    # 执照中心模型：ack 按 ack_valid_to 自动失效，无需手动作废旧提醒
                    # 即时扫描：更新 license.status（不再预生成 reminder）
                    scan_single_license(license_obj)
            else:
                # 新增模式
                form.created_by = request.user
                form.pop('remark', None)
                assign_tenant_id(form, request.user)
                license_obj = RadioLicense.objects.create(**form)
                # 创建频率明细
                _create_frequencies(license_obj, frequencies, request.user)
                # 即时扫描：更新状态 + 生成提醒
                scan_single_license(license_obj)

        return json_response(error=error)

    @auth('radio_license.license.del')
    def delete(self, request):
        form, error = JsonParser(
            Argument('id', type=int, help='请指定操作对象')
        ).parse(request.GET)
        if error is None:
            qs = apply_tenant_filter(RadioLicense.objects.all(), request.user)
            license_obj = qs.filter(pk=form.id).first()
            if not license_obj:
                error = '删除失败：记录不存在或无权限删除'
            else:
                # 先删除关联附件的物理文件（CASCADE 会自动删 DB 记录，但磁盘文件需手动清理）
                attachments = RadioLicenseAttachment.objects.filter(license_id=form.id)
                for att in attachments:
                    full_path = os.path.join(settings.MEDIA_ROOT, att.file_path)
                    try:
                        if os.path.exists(full_path):
                            os.remove(full_path)
                    except OSError as e:
                        logger.warning(f'[RadioLicense] 删除附件文件失败: {e}')
                # 物理删除执照（CASCADE 自动级联删除频率/附件/提醒记录）
                license_obj.delete()
        return json_response(error=error)


class RadioLicenseDetailView(View):
    """执照详情"""

    @auth('radio_license.license.view')
    def get(self, request, pk):
        qs = apply_tenant_filter(RadioLicense.objects.all(), request.user)
        try:
            record = qs.get(pk=pk)
        except RadioLicense.DoesNotExist:
            return json_response(error='记录不存在或无权限访问')

        item = record.to_view()
        # 附加频率列表
        freqs = RadioLicenseFrequency.objects.filter(license=record).order_by('sort_order', 'id')
        item['frequencies'] = [f.to_view() for f in freqs]
        # 计算剩余天数和状态（与 BadgeView 的 60 天规则保持一致）
        today = timezone.now().date()
        days_left = (record.valid_to - today).days
        if days_left < 0:
            computed_status = 'expired'
        elif days_left <= EXPIRING_DAYS_THRESHOLD:
            computed_status = 'expiring'
        else:
            computed_status = 'normal'
        item['days_left'] = days_left
        item['computed_status'] = computed_status
        # 附件数量
        item['attachment_count'] = RadioLicenseAttachment.objects.filter(license=record).count()
        # 提醒数量
        item['reminder_count'] = RadioLicenseReminder.objects.filter(license=record).count()

        return json_response(item)


def _create_frequencies(license_obj, frequencies, user):
    """创建频率明细"""
    for idx, freq_data in enumerate(frequencies):
        RadioLicenseFrequency.objects.create(
            tenant_id=license_obj.tenant_id,
            license=license_obj,
            frequency_value=freq_data.get('frequency_value', 0),
            frequency_unit=freq_data.get('frequency_unit', 'MHz'),
            frequency_text=freq_data.get('frequency_text', ''),
            remark=freq_data.get('remark', ''),
            sort_order=freq_data.get('sort_order', idx),
            created_by=user,
        )


def _update_frequencies(license_id, frequencies, user):
    """更新频率明细：先删后建"""
    license_obj = RadioLicense.objects.get(pk=license_id)
    RadioLicenseFrequency.objects.filter(license_id=license_id).delete()
    _create_frequencies(license_obj, frequencies, user)


# ==================== 附件接口 ====================

ATTACHMENT_UPLOAD_DIR = 'radio_license/attachments'


class AttachmentListView(View):
    """附件列表 / 上传"""

    @auth('radio_license.license.view')
    def get(self, request, pk):
        """获取指定执照的附件列表"""
        # 校验执照存在且有权限
        qs = apply_tenant_filter(RadioLicense.objects.all(), request.user)
        if not qs.filter(pk=pk).exists():
            return json_response(error='执照不存在或无权限访问')

        attachments = RadioLicenseAttachment.objects.filter(license_id=pk)
        # 租户过滤：确保只返回当前租户的附件
        attachments = apply_tenant_filter(attachments, request.user).order_by('-created_at')
        data = []
        for att in attachments:
            item = att.to_view()
            item['uploaded_by_name'] = att.uploaded_by.nickname if att.uploaded_by else '-'
            data.append(item)
        return json_response(data)

    @auth('radio_license.attachment.upload')
    def post(self, request, pk):
        """上传附件"""
        # 校验执照存在且有权限
        qs = apply_tenant_filter(RadioLicense.objects.all(), request.user)
        license_obj = qs.filter(pk=pk).first()
        if not license_obj:
            return json_response(error='执照不存在或无权限访问')

        file = request.FILES.get('file')
        if not file:
            return json_response(error='请选择要上传的文件')

        # 文件类型校验
        _, ext = os.path.splitext(file.name)
        ext = ext.lower()
        if ext not in ALLOWED_FILE_EXTENSIONS:
            return json_response(error=f'不支持的文件类型，允许：{", ".join(ALLOWED_FILE_EXTENSIONS)}')

        # 文件大小校验
        if file.size > MAX_FILE_SIZE_MB * 1024 * 1024:
            return json_response(error=f'文件大小不能超过 {MAX_FILE_SIZE_MB}MB')

        # 文件名清洗（防路径穿越）
        safe_name = os.path.basename(file.name)
        # 移除潜在危险字符
        safe_name = safe_name.replace('..', '').replace('/', '').replace('\\', '').replace('\x00', '')
        if not safe_name:
            safe_name = f'attachment{ext}'

        # 生成存储路径
        date_path = timezone.now().strftime('%Y%m')
        save_dir = os.path.join(settings.MEDIA_ROOT, ATTACHMENT_UPLOAD_DIR, date_path)
        os.makedirs(save_dir, exist_ok=True)

        # 保留原始文件名，遇重名自动加序号（如 xxx.pdf → xxx_1.pdf）
        disk_name = safe_name
        file_path = os.path.join(save_dir, disk_name)
        counter = 1
        name_base, name_ext = os.path.splitext(safe_name)
        while os.path.exists(file_path):
            disk_name = f'{name_base}_{counter}{name_ext}'
            file_path = os.path.join(save_dir, disk_name)
            counter += 1

        # 保存文件
        try:
            with open(file_path, 'wb+') as destination:
                for chunk in file.chunks():
                    destination.write(chunk)
        except OSError as e:
            logger.error(f'[RadioLicense] 附件保存失败: {e}')
            return json_response(error='附件保存失败')

        # 创建数据库记录
        relative_path = f'{ATTACHMENT_UPLOAD_DIR}/{date_path}/{disk_name}'
        attachment_type = request.POST.get('attachment_type', 'other')
        if attachment_type not in ['license', 'permit', 'approval', 'other']:
            attachment_type = 'other'

        att = RadioLicenseAttachment.objects.create(
            tenant_id=license_obj.tenant_id,
            license=license_obj,
            attachment_type=attachment_type,
            file_name=safe_name,
            file_path=relative_path,
            file_size=file.size,
            file_ext=ext,
            uploaded_by=request.user,
        )
        result = att.to_view()
        result['uploaded_by_name'] = request.user.nickname
        return json_response(result)


class AttachmentDownloadView(View):
    """附件下载（鉴权）"""

    @auth('radio_license.attachment.download')
    def get(self, request, pk):
        """下载附件"""
        # 校验附件存在且属于当前租户
        qs = apply_tenant_filter(RadioLicenseAttachment.objects.all(), request.user)
        try:
            att = qs.get(pk=pk)
        except RadioLicenseAttachment.DoesNotExist:
            return json_response(error='附件不存在或无权限访问')

        # 校验关联执照存在且有权限
        license_qs = apply_tenant_filter(RadioLicense.objects.all(), request.user)
        if not license_qs.filter(pk=att.license_id).exists():
            return json_response(error='执照不存在或无权限访问')

        # 路径安全检查
        full_path = os.path.join(settings.MEDIA_ROOT, att.file_path)
        # 防止路径穿越
        media_real = os.path.realpath(settings.MEDIA_ROOT)
        file_real = os.path.realpath(full_path)
        if not file_real.startswith(media_real):
            logger.error(f'[RadioLicense] 路径穿越攻击: {att.file_path}')
            return json_response(error='文件不存在')

        if not os.path.exists(full_path):
            return json_response(error='文件不存在')

        # 流式下载
        encoded_filename = quote(att.file_name)
        response = FileResponse(
            open(full_path, 'rb'),
            content_type='application/octet-stream',
        )
        response['Content-Disposition'] = (
            f'attachment; filename="{encoded_filename}"; '
            f'filename*=UTF-8\'\'{encoded_filename}'
        )
        response['Content-Length'] = os.path.getsize(full_path)
        return response


class AttachmentDeleteView(View):
    """附件删除"""

    @auth('radio_license.attachment.upload')
    def delete(self, request):
        """删除附件"""
        form, error = JsonParser(
            Argument('id', type=int, help='请指定附件ID')
        ).parse(request.GET)
        if error is None:
            # 校验附件存在且属于当前租户
            qs = apply_tenant_filter(RadioLicenseAttachment.objects.all(), request.user)
            att = qs.filter(pk=form.id).first()
            if not att:
                return json_response(error='附件不存在或无权限删除')

            # 校验关联执照存在且有权限
            license_qs = apply_tenant_filter(RadioLicense.objects.all(), request.user)
            if not license_qs.filter(pk=att.license_id).exists():
                return json_response(error='执照不存在或无权限操作')

            # 删除物理文件
            full_path = os.path.join(settings.MEDIA_ROOT, att.file_path)
            try:
                if os.path.exists(full_path):
                    os.remove(full_path)
            except OSError as e:
                logger.warning(f'[RadioLicense] 删除附件文件失败: {e}')

            # 删除数据库记录
            att.delete()
        return json_response(error=error)


# ==================== 提醒接口 ====================

class ReminderListView(View):
    """提醒列表"""

    @auth('radio_license.license.view')
    def get(self, request):
        """获取当前用户的提醒列表（历史日志，只读）

        执照中心模型重构后，此接口返回 RadioLicenseReminder 历史记录供查阅。
        days_left 为生成时快照，前端展示时如需实时值应由弹窗接口提供。
        """
        # 只返回当前用户的提醒
        reminders = RadioLicenseReminder.objects.filter(
            receiver_user_id=request.user.id,
        )
        # 租户过滤
        reminders = apply_tenant_filter(reminders, request.user)

        # 筛选参数
        is_read = request.GET.get('is_read', '')
        is_handled = request.GET.get('is_handled', '')
        remind_type = request.GET.get('remind_type', '')

        if is_read == 'false':
            reminders = reminders.filter(is_read=False)
        elif is_read == 'true':
            reminders = reminders.filter(is_read=True)
        if is_handled == 'false':
            reminders = reminders.filter(is_handled=False)
        elif is_handled == 'true':
            reminders = reminders.filter(is_handled=True)
        if remind_type:
            reminders = reminders.filter(remind_type=remind_type)

        reminders = reminders.select_related('license').order_by('-created_at')

        # 分页
        page = int(request.GET.get('page', 1))
        page_size = int(request.GET.get('page_size', 20))

        total_count = reminders.count()
        offset = (page - 1) * page_size
        reminders = reminders[offset:offset + page_size]

        data = []
        for r in reminders:
            item = r.to_view()
            item['station_name'] = r.license.station_name if r.license else '-'
            item['valid_to'] = str(r.license.valid_to) if r.license else '-'
            data.append(item)
        return json_response({
            'records': data,
            'total': total_count,
            'page': page,
            'page_size': page_size,
        })


class ReminderPopupView(View):
    """弹窗提醒查询接口（执照中心模型）

    实时查询当前用户负责的 expiring/expired 执照，排除已 ack 的。
    days_left 实时计算，content 前端拼装，不依赖预生成数据。

    返回格式与旧 reminder 兼容（前端 ReminderNotification.js 无需大改）：
        records: [{
            license_id, station_name, valid_to, days_left, status, ...
        }]
    """

    @auth('radio_license.license.view')
    def get(self, request):
        from datetime import date, timedelta
        today = date.today()
        # 查询当前用户负责的、即将到期或已过期的执照
        qs = apply_tenant_filter(RadioLicense.objects.all(), request.user)
        licenses = qs.filter(
            responsible_user_id=request.user.id,
            valid_to__lte=today + timedelta(days=EXPIRING_DAYS_THRESHOLD),
        ).select_related('created_by')

        # 查询该用户所有 ack，构造 (license_id, ack_valid_to) 集合用于排除
        acks = LicenseReminderAck.objects.filter(
            user_id=request.user.id,
        ).values_list('license_id', 'ack_valid_to')
        ack_set = {(lid, vid) for lid, vid in acks}

        records = []
        for lic in licenses:
            days_left = (lic.valid_to - today).days
            # 排除已 ack 且 ack_valid_to 匹配当前 valid_to 的（续期后自动失效）
            if (lic.id, lic.valid_to) in ack_set:
                continue
            # 兼容旧 reminder 字段命名，前端无需改
            records.append({
                'license_id': lic.id,
                'station_name': lic.station_name,
                'valid_from': str(lic.valid_from),
                'valid_to': str(lic.valid_to),
                'days_left': days_left,
                'status': lic.status,
                'remind_type': 'expired' if days_left < 0 else 'expiring_daily',
            })
        return json_response({'records': records})


class ReminderAckView(View):
    """提醒确认（已处理）接口（执照中心模型）

    用户点击"已处理"→ 写一条 LicenseReminderAck
    续期后 license.valid_to 变化 → 旧 ack 自动失效 → 重新弹窗
    """

    @auth('radio_license.license.view')
    def post(self, request):
        form, error = JsonParser(
            Argument('license_id', type=int, help='执照ID'),
        ).parse(request.body)

        if error is not None:
            return json_response(error=error)

        # 校验执照存在且属于当前租户
        qs = apply_tenant_filter(RadioLicense.objects.all(), request.user)
        license_obj = qs.filter(pk=form.license_id).first()
        if not license_obj:
            return json_response(error='执照不存在或无权限')

        # 写入 ack（唯一约束会自动去重同周期重复确认）
        from django.db import IntegrityError
        try:
            LicenseReminderAck.objects.create(
                tenant_id=license_obj.tenant_id,
                license=license_obj,
                user_id=request.user.id,
                user_name=request.user.nickname or request.user.username,
                ack_valid_to=license_obj.valid_to,
            )
            logger.info(f'[RadioLicense] 用户 {request.user.id} 确认处理执照 {form.license_id} '
                        f'(valid_to={license_obj.valid_to})')
        except IntegrityError:
            # 同周期已确认过，幂等返回成功
            logger.debug(f'[RadioLicense] 执照 {form.license_id} 本周期已确认，跳过')

        return json_response(data={'license_id': form.license_id, 'acked': True})


class ReminderHandleView(View):
    """提醒处理（已读/已处理）- 兼容旧接口

    执照中心模型重构后，"已处理"功能由 ReminderAckView 承担。
    此接口保留"已读"功能供提醒记录页使用，"handle" action 转发到 ack 逻辑。
    """

    @auth('radio_license.reminder.handle')
    def post(self, request):
        form, error = JsonParser(
            Argument('id', type=int, required=False, help='提醒ID'),
            Argument('action', help='操作类型: read / handle / unread'),
            Argument('ids', type=list, required=False, help='批量操作ID列表'),
        ).parse(request.body)

        if error is not None:
            return json_response(error=error)

        ids = []
        if form.ids:
            ids = form.ids
        elif form.id:
            ids = [form.id]
        else:
            return json_response(error='请指定提醒ID')

        qs = RadioLicenseReminder.objects.filter(
            pk__in=ids,
            receiver_user_id=request.user.id,
        )
        qs = apply_tenant_filter(qs, request.user)

        if form.action == 'read':
            count = qs.update(is_read=True)
        elif form.action == 'unread':
            count = qs.update(is_read=False)
        elif form.action == 'handle':
            # handle：标记提醒已处理 + 同步写 ack（兼容旧前端）
            count = qs.update(is_handled=True, is_read=True)
            # 为这些提醒对应的执照写 ack（取第一条反推 valid_to）
            for r in qs.select_related('license'):
                if r.license:
                    from django.db import IntegrityError
                    try:
                        LicenseReminderAck.objects.create(
                            tenant_id=r.tenant_id,
                            license=r.license,
                            user_id=request.user.id,
                            user_name=request.user.nickname or request.user.username,
                            ack_valid_to=r.license.valid_to,
                        )
                    except IntegrityError:
                        pass
                    break  # 同一执照只写一次 ack
        else:
            return json_response(error='不支持的操作类型，请使用 read / handle / unread')

        return json_response(data={'count': count})


# ==================== 菜单红点接口 ====================

class ResponsibleUserListView(View):
    """可选责任人列表（轻量接口）

    为前端执照表单提供可选用户下拉。复用 radio_license.license.view 权限，
    不要求用户具备 system.account.view，避免给非管理员开账户管理权限。

    租户隔离：非超管只返回本租户激活用户；超管返回全量激活用户。

    Returns:
        list: [{id, nickname, username}, ...]
    """

    @auth('radio_license.license.view')
    def get(self, request):
        from apps.account.models import User as UserModel
        qs = UserModel.objects.filter(is_active=True, deleted_by_id__isnull=True)
        if not getattr(request.user, 'is_supper', False):
            qs = qs.filter(tenant_id=request.user.tenant_id)
        data = [
            {'id': u.id, 'nickname': u.nickname or u.username, 'username': u.username}
            for u in qs.order_by('nickname', 'username')
        ]
        return json_response(data)


class RadioLicenseBadgeView(View):
    """菜单红点统计

    返回本租户下"即将到期 + 已过期"执照的数量，用于左侧菜单红点提示。
    实时计算（按 valid_to 与 today 差值），不依赖 status 缓存字段。

    鉴权：复用 radio_license.license.view（查看权限才能看到红点）。
    """

    @auth('radio_license.license.view')
    def get(self, request):
        from datetime import date, timedelta
        qs = apply_tenant_filter(RadioLicense.objects.all(), request.user)
        today = date.today()
        # 即将到期：到期前 60 天内且未过期；已过期：valid_to < today
        expiring_count = qs.filter(
            valid_to__gte=today,
            valid_to__lte=today + timedelta(days=60),
        ).count()
        expired_count = qs.filter(valid_to__lt=today).count()
        return json_response(data={
            'count': expiring_count + expired_count,  # 红点总数
            'expiring_count': expiring_count,        # 即将到期
            'expired_count': expired_count,          # 已过期
        })
