# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
from django.views.generic import View
from libs import JsonParser, Argument, json_response, auth
from libs.tenant_utils import apply_tenant_filter, assign_tenant_id
from apps.device.models import DeviceResume, DeviceEvent
from apps.logs.audit import record_audit_event
from django.db import IntegrityError, DatabaseError
from django.db.models import Q
from django.http import HttpResponse
import logging
import json
from datetime import datetime

logger = logging.getLogger(__name__)


class DeviceResumeView(View):
    """Device Resume View"""

    @auth('device.device_resume.view')
    def get(self, request):
        """Get device resume list or single record"""
        # If use_units parameter exists, return distinct use unit list
        use_units_param = request.GET.get('use_units')
        if use_units_param:
            query = apply_tenant_filter(DeviceResume.objects.all(), request.user)
            use_units = query.values_list('use_unit', flat=True).exclude(use_unit='').exclude(use_unit__isnull=True).distinct().order_by('use_unit')
            return json_response(list(use_units))

        # If device_models parameter exists, return distinct device model list
        device_models_param = request.GET.get('device_models')
        if device_models_param:
            query = apply_tenant_filter(DeviceResume.objects.all(), request.user)
            device_models = query.values_list('device_model', flat=True).exclude(device_model='').exclude(device_model__isnull=True).distinct().order_by('device_model')
            return json_response(list(device_models))

        # If id parameter exists, return single record (for detail page)
        record_id = request.GET.get('id')
        if record_id:
            record = apply_tenant_filter(
                DeviceResume.objects.all().select_related('created_by', 'updated_by'),
                request.user
            ).filter(pk=record_id).first()
            if not record:
                return json_response(error='Device resume not found')
            return json_response(record.to_view())

        # Otherwise return list (with search and filter support)
        form, error = JsonParser(
            Argument('keyword', type=str, required=False, help='设备编号/名称关键字'),
            Argument('device_sn', type=str, required=False),
            Argument('device_name', type=str, required=False),
            Argument('device_model', type=str, required=False),
            Argument('current_status', type=list, required=False),
            Argument('use_unit', type=str, required=False),
            Argument('manufacturer', type=str, required=False),
            Argument('page', type=int, required=False, default=1),
            Argument('page_size', type=int, required=False, default=20)
        ).parse(request.GET)
        if error:
            return json_response(error=error)

        query = apply_tenant_filter(DeviceResume.objects.all(), request.user)

        # 统一关键字搜索：同时匹配设备编号或设备名称
        if form.keyword:
            query = query.filter(
                Q(device_sn__icontains=form.keyword) | Q(device_name__icontains=form.keyword)
            )
        # 兼容旧参数：单独传 device_sn / device_name 时仍按精确字段模糊匹配
        if form.device_sn:
            query = query.filter(device_sn__icontains=form.device_sn)
        if form.device_name:
            query = query.filter(device_name__icontains=form.device_name)
        if form.device_model:
            query = query.filter(device_model__icontains=form.device_model)

        # Filter
        if form.current_status:
            query = query.filter(current_status__in=form.current_status)
        if form.use_unit:
            query = query.filter(use_unit__icontains=form.use_unit)
        if form.manufacturer:
            query = query.filter(manufacturer__icontains=form.manufacturer)

        # Pagination（边界限制：page>=1, page_size<=200，避免恶意超大请求）
        page = max(1, form.page)
        page_size = min(max(1, form.page_size), 200)
        total = query.count()
        start = (page - 1) * page_size
        records = query[start:start + page_size]

        return json_response({
            'data': [r.to_view() for r in records],
            'total': total,
            'page': page,
            'page_size': page_size
        })

    @auth('device.device_resume.add')
    def post(self, request):
        """Create new device resume"""
        form, error = JsonParser(
            Argument('device_sn', type=str, help='Please enter device asset number'),
            Argument('device_name', type=str, help='Please enter device name'),
            Argument('device_model', type=str, help='Please enter device model'),
            Argument('frequency', type=str, required=False),
            Argument('call_sign', type=str, required=False),
            Argument('install_location', type=str, help='Please enter installation location'),
            Argument('geo_coordinate', type=str, required=False),
            Argument('device_purpose', type=str, required=False),
            Argument('manufacturer', type=str, help='Please enter manufacturer'),
            Argument('install_unit', type=str, help='Please enter installation unit'),
            Argument('use_unit', type=str, help='Please enter usage unit'),
            Argument('install_time', type=str, help='Please select installation time'),
            Argument('enable_time', type=str, help='Please select enable time'),
            Argument('current_status', type=str, help='Please select current device status'),
            # 字段命名规范化：优先使用 responsible_user_name（姓名）
            # 兼容旧前端仍传 responsible_user_id（实为姓名字符串）
            Argument('responsible_user_name', type=str, required=False),
            Argument('responsible_user_id', type=str, required=False),
            Argument('remark', type=str, required=False)
        ).parse(request.body)
        if error:
            return json_response(error=error)

        # 枚举校验：设备状态必须在合法范围内
        if form.current_status not in DeviceResume.STATUS_TEXT_MAP:
            return json_response(error='设备状态非法，仅支持：1=正常，2=故障，3=维修中，4=停用，5=报废')

        # 负责人姓名：优先新字段，兼容旧字段
        responsible_user_name = form.responsible_user_name or form.responsible_user_id or ''
        tenant_id = request.user.tenant_id

        # Create device resume
        # 注意：按 (tenant_id, device_sn) 唯一约束查询，不同租户可创建相同编号
        # 软删除策略（证据闭环第三阶段）：
        #   - objects 管理器自动过滤 is_deleted=False，故查重只看未删除记录；
        #   - 若同编号仅有已软删除记录，则"恢复重建"（复用原 ID，证据事件/审计日志不脱链），
        #     既允许编号复用，又保持证据链连续。
        from libs import human_datetime

        try:
            # 1. 查重：未删除记录中是否已存在该编号（objects 自动过滤 is_deleted=False）
            if DeviceResume.objects.filter(tenant_id=tenant_id, device_sn=form.device_sn).exists():
                logging.warning(f'创建设备失败：设备编号已存在｜设备编号：{form.device_sn}｜租户：{tenant_id}｜用户：{request.user.username}')
                return json_response(error='设备资产编号已存在')

            # 2. 检查是否存在已软删除的同编号记录：复用编号时恢复历史记录，保持证据链连续
            deleted_record = DeviceResume.all_objects.filter(
                tenant_id=tenant_id, device_sn=form.device_sn, is_deleted=True
            ).first()
            if deleted_record:
                deleted_record.device_name = form.device_name
                deleted_record.device_model = form.device_model
                deleted_record.frequency = form.frequency
                deleted_record.call_sign = form.call_sign
                deleted_record.install_location = form.install_location
                deleted_record.geo_coordinate = form.geo_coordinate
                deleted_record.device_purpose = form.device_purpose
                deleted_record.manufacturer = form.manufacturer
                deleted_record.install_unit = form.install_unit
                deleted_record.use_unit = form.use_unit
                deleted_record.install_time = form.install_time
                deleted_record.enable_time = form.enable_time
                deleted_record.current_status = form.current_status
                deleted_record.responsible_user_id = None
                deleted_record.responsible_user_name = responsible_user_name
                deleted_record.remark = form.remark
                deleted_record.is_deleted = False
                deleted_record.deleted_at = None
                deleted_record.deleted_by_id = None
                deleted_record.delete_reason = ''
                deleted_record.updated_by = request.user
                deleted_record.updated_at = human_datetime()
                deleted_record.save()
                logging.info(f'恢复并重建设备成功（复用历史编号，保留证据链）｜租户：{tenant_id}｜用户：{request.user.username}｜设备编号：{form.device_sn}｜设备ID：{deleted_record.id}')
                return json_response(deleted_record.to_view())

            # 3. 全新创建
            record = DeviceResume(
                tenant_id=tenant_id,
                device_sn=form.device_sn,
                device_name=form.device_name,
                device_model=form.device_model,
                frequency=form.frequency,
                call_sign=form.call_sign,
                install_location=form.install_location,
                geo_coordinate=form.geo_coordinate,
                device_purpose=form.device_purpose,
                manufacturer=form.manufacturer,
                install_unit=form.install_unit,
                use_unit=form.use_unit,
                install_time=form.install_time,
                enable_time=form.enable_time,
                current_status=form.current_status,
                responsible_user_id=None,
                responsible_user_name=responsible_user_name,
                remark=form.remark,
                created_by=request.user,
            )
            record.save()
            logging.info(f'创建设备成功｜租户：{tenant_id}｜用户：{request.user.username}｜设备编号：{form.device_sn}')
            return json_response(record.to_view())

        except (IntegrityError, DatabaseError) as e:
            logging.error(f'创建设备数据库错误｜设备编号：{form.device_sn}｜租户：{tenant_id}｜用户：{request.user.username}｜错误：{e}', exc_info=True)
            return json_response(error='设备资产编号已存在，请重试')
        except Exception as e:
            logging.error(f'创建设备系统异常｜设备编号：{form.device_sn}｜租户：{tenant_id}｜用户：{request.user.username}｜错误：{e}', exc_info=True)
            return json_response(error='创建设备失败，请联系管理员')

    @auth('device.device_resume.edit')
    def put(self, request):
        """Edit device resume"""
        form, error = JsonParser(
            Argument('id', type=int, help='Parameter error'),
            Argument('device_name', type=str, help='Please enter device name'),
            Argument('device_model', type=str, help='Please enter device model'),
            Argument('frequency', type=str, required=False),
            Argument('call_sign', type=str, required=False),
            Argument('install_location', type=str, help='Please enter installation location'),
            Argument('geo_coordinate', type=str, required=False),
            Argument('device_purpose', type=str, required=False),
            Argument('manufacturer', type=str, help='Please enter manufacturer'),
            Argument('install_unit', type=str, help='Please enter installation unit'),
            Argument('use_unit', type=str, help='Please enter usage unit'),
            Argument('install_time', type=str, help='Please select installation time'),
            Argument('enable_time', type=str, help='Please select enable time'),
            Argument('current_status', type=str, help='Please select current device status'),
            # 字段命名规范化：优先使用 responsible_user_name（姓名）
            Argument('responsible_user_name', type=str, required=False),
            Argument('responsible_user_id', type=str, required=False),
            Argument('remark', type=str, required=False)
        ).parse(request.body)
        if error:
            return json_response(error=error)

        # 枚举校验：设备状态必须在合法范围内
        if form.current_status not in DeviceResume.STATUS_TEXT_MAP:
            return json_response(error='设备状态非法，仅支持：1=正常，2=故障，3=维修中，4=停用，5=报废')

        # 登录状态校验（@auth装饰器已验证，此处移除冗余检查）
        try:
            record = apply_tenant_filter(DeviceResume.objects.all(), request.user).filter(pk=form.id).first()
            if not record:
                logging.info(f'编辑设备不存在｜设备ID：{form.id}｜用户：{request.user.username}')
                return json_response(error='设备不存在或无权限操作')

            # 权限校验：普通用户不能编辑全局设备
            if record.tenant_id == '' and not request.user.is_supper:
                logging.warning(f'编辑设备权限不足：尝试编辑全局设备｜设备ID：{form.id}｜设备编号：{record.device_sn}｜用户：{request.user.username}')
                return json_response(error='无权限编辑全局设备')

            # 负责人姓名：优先新字段，兼容旧字段
            responsible_user_name = form.responsible_user_name or form.responsible_user_id or ''

            # 证据闭环第三阶段：记录状态变更前的旧状态，用于状态变更事件化
            old_status = record.current_status
            old_status_text = DeviceResume.STATUS_TEXT_MAP.get(old_status, old_status)
            new_status = form.current_status
            new_status_text = DeviceResume.STATUS_TEXT_MAP.get(new_status, new_status)
            status_changed = (old_status != new_status)

            # Update device resume
            from libs import human_datetime
            record.device_name = form.device_name
            record.device_model = form.device_model
            record.frequency = form.frequency
            record.call_sign = form.call_sign
            record.install_location = form.install_location
            record.geo_coordinate = form.geo_coordinate
            record.device_purpose = form.device_purpose
            record.manufacturer = form.manufacturer
            record.install_unit = form.install_unit
            record.use_unit = form.use_unit
            record.install_time = form.install_time
            record.enable_time = form.enable_time
            record.current_status = form.current_status
            record.responsible_user_id = None
            record.responsible_user_name = responsible_user_name
            record.remark = form.remark
            record.updated_by = request.user
            record.updated_at = human_datetime()
            record.save()
            logging.info(f'编辑设备成功｜租户：{record.tenant_id}｜用户：{request.user.username}｜设备编号：{record.device_sn}')

            # 证据闭环第三阶段：设备状态变更必须生成证据事件
            # 方案 8.3.1：current_status 变化时写入证据事件（before/after 快照）
            if status_changed:
                try:
                    from apps.evidence.services import record_evidence_event
                    record_evidence_event(
                        tenant_id=record.tenant_id,
                        module='device',
                        object_type='device',
                        object_id=record.id,
                        event_type='other',
                        actor_user_id=getattr(request.user, 'id', None),
                        actor_username=getattr(request.user, 'username', ''),
                        actor_name=getattr(request.user, 'nickname', '') or getattr(request.user, 'username', ''),
                        before_snapshot={'current_status': old_status, 'current_status_text': old_status_text},
                        after_snapshot={'current_status': new_status, 'current_status_text': new_status_text},
                        object_snapshot={
                            'device_sn': record.device_sn,
                            'device_name': record.device_name,
                            'current_status': record.current_status,
                            'current_status_text': new_status_text,
                        },
                        event_title=f'设备状态变更 {record.device_sn}: {old_status_text} → {new_status_text}',
                        remark=f'状态由 {old_status_text} 变更为 {new_status_text}',
                    )
                except Exception as ev_err:
                    logger.error(f'设备状态变更证据事件写入失败｜设备ID：{record.id}｜错误：{ev_err}')

            return json_response(record.to_view())
        except (IntegrityError, DatabaseError) as e:
            logging.error(f'编辑设备数据库错误｜设备ID：{form.id}｜用户：{request.user.username}｜错误：{e}', exc_info=True)
            return json_response(error='编辑设备失败，数据关联冲突，请联系管理员')
        except Exception as e:
            logging.error(f'编辑设备系统异常｜设备ID：{form.id}｜用户：{request.user.username}｜错误：{e}', exc_info=True)
            return json_response(error='编辑设备失败，请联系管理员')

    @auth('device.device_resume.delete')
    def delete(self, request):
        """Delete device resume (soft delete - 证据闭环第三阶段)"""
        form, error = JsonParser(
            Argument('id', type=int, help='Parameter error'),
            Argument('delete_reason', type=str, required=False),
        ).parse(request.GET)
        if error:
            return json_response(error=error)

        # Validate id format
        if not form.id or not str(form.id).isdigit():
            return json_response(error='设备ID格式错误')

        from django.db import transaction
        from libs import human_datetime
        from apps.evidence.services import record_evidence_event

        delete_success = False
        error_msg = ''

        try:
            with transaction.atomic():
                # 1. 查询设备
                record = apply_tenant_filter(DeviceResume.objects.all(), request.user).filter(pk=form.id).first()
                if not record:
                    raise ValueError('设备不存在或无权限删除')

                device_sn = record.device_sn
                tenant_id = record.tenant_id

                # 2. 权限校验：普通用户不能删除超级管理员的全局设备
                if record.tenant_id == '' and not request.user.is_supper:
                    raise PermissionError('无权限删除全局设备')

                # 3. 软删除：标记 is_deleted，保留数据和事件
                record.is_deleted = True
                record.deleted_at = human_datetime()
                record.deleted_by_id = getattr(request.user, 'id', None)
                record.delete_reason = form.delete_reason or ''
                record.save(update_fields=['is_deleted', 'deleted_at', 'deleted_by_id', 'delete_reason'])

                # 4. 写入证据事件
                record_evidence_event(
                    tenant_id=tenant_id, module='device', object_type='device',
                    object_id=record.id, event_type='delete',
                    actor_user_id=getattr(request.user, 'id', None),
                    actor_username=getattr(request.user, 'username', ''),
                    actor_name=getattr(request.user, 'nickname', '') or getattr(request.user, 'username', ''),
                    object_snapshot={'device_sn': device_sn, 'delete_reason': form.delete_reason or ''},
                    event_title=f'删除设备 {device_sn}',
                )
                delete_success = True
                logging.info(f'软删除设备成功｜租户：{tenant_id}｜用户：{request.user.username}｜设备编号：{device_sn}')

        except ValueError as e:
            error_msg = str(e)
        except PermissionError as e:
            error_msg = str(e)
        except (IntegrityError, DatabaseError) as e:
            error_msg = '删除设备失败，数据关联冲突，请联系管理员'
        except Exception as e:
            error_msg = '删除设备失败，请重试'

        if delete_success:
            return json_response()
        else:
            return json_response(error=error_msg)


