# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
from django.views.generic import View
from libs import JsonParser, Argument, json_response, auth
from libs.tenant_utils import apply_tenant_filter, assign_tenant_id
from apps.device.models import DeviceResume, DeviceEvent
from apps.account.models import User
from django.db import IntegrityError, DatabaseError
from django.http import HttpResponse
import logging
import json

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

        # Fuzzy search
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

        # Pagination
        total = query.count()
        start = (form.page - 1) * form.page_size
        records = query[start:start + form.page_size]

        return json_response({
            'data': [r.to_view() for r in records],
            'total': total,
            'page': form.page,
            'page_size': form.page_size
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
            Argument('responsible_user_id', type=str, help='Please enter device owner name'),
            Argument('remark', type=str, required=False)
        ).parse(request.body)
        if error:
            return json_response(error=error)

        # Use owner name directly (responsible_user_id is now a string name)
        responsible_user_name = form.responsible_user_id
        tenant_id = request.user.tenant_id

        # Create device resume using get_or_create for thread safety
        from libs import human_datetime

        try:
            defaults_data = {
                'device_name': form.device_name,
                'device_model': form.device_model,
                'frequency': form.frequency,
                'call_sign': form.call_sign,
                'install_location': form.install_location,
                'geo_coordinate': form.geo_coordinate,
                'device_purpose': form.device_purpose,
                'manufacturer': form.manufacturer,
                'install_unit': form.install_unit,
                'use_unit': form.use_unit,
                'install_time': form.install_time,
                'enable_time': form.enable_time,
                'current_status': form.current_status,
                'responsible_user_id': None,
                'responsible_user_name': responsible_user_name,
                'tenant_id': tenant_id,
                'remark': form.remark,
                'created_by': request.user,
                'is_deleted': False
            }
            record, created = DeviceResume.objects.get_or_create(
                device_sn=form.device_sn,
                defaults=defaults_data
            )
            if not created:
                logging.warning(f'创建设备失败：设备编号已存在｜设备编号：{form.device_sn}｜租户：{tenant_id}｜用户：{request.user.username}')
                return json_response(error='设备资产编号已存在')
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
            Argument('responsible_user_id', type=str, help='Please enter device owner name'),
            Argument('remark', type=str, required=False)
        ).parse(request.body)
        if error:
            return json_response(error=error)

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

            # Use owner name directly
            responsible_user_name = form.responsible_user_id

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
            return json_response(record.to_view())
        except (IntegrityError, DatabaseError) as e:
            logging.error(f'编辑设备数据库错误｜设备ID：{form.id}｜用户：{request.user.username}｜错误：{e}', exc_info=True)
            return json_response(error='编辑设备失败，数据关联冲突，请联系管理员')
        except Exception as e:
            logging.error(f'编辑设备系统异常｜设备ID：{form.id}｜用户：{request.user.username}｜错误：{e}', exc_info=True)
            return json_response(error='编辑设备失败，请联系管理员')

    @auth('device.device_resume.delete')
    def delete(self, request):
        """Delete device resume (hard delete)"""
        form, error = JsonParser(
            Argument('id', type=int, help='Parameter error')
        ).parse(request.GET)
        if error:
            return json_response(error=error)

        # Validate id format
        if not form.id or not str(form.id).isdigit():
            return json_response(error='设备ID格式错误')

        from django.db import transaction

        # 登录状态校验
        if not request.user.is_authenticated:
            logging.warning(f'删除设备未登录｜设备ID：{form.id}｜IP：{request.META.get("REMOTE_ADDR")}')
            return json_response(error='无权限执行该操作')

        delete_success = False
        error_msg = ''
        event_delete_count = 0

        try:
            with transaction.atomic():
                # 1. 查询设备
                record = apply_tenant_filter(DeviceResume.objects.all(), request.user).filter(pk=form.id).first()
                if not record:
                    logging.info(f'删除设备不存在｜设备ID：{form.id}｜用户：{request.user.username}')
                    raise ValueError('设备不存在或无权限删除')

                device_sn = record.device_sn
                tenant_id = record.tenant_id

                # 2. 权限校验：普通用户不能删除超级管理员的全局设备
                if record.tenant_id == '' and not request.user.is_supper:
                    logging.warning(f'删除设备权限不足：尝试删除全局设备｜设备ID：{form.id}｜设备编号：{device_sn}｜用户：{request.user.username}')
                    raise PermissionError('无权限删除全局设备')

                # 3. 级联删除事件
                event_qs = apply_tenant_filter(DeviceEvent.objects.all(), request.user).filter(
                    device_resume_id=form.id
                )
                event_delete_count, _ = event_qs.delete()

                # 4. 删除设备
                record.delete()
                delete_success = True

                logging.info(f'删除设备成功｜租户：{tenant_id}｜用户：{request.user.username}｜设备编号：{device_sn}｜删除事件数：{event_delete_count}')

        except ValueError as e:
            error_msg = str(e)
        except PermissionError as e:
            error_msg = str(e)
        except (IntegrityError, DatabaseError) as e:
            error_msg = '删除设备失败，数据关联冲突，请联系管理员'
            logging.error(f'删除设备数据库错误｜设备ID：{form.id}｜用户：{request.user.username}｜错误：{e}', exc_info=True)
        except Exception as e:
            error_msg = '删除设备失败，请重试'
            logging.error(f'删除设备系统异常｜设备ID：{form.id}｜用户：{request.user.username}｜错误：{e}', exc_info=True)

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

        # Pagination
        total = query.count()
        start = (form.page - 1) * form.page_size
        records = query[start:start + form.page_size]

        return json_response({
            'data': [r.to_view() for r in records],
            'total': total,
            'page': form.page,
            'page_size': form.page_size
        })

    @auth('device.device_resume.history_add')
    def post(self, request):
        """Create new device event"""
        from .validators import DeviceEventValidator, DeviceEventBuilder

        form, error = self._parse_event_form(request)
        if error:
            return json_response(error=error)

        # Get device info
        device = apply_tenant_filter(DeviceResume.objects.all(), request.user).filter(pk=form.device_resume_id).first()
        if not device:
            return json_response(error='Device not found')

        # Validate maintenance fields
        is_valid, error = DeviceEventValidator.validate_maintenance_fields(form)
        if not is_valid:
            return json_response(error=error)

        # Validate time logic
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

    def _parse_event_form(self, request):
        """解析事件表单数据"""
        return JsonParser(
            Argument('device_resume_id', type=int, help='Please select associated device'),
            Argument('event_type', type=int, help='Please select event type'),
            Argument('event_time', type=str, help='Please select event time'),
            Argument('event_title', type=str, help='Please enter event title'),
            Argument('related_user_id', type=str, help='Please enter recorder name'),
            Argument('fault_part', type=str, required=False),
            Argument('fault_phenomenon_cause', type=str, required=False),
            Argument('maintenance_measures', type=str, required=False),
            Argument('repair_time', type=str, required=False),
            Argument('remark', type=str, required=False)
        ).parse(request.body)

    @auth('device.device_resume.history_edit')
    def put(self, request):
        """Edit device event"""
        form, error = JsonParser(
            Argument('id', type=int, help='Parameter error'),
            Argument('event_title', type=str, help='Please enter event title'),
            Argument('event_time', type=str, help='Please select event time'),
            Argument('related_user_id', type=str, help='Please enter recorder name'),
            # Device maintenance specific fields
            Argument('fault_part', type=str, required=False),
            Argument('fault_phenomenon_cause', type=str, required=False),
            Argument('maintenance_measures', type=str, required=False),
            Argument('repair_time', type=str, required=False),
            Argument('remark', type=str, required=False)
        ).parse(request.body)
        if error:
            return json_response(error=error)

        event = apply_tenant_filter(DeviceEvent.objects.all(), request.user).filter(pk=form.id).first()
        if not event:
            return json_response(error='Event record not found')

        # Validate fields based on event type
        if event.event_type == 3:  # Device maintenance
            if form.repair_time and form.event_time:
                from datetime import datetime
                try:
                    repair_time = datetime.strptime(form.repair_time, '%Y-%m-%d %H:%M')
                    event_time = datetime.strptime(form.event_time, '%Y-%m-%d %H:%M')
                    if repair_time < event_time:
                        return json_response(error='Repair time cannot be earlier than fault time')
                    if repair_time > datetime.now() or event_time > datetime.now():
                        return json_response(error='时间不能晚于当前时间')
                except ValueError:
                    return json_response(error='时间格式错误，请使用YYYY-MM-DD HH:MM格式（如：2026-03-03 14:30）')

        # Update event record
        event.event_title = form.event_title
        event.event_time = form.event_time
        event.related_user_id = None
        event.related_user_name = form.related_user_id
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
        
        前端传入设备信息和事件列表，后端生成PDF返回
        """
        try:
            data = json.loads(request.body)
        except (json.JSONDecodeError, ValueError):
            return json_response(error='请求数据格式错误')

        device_info = data.get('device_info')
        events = data.get('events', [])

        if not device_info or not device_info.get('device_sn'):
            return json_response(error='缺少设备信息')

        try:
            from .pdf_export import generate_device_resume_pdf
            pdf_output = generate_device_resume_pdf(device_info, events)

            device_sn = device_info.get('device_sn', 'unknown')
            device_name = device_info.get('device_name', '')
            filename = f'设备履历_{device_sn}_{device_name}.pdf'
            # 对文件名做ASCII安全处理（避免中文文件名在部分浏览器乱码）
            from django.utils.encoding import escape_uri_path
            safe_filename = escape_uri_path(filename)

            response = HttpResponse(
                pdf_output.getvalue(),
                content_type='application/pdf'
            )
            response['Content-Disposition'] = f"attachment; filename*=UTF-8''{safe_filename}"
            return response

        except Exception as e:
            logger.error(f'导出设备履历PDF失败｜设备编号：{device_info.get("device_sn")}｜错误：{e}', exc_info=True)
            return json_response(error='导出PDF失败，请重试')
