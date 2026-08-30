/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React, { useState } from 'react';
import { observer } from 'mobx-react';
import { Modal, Form, Input, Select, DatePicker, InputNumber, Radio, Button, message, Descriptions, Tag, Divider } from 'antd';
import { http, hasPermission } from 'libs';
import moment from 'moment';
import S from './store';
import { AttachmentManager } from 'components';

const STATUS_TAG_MAP = {
  normal: {color: 'green', text: '正常'},
  expired: {color: 'default', text: '已关闭'},
};

export default observer(function () {
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(false);
  const viewMode = !!S.detailVisible;
  const info = S.record || {};

  React.useEffect(() => {
    S.fetchResponsibleUsers();
  }, []);

  const initialValues = {
    ...info,
    has_fee: !!info.has_fee,
  };
  if (initialValues.valid_start_date) {
    initialValues.valid_start_date = moment(initialValues.valid_start_date);
  }
  if (initialValues.valid_end_date) {
    initialValues.valid_end_date = moment(initialValues.valid_end_date);
  }

  function handleSubmit() {
    form.validateFields().then(() => {
      const formData = form.getFieldsValue();
      if (formData.valid_start_date) {
        formData.valid_start_date = formData.valid_start_date.format('YYYY-MM-DD');
      }
      if (formData.valid_end_date) {
        formData.valid_end_date = formData.valid_end_date.format('YYYY-MM-DD');
      }
      if (!formData.has_fee) {
        formData.fee_amount = null;
        formData.fee_detail = '';
      }
      if (S.record.id) {
        formData.id = S.record.id;
      }

      setLoading(true);
      http.post('/api/contract-agreement/', formData)
        .then(() => {
          message.success('操作成功');
          S.formVisible = false;
          S.fetchRecords();
        })
        .catch(e => {
          message.error(e.message || '操作失败，请稍后重试');
        })
        .finally(() => setLoading(false));
    });
  }

  function renderDaysLeft(record) {
    if (record.days_left === undefined || record.days_left === null) return '-';
    if (record.days_left < 0) {
      return <span style={{color: '#8c8c8c'}}>已关闭 {Math.abs(record.days_left)} 天</span>;
    }
    return <span>{record.days_left} 天</span>;
  }

  if (viewMode) {
    const statusTag = STATUS_TAG_MAP[info.computed_status || info.status] || STATUS_TAG_MAP.normal;
    return (
      <Modal
        visible
        width={900}
        title="合同协议详情"
        footer={[
          <Button key="close" onClick={() => S.detailVisible = false}>关闭</Button>,
          hasPermission('contract_agreement.agreement.edit') && (
            <Button key="edit" type="primary" onClick={() => {
              S.detailVisible = false;
              S.showForm(info);
            }}>编辑</Button>
          ),
        ]}
        onCancel={() => S.detailVisible = false}>
        <Descriptions bordered column={2}>
          <Descriptions.Item label="合同名称">{info.contract_name || '-'}</Descriptions.Item>
          <Descriptions.Item label="合同编号">{info.contract_no || '-'}</Descriptions.Item>
          <Descriptions.Item label="类型">{info.contract_type_display || '-'}</Descriptions.Item>
          <Descriptions.Item label="起始日期">{info.valid_start_date || '-'}</Descriptions.Item>
          <Descriptions.Item label="截止日期">{info.valid_end_date || '-'}</Descriptions.Item>
          <Descriptions.Item label="剩余天数">{renderDaysLeft(info)}</Descriptions.Item>
          <Descriptions.Item label="责任人">{info.responsible_user_name || '-'}</Descriptions.Item>
          <Descriptions.Item label="费用">{info.has_fee ? `人民币 ${info.fee_amount || '0.00'}` : '无'}</Descriptions.Item>
          <Descriptions.Item label="状态"><Tag color={statusTag.color}>{statusTag.text}</Tag></Descriptions.Item>
          <Descriptions.Item label="签约方" span={2}>{info.signing_party || '-'}</Descriptions.Item>
          <Descriptions.Item label="费用详细数据" span={2}>
            <div style={{whiteSpace: 'pre-wrap'}}>{info.fee_detail || '-'}</div>
          </Descriptions.Item>
          <Descriptions.Item label="备注" span={2}>
            <div style={{whiteSpace: 'pre-wrap'}}>{info.remark || '-'}</div>
          </Descriptions.Item>
        </Descriptions>

        <Divider orientation="left">附件</Divider>
        {info.id && (
          <AttachmentManager
            module="contract_agreement"
            objectType="agreement"
            recordId={info.id}
            listUrl={`/api/contract-agreement/${info.id}/attachments/`}
            uploadUrl={`/api/contract-agreement/${info.id}/attachments/`}
            deleteUrl="/api/contract-agreement/attachments/"
            downloadUrlPrefix="/api/contract-agreement/attachments/"
            previewUrlPrefix="/api/contract-agreement/attachments/"
            readOnly={false}
            uploadPerm="contract_agreement.attachment.upload"
            deletePerm="contract_agreement.attachment.delete"
            previewPerm="contract_agreement.agreement.view"
            maxFileSize={50}
            multiple
            maxFilesPerBatch={20}
            accept=".pdf,.jpg,.jpeg,.png,.gif,.bmp,.webp,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.zip,.rar,.7z"
          />
        )}

        <Descriptions bordered column={2} style={{marginTop: 16}}>
          <Descriptions.Item label="创建人">{info.created_by_name || '-'}</Descriptions.Item>
          <Descriptions.Item label="创建时间">{info.created_at || '-'}</Descriptions.Item>
          <Descriptions.Item label="更新人">{info.updated_by_name || '-'}</Descriptions.Item>
          <Descriptions.Item label="更新时间">{info.updated_at || '-'}</Descriptions.Item>
        </Descriptions>
      </Modal>
    );
  }

  return (
    <Modal
      visible
      width={760}
      maskClosable={false}
      title={S.record.id ? '编辑合同协议' : '新建合同协议'}
      onCancel={() => S.formVisible = false}
      confirmLoading={loading}
      onOk={handleSubmit}>
      <Form form={form} initialValues={initialValues} labelCol={{span: 6}} wrapperCol={{span: 15}}>
        <Form.Item name="contract_name" label="合同名称" rules={[{required: true, message: '请输入合同名称'}]}>
          <Input placeholder="请输入合同名称"/>
        </Form.Item>
        <Form.Item name="contract_no" label="合同编号">
          <Input placeholder="请输入合同编号（选填）"/>
        </Form.Item>
        <Form.Item name="contract_type" label="类型" rules={[{required: true, message: '请选择类型'}]}>
          <Select placeholder="请选择类型">
            {S.contractTypeOptions.map(item => (
              <Select.Option value={item.value} key={item.value}>{item.label}</Select.Option>
            ))}
          </Select>
        </Form.Item>
        <Form.Item name="valid_start_date" label="起始日期" rules={[{required: true, message: '请选择起始日期'}]}>
          <DatePicker style={{width: '100%'}} placeholder="请选择起始日期"/>
        </Form.Item>
        <Form.Item
          name="valid_end_date"
          label="截止日期"
          rules={[
            {required: true, message: '请选择截止日期'},
            ({getFieldValue}) => ({
              validator(_, value) {
                const start = getFieldValue('valid_start_date');
                if (!start || !value || !value.isBefore(start, 'day')) {
                  return Promise.resolve();
                }
                return Promise.reject(new Error('截止日期不能早于起始日期'));
              }
            })
          ]}>
          <DatePicker style={{width: '100%'}} placeholder="请选择截止日期"/>
        </Form.Item>
        <Form.Item
          required
          name="responsible_user_id"
          label="责任人"
          rules={[{required: true, message: '请选择责任人'}]}>
          <Select
            showSearch
            allowClear
            placeholder="请选择责任人（必填，按姓名/账号搜索）"
            optionFilterProp="label"
            loading={!S.responsibleUsersLoaded}
            notFoundContent={S.responsibleUsersLoaded ? '暂无可选用户' : '加载中...'}
            onChange={(value) => {
              const u = S.responsibleUsers.find(x => x.id === value);
              if (u) form.setFieldsValue({responsible_user_name: u.nickname || u.username});
            }}>
            {S.responsibleUsers.map(u => (
              <Select.Option key={u.id} value={u.id} label={`${u.nickname} ${u.username}`}>
                {u.nickname}（{u.username}）
              </Select.Option>
            ))}
          </Select>
        </Form.Item>
        <Form.Item name="responsible_user_name" hidden noStyle>
          <Input/>
        </Form.Item>
        <Form.Item name="has_fee" label="费用" rules={[{required: true}]}>
          <Radio.Group>
            <Radio value={true}>有</Radio>
            <Radio value={false}>无</Radio>
          </Radio.Group>
        </Form.Item>
        <Form.Item noStyle shouldUpdate={(prev, cur) => prev.has_fee !== cur.has_fee}>
          {({getFieldValue}) => getFieldValue('has_fee') ? (
            <>
              <Form.Item name="fee_amount" label="费用金额" rules={[{required: true, message: '请输入费用金额'}]}>
                <InputNumber min={0} precision={2} style={{width: '100%'}} addonBefore="人民币"/>
              </Form.Item>
              <Form.Item name="fee_detail" label="费用详细数据">
                <Input.TextArea rows={4} placeholder="可填写付款方式、付款节点、服务费说明等"/>
              </Form.Item>
            </>
          ) : null}
        </Form.Item>
        <Form.Item name="signing_party" label="签约方" rules={[{required: true, message: '请输入签约方'}]}>
          <Input.TextArea rows={3} placeholder="请输入签约方"/>
        </Form.Item>
        <Form.Item name="remark" label="备注">
          <Input.TextArea rows={3} placeholder="请输入备注"/>
        </Form.Item>
      </Form>
    </Modal>
  );
});
