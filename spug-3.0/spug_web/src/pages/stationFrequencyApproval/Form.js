/**
 * 台站频率批复表单（新增 / 编辑 / 详情三态）。
 *
 * 设计方案 9.2：
 * - 字段：文件名称、文件编号、批复频率、起始日期、截止日期、责任人、备注
 * - 前端日期校验即时反馈，后端仍执行最终校验
 * - 责任人下拉使用批复专属 /approvals/responsible-users/ 接口
 * - 附件只在记录已经创建并取得 id 后显示（详情态）
 * - 统一 POST /api/radio-license/approvals/ 接口：带 id 编辑，不带 id 新增
 */
import React, { useState, useRef } from 'react';
import { observer } from 'mobx-react';
import { Modal, Form, Input, Select, DatePicker, Button, message, Descriptions, Tag, Divider } from 'antd';
import { http, hasPermission } from 'libs';
import moment from 'moment';
import S from './store';
import { AttachmentManager } from 'components';

const STATUS_TAG_MAP = {
  normal: { color: 'green', text: '正常' },
  expiring: { color: 'orange', text: '即将到期' },
  expired: { color: 'red', text: '已过期' },
};

// 与后端 ApprovalAttachmentConfig 保持一致的允许扩展名
const ACCEPT = '.pdf,.jpg,.jpeg,.png,.gif,.bmp,.webp,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.zip,.rar,.7z';