class DeviceEventView(View):
    """Device Event View"""

    @auth('device.device_resume.history_view')
    def get(self, request):
        """Get device event list"""
        form, error = JsonParser(
            Argument('device_resume_id', type=int, required=False),
            Argument('event_type', type=int, required=False, help='Event type filter'),
            Argument('page', type=int, required=False, default=1),
            Argument('page_size', type=int, required=False, default=20)
        ).parse(request.GET)
        if error:
            return json_response(error=error)

        query = apply_tenant_filter(DeviceEvent.objects.all(), request.user)

        # Filter by device
        if form.device_resume_id:
            query = query.filter(device_resume_id=form.device_resume_id)

        # Filter by event type
        if form.event_type:
            query = query.filter(event_type=form.event_type)

        # Order by time descending
        query = query.order_by('-event_time', '-id')

        # Pagination（边界限制：page>=1, page_size<=200）
        page = max(1, form.page)
        page_size = min(max(1, form.page_size), 200)
        total = query.count()
        start = (page - 1) * page_size
        records = query[start:start + page_size]

        return json_response({
            'data': [r.to_view() for r in records],
            'total': total,
            'page': page,
            'page_size': page_size
        })

    @auth('device.device_resume.history_add')
    def post(self, request):
        """Create new device event"""
        from .validators import DeviceEventValidator, DeviceEventBuilder

        form, error = self._parse_event_form(request, is_edit=False)
        if error:
            return json_response(error=error)

        # 枚举校验：事件类型必须在合法范围内
        is_valid, error = DeviceEventValidator.validate_event_type(form)
        if not is_valid:
            return json_response(error=error)

        # Get device info（按租户过滤，确保不能为其他租户设备创建事件）
        device = apply_tenant_filter(DeviceResume.objects.all(), request.user).filter(pk=form.device_resume_id).first()
        if not device:
            return json_response(error='关联设备不存在或无权限操作')

        # Validate maintenance fields（检修类型必填字段）
        is_valid, error = DeviceEventValidator.validate_maintenance_fields(form)
        if not is_valid:
            return json_response(error=error)

        # Validate time logic（修复时间不能早于故障时间）
        is_valid, error = DeviceEventValidator.validate_time_logic(form)
        if not is_valid:
            return json_response(error=error)

        # Create event record
        try:
            event_data = DeviceEventBuilder.build_event_data(form, device, request.user)
            assign_tenant_id(event_data, request.user)
            event = DeviceEvent.objects.create(**event_data)
            logging.info(f'创建设备事件成功｜租户：{event.tenant_id}｜用户：{request.user.username}｜设备编号：{event.device_sn}｜事件类型：{event.event_type}')
            return json_response(event.to_view())
        except (IntegrityError, DatabaseError) as e:
            logging.error(f'创建设备事件数据库错误｜设备ID：{form.device_resume_id}｜用户：{request.user.username}｜错误：{e}', exc_info=True)
            return json_response(error='创建事件失败，数据关联冲突，请联系管理员')
        except Exception as e:
            logging.error(f'创建设备事件系统异常｜设备ID：{form.device_resume_id}｜用户：{request.user.username}｜错误：{e}', exc_info=True)
            return json_response(error='创建事件失败，请联系管理员')

    def _parse_event_form(self, request, is_edit=False):
        """
        解析事件表单数据（新增和编辑共用，避免规则分叉）

        Args:
            is_edit: True=编辑场景（需 id，不需 device_resume_id/event_type）；
                     False=新增场景（需 device_resume_id/event_type）
        """
        args = []
        if is_edit:
            args.append(Argument('id', type=int, help='Parameter error'))
        else:
            args.append(Argument('device_resume_id', type=int, help='Please select associated device'))
            args.append(Argument('event_type', type=int, help='Please select event type'))
        # 共有字段（字段命名规范化：优先 related_user_name，兼容旧字段 related_user_id）
        args.extend([
            Argument('event_time', type=str, help='Please select event time'),
            Argument('event_title', type=str, help='Please enter event title'),
            Argument('related_user_name', type=str, required=False),
            Argument('related_user_id', type=str, required=False),
            Argument('fault_part', type=str, required=False),
            Argument('fault_phenomenon_cause', type=str, required=False),
            Argument('maintenance_measures', type=str, required=False),
            Argument('repair_time', type=str, required=False),
            Argument('remark', type=str, required=False)
        ])
        return JsonParser(*args).parse(request.body)

    @auth('device.device_resume.history_edit')
    def put(self, request):
        """Edit device event"""
        from .validators import DeviceEventValidator

        form, error = self._parse_event_form(request, is_edit=True)
        if error:
            return json_response(error=error)

        event = apply_tenant_filter(DeviceEvent.objects.all(), request.user).filter(pk=form.id).first()
        if not event:
            return json_response(error='事件记录不存在或无权限操作')

        # 编辑时事件类型不可改（前端 disabled），用数据库中的 event_type 复用校验逻辑
        form.event_type = event.event_type

        # 复用与新增一致的校验：检修类型必填字段 + 时间逻辑
        is_valid, error = DeviceEventValidator.validate_maintenance_fields(form)
        if not is_valid:
            return json_response(error=error)

        is_valid, error = DeviceEventValidator.validate_time_logic(form)
        if not is_valid:
            return json_response(error=error)

        # 记录人姓名：优先新字段，兼容旧字段
        related_user_name = form.related_user_name or form.related_user_id or ''

        # Update event record
        event.event_title = form.event_title
        event.event_time = form.event_time
        event.related_user_id = None
        event.related_user_name = related_user_name
        event.fault_part = form.fault_part
        event.fault_phenomenon_cause = form.fault_phenomenon_cause
        event.maintenance_measures = form.maintenance_measures
        event.repair_time = form.repair_time
        event.remark = form.remark
        event.save()
        logging.info(f'编辑设备事件成功｜租户：{event.tenant_id}｜用户：{request.user.username}｜事件ID：{event.id}')
        return json_response(event.to_view())

    @auth('device.device_resume.history_delete')
    def delete(self, request):
        """Delete device event (hard delete)"""
        form, error = JsonParser(
            Argument('id', type=int, help='Parameter error')
        ).parse(request.GET)
        if error:
            return json_response(error=error)

        # Validate id format
        if not form.id or not str(form.id).isdigit():
            return json_response(error='事件ID格式错误')

        try:
            event = apply_tenant_filter(DeviceEvent.objects.all(), request.user).filter(pk=form.id).first()
            if not event:
                logging.info(f'删除设备事件不存在｜事件ID：{form.id}｜用户：{request.user.username}')
                return json_response(error='事件记录不存在')

            # Hard delete
            device_sn = event.device_sn
            event.delete()
            logging.info(f'删除设备事件成功｜租户：{event.tenant_id}｜用户：{request.user.username}｜设备编号：{device_sn}｜事件ID：{form.id}')
            return json_response()
        except (IntegrityError, DatabaseError) as e:
            logging.error(f'删除设备事件数据库错误｜事件ID：{form.id}｜用户：{request.user.username}｜错误：{e}', exc_info=True)
            return json_response(error='删除事件失败，数据关联冲突，请联系管理员')
        except Exception as e:
            logging.error(f'删除设备事件系统异常｜事件ID：{form.id}｜用户：{request.user.username}｜错误：{e}', exc_info=True)
            return json_response(error='删除事件失败，请重试')


