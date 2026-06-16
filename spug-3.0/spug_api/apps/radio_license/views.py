# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
from django.views.generic import View
from django.utils import timezone
from libs import json_response, JsonParser, Argument, human_datetime, auth
from libs.tenant_utils import apply_tenant_filter, assign_tenant_id
from apps.radio_license.models import RadioLicense, RadioLicenseFrequency
import json
import logging

logger = logging.getLogger(__name__)


class RadioLicenseView(View):
    """执照列表 / 新增编辑 / 删除"""

    @auth('radio_license.license.view')
    def get(self, request):
        records = apply_tenant_filter(RadioLicense.objects.all(), request.user)
        # 软删除过滤
        records = records.filter(is_deleted=False)

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
            # 计算剩余天数和状态
            today = timezone.now().date()
            days_left = (record.valid_to - today).days
            if days_left < 0:
                computed_status = 'expired'
            elif days_left <= 30:
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
            Argument('responsible_user_id', type=int, required=False),
            Argument('responsible_user_name', required=False),
            Argument('remark', required=False),
            Argument('frequencies', type=list, required=False, help='频率列表'),
        ).parse(request.body)

        if error is None:
            # 日期校验：起始日期不能晚于截止日期
            if form.valid_from and form.valid_to:
                if form.valid_from > form.valid_to:
                    return json_response(error='起始日期不能晚于截止日期')

            frequencies = form.pop('frequencies', []) if hasattr(form, 'frequencies') else []

            if form.id:
                # 编辑模式
                form.updated_at = human_datetime()
                form.updated_by = request.user
                record_id = form.pop('id')
                # 计算状态
                from datetime import datetime
                if isinstance(form.valid_to, str):
                    valid_to_date = datetime.strptime(form.valid_to, '%Y-%m-%d').date()
                else:
                    valid_to_date = form.valid_to
                today = timezone.now().date()
                days_left = (valid_to_date - today).days
                if days_left < 0:
                    form.status = 'expired'
                elif days_left <= 30:
                    form.status = 'expiring'
                else:
                    form.status = 'normal'
                form.pop('remark', None)
                qs = apply_tenant_filter(RadioLicense.objects.all(), request.user)
                updated_count = qs.filter(pk=record_id).update(**form)
                if updated_count == 0:
                    error = '编辑失败：记录不存在或无权限编辑'
                else:
                    # 更新频率明细
                    _update_frequencies(record_id, frequencies, request.user)
            else:
                # 新增模式
                # 计算状态
                from datetime import datetime
                if isinstance(form.valid_to, str):
                    valid_to_date = datetime.strptime(form.valid_to, '%Y-%m-%d').date()
                else:
                    valid_to_date = form.valid_to
                today = timezone.now().date()
                days_left = (valid_to_date - today).days
                if days_left < 0:
                    form.status = 'expired'
                elif days_left <= 30:
                    form.status = 'expiring'
                else:
                    form.status = 'normal'
                form.created_by = request.user
                form.pop('remark', None)
                assign_tenant_id(form, request.user)
                license_obj = RadioLicense.objects.create(**form)
                # 创建频率明细
                _create_frequencies(license_obj, frequencies, request.user)

        return json_response(error=error)

    @auth('radio_license.license.del')
    def delete(self, request):
        form, error = JsonParser(
            Argument('id', type=int, help='请指定操作对象')
        ).parse(request.GET)
        if error is None:
            qs = apply_tenant_filter(RadioLicense.objects.all(), request.user)
            # 软删除
            updated_count = qs.filter(pk=form.id, is_deleted=False).update(is_deleted=True)
            if updated_count == 0:
                error = '删除失败：记录不存在或无权限删除'
        return json_response(error=error)


class RadioLicenseDetailView(View):
    """执照详情"""

    @auth('radio_license.license.view')
    def get(self, request, pk):
        qs = apply_tenant_filter(RadioLicense.objects.all(), request.user)
        try:
            record = qs.get(pk=pk, is_deleted=False)
        except RadioLicense.DoesNotExist:
            return json_response(error='记录不存在或无权限访问')

        item = record.to_view()
        # 附加频率列表
        freqs = RadioLicenseFrequency.objects.filter(license=record).order_by('sort_order', 'id')
        item['frequencies'] = [f.to_view() for f in freqs]
        # 计算剩余天数和状态
        today = timezone.now().date()
        days_left = (record.valid_to - today).days
        if days_left < 0:
            computed_status = 'expired'
        elif days_left <= 30:
            computed_status = 'expiring'
        else:
            computed_status = 'normal'
        item['days_left'] = days_left
        item['computed_status'] = computed_status

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