export default observer(function () {
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(false);
  const [viewMode, setViewMode] = useState(false);
  const mountedRef = useRef(true);

  React.useEffect(() => {
    mountedRef.current = true;
    return () => { mountedRef.current = false; };
  }, []);

  React.useEffect(() => {
    // 详情模式（点击"查看"或双击行）
    if (S.detailVisible) {
      setViewMode(true);
      return;
    }
    setViewMode(false);
    const initialValues = { ...S.record };
    if (initialValues.valid_from) {
      initialValues.valid_from = moment(initialValues.valid_from);
    }
    if (initialValues.valid_to) {
      initialValues.valid_to = moment(initialValues.valid_to);
    }
    form.setFieldsValue(initialValues);
    // 加载可选责任人列表（必填项需要）
    S.fetchResponsibleUsers();
  }, [form]);

  function handleSubmit() {
    form.validateFields().then(() => {
      setLoading(true);
      const formData = form.getFieldsValue();
      // 日期转换：moment -> 'YYYY-MM-DD'
      if (formData.valid_from) {
        formData.valid_from = formData.valid_from.format('YYYY-MM-DD');
      }
      if (formData.valid_to) {
        formData.valid_to = formData.valid_to.format('YYYY-MM-DD');
      }
      // 前端日期校验（即时反馈，后端仍会最终校验）
      if (formData.valid_from && formData.valid_to && formData.valid_from > formData.valid_to) {
        message.error('起始日期不能晚于截止日期');
        setLoading(false);
        return;
      }
      if (S.record.id) {
        formData.id = S.record.id;
      }
      // 统一 POST 接口：带 id 走编辑分支，不带 id 走新增分支
      http.post('/api/radio-license/approvals/', formData)
        .then(() => {
          message.success('操作成功');
          S.formVisible = false;
          S.fetchRecords();
        })
        .catch(e => {
          console.error('[台站频率批复] 提交表单失败:', e);
        })
        .finally(() => {
          if (mountedRef.current) setLoading(false);
        });
    });
  }

  const info = S.record;

  // ===== 详情模式 =====
  if (viewMode) {
    const tagInfo = STATUS_TAG_MAP[info.computed_status] || STATUS_TAG_MAP.normal;
    return (
      <Modal
        visible
        width={900}
        title="批复详情"
        footer={[
          <Button key="close" onClick={() => S.detailVisible = false}>关闭</Button>,
          hasPermission('radio_license.approval.edit') && (
            <Button key="edit" type="primary" onClick={() => {
              S.detailVisible = false;
              S.showForm(info);
            }}>编辑</Button>
          ),
        ]}
        onCancel={() => S.detailVisible = false}>
        <Descriptions bordered column={2}>
          <Descriptions.Item label="文件名称" span={2}>{info.name}</Descriptions.Item>
          <Descriptions.Item label="文件编号">{info.doc_no}</Descriptions.Item>
          <Descriptions.Item label="批复频率">{info.frequency_text}</Descriptions.Item>
          <Descriptions.Item label="起始日期">{info.valid_from}</Descriptions.Item>
          <Descriptions.Item label="截止日期">{info.valid_to}</Descriptions.Item>
          <Descriptions.Item label="状态">
            <Tag color={tagInfo.color}>{tagInfo.text}</Tag>
          </Descriptions.Item>
          <Descriptions.Item label="剩余天数">
            {info.days_left == null
              ? '-'
              : (info.days_left < 0
                ? <span style={{ color: '#ff4d4f' }}>已过期 {Math.abs(info.days_left)} 天</span>
                : <span style={{ color: info.days_left <= 60 ? '#fa8c16' : '#52c41a' }}>{info.days_left} 天</span>)}
          </Descriptions.Item>
          <Descriptions.Item label="责任人">{info.responsible_user_name || '-'}</Descriptions.Item>
          <Descriptions.Item label="附件数">{info.attachment_count ?? 0}</Descriptions.Item>
          <Descriptions.Item label="备注" span={2}>
            <div style={{ whiteSpace: 'pre-wrap', maxHeight: 200, overflowY: 'auto' }}>
              {info.remark || '-'}
            </div>
          </Descriptions.Item>
        </Descriptions>

        <Divider orientation="left">附件</Divider>
        {info.id && (
          <AttachmentManager
            module="radio_license"
            recordId={info.id}
            listUrl={`/api/radio-license/approvals/${info.id}/attachments/`}
            uploadUrl={`/api/radio-license/approvals/${info.id}/attachments/`}
            deleteUrl="/api/radio-license/approvals/attachments/"
            downloadUrlPrefix="/api/radio-license/approvals/attachments/"
            previewUrlPrefix="/api/radio-license/approvals/attachments/"
            uploadPerm="radio_license.approval.view&radio_license.attachment.upload"
            deletePerm="radio_license.approval.view&radio_license.attachment.delete"
            previewPerm="radio_license.approval.view"
            downloadPerm="radio_license.approval.view&radio_license.attachment.download"
            maxFileSize={50}
            multiple
            accept={ACCEPT}
          />
        )}

        <Descriptions bordered column={2} style={{ marginTop: 16 }}>
          <Descriptions.Item label="创建人">{info.created_by_name || '-'}</Descriptions.Item>
          <Descriptions.Item label="创建时间">{info.created_at || '-'}</Descriptions.Item>
          <Descriptions.Item label="更新人">{info.updated_by_name || '-'}</Descriptions.Item>
          <Descriptions.Item label="更新时间">{info.updated_at || '-'}</Descriptions.Item>
        </Descriptions>
      </Modal>
    );
  }

  // ===== 新增 / 编辑模式 =====
  const initialValues = { ...info };
  if (initialValues.valid_from) {
    initialValues.valid_from = moment(initialValues.valid_from);
  }
  if (initialValues.valid_to) {
    initialValues.valid_to = moment(initialValues.valid_to);
  }

  return (
    <Modal
      visible
      width={720}
      maskClosable={false}
      title={S.record.id ? '编辑批复' : '新建批复'}
      onCancel={() => S.formVisible = false}
      confirmLoading={loading}
      onOk={handleSubmit}>
      <Form form={form} initialValues={initialValues} labelCol={{ span: 6 }} wrapperCol={{ span: 16 }}>
        <Form.Item required name="name" label="文件名称" rules={[{ required: true, message: '请输入文件名称' }]}>
          <Input placeholder="请输入文件名称" maxLength={200} />
        </Form.Item>
        <Form.Item required name="doc_no" label="文件编号" rules={[{ required: true, message: '请输入文件编号' }]}>
          <Input placeholder="请输入文件编号" maxLength={100} />
        </Form.Item>
        <Form.Item required name="frequency_text" label="批复频率" rules={[{ required: true, message: '请输入批复频率' }]}>
          <Input placeholder="如 88-108 MHz" maxLength={200} />
        </Form.Item>
        <Form.Item required name="valid_from" label="起始日期" rules={[{ required: true, message: '请选择起始日期' }]}>
          <DatePicker style={{ width: '100%' }} placeholder="请选择起始日期" />
        </Form.Item>
        <Form.Item required name="valid_to" label="截止日期" rules={[{ required: true, message: '请选择截止日期' }]}>
          <DatePicker style={{ width: '100%' }} placeholder="请选择截止日期" />
        </Form.Item>
        <Form.Item
          required
          name="responsible_user_id"
          label="责任人"
          rules={[{ required: true, message: '请选择责任人' }]}>
          <Select
            showSearch
            allowClear
            placeholder="请选择责任人（按姓名/账号搜索）"
            optionFilterProp="label"
            loading={!S.responsibleUsersLoaded}
            notFoundContent={S.responsibleUsersLoaded ? '暂无可选用户' : '加载中...'}
            onChange={(value) => {
              // 选中后自动回填姓名（后端也会校验并覆盖一次）
              const u = S.responsibleUsers.find(x => x.id === value);
              if (u) form.setFieldsValue({ responsible_user_name: u.nickname || u.username });
            }}>
            {S.responsibleUsers.map(u => (
              <Select.Option
                key={u.id}
                value={u.id}
                label={`${u.nickname} ${u.username}`}>
                {u.nickname}（{u.username}）
              </Select.Option>
            ))}
          </Select>
        </Form.Item>
        {/* 隐藏字段，提交时同步携带姓名（后端会自动用真名覆盖） */}
        <Form.Item name="responsible_user_name" hidden noStyle>
          <Input />
        </Form.Item>
        <Form.Item name="remark" label="备注">
          <Input.TextArea rows={3} placeholder="请输入备注（非必填）" maxLength={500} />
        </Form.Item>
      </Form>
    </Modal>
  );
});