class DeviceResumeExportView(View):
    """设备履历PDF导出"""

    @auth('device.device_resume.history_view')
    def post(self, request):
        """导出设备履历PDF

        安全原则：后端只接受 device_id，设备和事件数据全部从数据库按租户重新查询，
        不信任前端传入的 device_info / events，避免请求体被篡改导出伪造履历。
        """
        try:
            data = json.loads(request.body)
        except (json.JSONDecodeError, ValueError):
            record_audit_event(
                request=request,
                action='export',
                target_type='device',
                target_name='Device resume PDF export',
                detail={'format': 'pdf', 'filters': {}},
                error='invalid request body',
            )
            return json_response(error='请求数据格式错误')

        device_id = data.get('device_id')
        event_type = data.get('event_type')
        filters = {
            'device_id': device_id,
            'event_type': event_type,
        }
        if not device_id:
            record_audit_event(
                request=request,
                action='export',
                target_type='device',
                target_name='Device resume PDF export',
                detail={'format': 'pdf', 'filters': filters},
                error='missing device_id',
            )
            return json_response(error='缺少设备ID')

        # 可选：事件类型筛选（默认导出全部事件，不受前端分页限制）

        # 按租户过滤查询设备，确保用户只能导出本租户设备
        # 证据包属审计场景：使用 all_objects 以便对已软删除设备仍可导出（证据链完整性）
        device = apply_tenant_filter(DeviceResume.all_objects.all(), request.user).filter(pk=device_id).first()
        if not device:
            record_audit_event(
                request=request,
                action='export',
                target_type='device',
                target_id=device_id,
                target_name='Device resume PDF export',
                detail={'format': 'pdf', 'filters': filters},
                error='device not found or denied',
            )
            return json_response(error='设备不存在或无权限操作')

        # 后端查询事件列表（全量导出，避免前端只传当前分页导致履历不完整）
        events_qs = apply_tenant_filter(DeviceEvent.objects.all(), request.user).filter(device_resume_id=device_id)
        if event_type:
            events_qs = events_qs.filter(event_type=event_type)
        events_qs = events_qs.order_by('-event_time', '-id')

        # 转换为字典列表（pdf_export 期望 dict 结构）
        device_info = device.to_view()
        events = [e.to_view() for e in events_qs]

        try:
            from .pdf_export import generate_device_resume_pdf
            # 导出人由后端从 request.user 注入，不信任前端传入
            operator_name = getattr(request.user, 'nickname', None) or \
                            getattr(request.user, 'username', None) or ''
            pdf_output = generate_device_resume_pdf(device_info, events, operator_name)

            device_sn = device_info.get('device_sn', 'unknown')
            device_name = device_info.get('device_name', '')
            export_time = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f'设备履历_{device_sn}_{device_name}_{export_time}.pdf'
            # 对文件名做ASCII安全处理（避免中文文件名在部分浏览器乱码）
            from django.utils.encoding import escape_uri_path
            safe_filename = escape_uri_path(filename)

            response = HttpResponse(
                pdf_output.getvalue(),
                content_type='application/pdf'
            )
            response['Content-Disposition'] = f"attachment; filename*=UTF-8''{safe_filename}"
            record_audit_event(
                request=request,
                action='export',
                target_type='device',
                target_id=device_id,
                target_name=device_info.get('device_sn') or 'Device resume PDF export',
                detail={
                    'format': 'pdf',
                    'filters': filters,
                    'count': len(events),
                },
            )
            return response

        except Exception as e:
            record_audit_event(
                request=request,
                action='export',
                target_type='device',
                target_id=device_id,
                target_name=device_info.get('device_sn') if 'device_info' in locals() else 'Device resume PDF export',
                detail={'format': 'pdf', 'filters': filters},
                error=f'{type(e).__name__}: {str(e)[:80]}',
            )
            logger.error(f'导出设备履历PDF失败｜设备ID：{device_id}｜错误：{e}', exc_info=True)
            return json_response(error='导出PDF失败，请重试')


# ==================== 证据闭环第三阶段：证据包导出 ====================

def _build_device_snapshot(device):
    """构建设备业务快照（用于证据事件 + 证据包）"""
    events = DeviceEvent.objects.filter(device_resume_id=device.id).order_by('-event_time', '-id')
    return {
        'device': {
            'id': device.id,
            'device_sn': device.device_sn,
            'device_name': device.device_name,
            'device_model': device.device_model,
            'frequency': device.frequency,
            'call_sign': device.call_sign,
            'install_location': device.install_location,
            'geo_coordinate': device.geo_coordinate,
            'device_purpose': device.device_purpose,
            'manufacturer': device.manufacturer,
            'install_unit': device.install_unit,
            'use_unit': device.use_unit,
            'install_time': device.install_time,
            'enable_time': device.enable_time,
            'current_status': device.current_status,
            'current_status_text': DeviceResume.STATUS_TEXT_MAP.get(device.current_status, device.current_status),
            'responsible_user_name': device.responsible_user_name,
            'is_deleted': device.is_deleted,
            'deleted_at': device.deleted_at,
            'delete_reason': device.delete_reason,
            'snapshot_hash': device.snapshot_hash,
            'created_at': device.created_at,
            'created_by_id': device.created_by_id,
            'updated_at': device.updated_at,
            'updated_by_id': device.updated_by_id,
        },
        'events': [
            {
                'id': e.id, 'event_type': e.event_type,
                'event_type_text': DeviceEvent.EVENT_TYPE_TEXT_MAP.get(e.event_type, str(e.event_type)),
                'event_time': e.event_time, 'event_title': e.event_title,
                'fault_part': e.fault_part,
                'fault_phenomenon_cause': e.fault_phenomenon_cause,
                'maintenance_measures': e.maintenance_measures,
                'related_user_name': e.related_user_name,
                'repair_time': e.repair_time, 'remark': e.remark,
                'correction_event_id': e.correction_event_id,
                'correction_reason': e.correction_reason,
                'corrected_by_id': e.corrected_by_id,
                'corrected_at': e.corrected_at,
                'created_at': e.created_at, 'created_by_id': e.created_by_id,
            }
            for e in events
        ],
    }


class DeviceEvidencePackageView(View):
    """设备证据包导出 - 包含业务快照/证据事件/审计日志/附件哈希清单"""

    @auth('device.device_resume.view')
    def get(self, request):
        import json as _json
        import zipfile
        from io import BytesIO
        from apps.evidence.models import EvidenceEvent, EvidenceAttachment
        from apps.logs.models import AuditLog
        from libs import human_datetime

        device_id = request.GET.get('id')
        if not device_id:
            return json_response(error='缺少 id 参数')

        device = apply_tenant_filter(DeviceResume.objects.all(), request.user).filter(pk=device_id).first()
        if not device:
            return json_response(error='设备不存在或无权限')

        tenant_id = getattr(request.user, 'tenant_id', 'default')
        snapshot = _build_device_snapshot(device)

        events = list(EvidenceEvent.objects.filter(
            tenant_id=tenant_id, module='device',
            object_type='device', object_id=str(device.id),
        ).order_by('id'))
        events_data = [e.to_dict() for e in events]

        audit_logs = list(AuditLog.objects.filter(
            tenant_id=tenant_id, target_type='device',
            target_id=str(device.id),
        ).order_by('id'))
        # 兼容：target_id 未记录时回退全量 device 类型审计
        if not audit_logs:
            audit_logs = list(AuditLog.objects.filter(
                tenant_id=tenant_id, target_type='device',
            ).order_by('id'))
        audit_data = [l.to_dict() for l in audit_logs]

        atts = EvidenceAttachment.objects.filter(
            tenant_id=tenant_id, module='device',
            object_type='device', object_id=str(device.id), is_deleted=False,
        )
        att_hashes = [
            {'file_name': a.file_name, 'sha256': a.file_hash_sha256, 'size': a.file_size}
            for a in atts
        ]

        buf = BytesIO()
        with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
            zf.writestr('object_snapshot.json', _json.dumps(snapshot, ensure_ascii=False, indent=2))
            zf.writestr('evidence_events.json', _json.dumps(events_data, ensure_ascii=False, indent=2))
            zf.writestr('audit_logs.json', _json.dumps(audit_data, ensure_ascii=False, indent=2))
            zf.writestr('hashes.json', _json.dumps({
                'module': 'device', 'object_id': device.id,
                'device_sn': device.device_sn,
                'current_status': device.current_status,
                'is_deleted': device.is_deleted,
                'snapshot_hash': device.snapshot_hash,
                'attachments': att_hashes,
                'events_count': len(events_data),
                'generated_at': human_datetime(),
            }, ensure_ascii=False, indent=2))
            zf.writestr('verify.txt',
                        '本证据包包含设备业务快照JSON、证据事件JSON、审计日志JSON、附件哈希清单。\n'
                        '校验方式：重新计算 object_snapshot.json 的 SHA256，与 hashes.json 中 snapshot_hash 比对。\n'
                        '证据事件哈希链可通过 evidence_events.json 中的 prev_hash/event_hash 校验连续性。\n')

        buf.seek(0)
        resp = HttpResponse(buf.getvalue(), content_type='application/zip')
        resp['Content-Disposition'] = f'attachment; filename="evidence_device_{device.id}.zip"'
        return resp
