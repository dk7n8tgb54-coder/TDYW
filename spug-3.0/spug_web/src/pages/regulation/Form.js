/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright: (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React, { useState, useCallback } from 'react';
import { observer } from 'mobx-react';
import {
  Modal, Form, Input, Select, DatePicker, Button, message,
  Descriptions, Tag, Divider,
} from 'antd';
import { http, hasPermission } from 'libs';
import moment from 'moment';
import S from './store';
import { AttachmentManager } from 'components';

const ALLOWED_ACCEPT = '.pdf,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.txt,.md,.png,.jpg,.jpeg,.gif,.bmp,.webp';
const MAX_FILE_SIZE_MB = 200;

export default observer(function () {
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(false);
  const viewMode = !!S.detailVisible;
  const info = S.record || {};
  const canEdit = hasPermission('document.regulation.edit');

  React.useEffect(() => {
    const initialValues = { ...info };
    if (!initialValues.status) {
      initialValues.status = 'active';
    }
    ['publish_date', 'effective_date'].forEach(f => {
      if (initialValues[f]) {
        initialValues[f] = moment(initialValues[f]);
      }
    });
    form.setFieldsValue(initialValues);
  }, []);

  function handleSubmit() {
    form.validateFields().then(() => {
      const formData = form.getFieldsValue();
      ['publish_date', 'effective_date'].forEach(f => {
        if (formData[f]) {
          formData[f] = formData[f].format('YYYY-MM-DD');
        }
      });
      setLoading(true);
      http.post('/api/regulation/create/', formData)
        .then(() => {
          message.success('操作成功');
          S.formVisible = false;
          S.fetchRecords();
        })
        .catch(e => message.error(e.message || '操作失败'))
        .finally(() => setLoading(false));
    });
  }

  function handleUpdate() {
    form.validateFields().then(() => {
      const formData = form.getFieldsValue();
      ['publish_date', 'effective_date'].forEach(f => {
        if (formData[f]) {
          formData[f] = formData[f].format('YYYY-MM-DD');
        }
      });
      setLoading(true);
      http.put(`/api/regulation/${info.id}/`, formData)
        .then(() => {
          message.success('编辑成功');
          S.formVisible = false;
          S.fetchRecords();
        })
        .catch(e => message.error(e.message || '操作失败'))
        .finally(() => setLoading(false));
    });
  }

  // 规章附件下载适配器：复用 Blob 下载方式（responseType: blob）
  const downloadRegulationAttachment = useCallback((attachment) => {
    return http.get(`/api/regulation/${info.id}/attachments/${attachment.id}/download/`, {
      responseType: 'blob',
    }).then(response => {
      const blob = new Blob([response.data], {
        type: (response.headers && (response.headers['content-type'] || response.headers['Content-Type'])) || 'application/octet-stream',
      });
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = attachment.file_name || 'attachment';
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      window.URL.revokeObjectURL(url);
    });
  }, [info.id]);

  // ==================== 详情模式 ====================
  if (viewMode) {
    const statusTag = STATUS_TAG_MAP[info.status] || STATUS_TAG_MAP.active;
    return (
      <Modal
        visible
        width={900}
        title="规章详情"
        footer={[
          <Button key="close" onClick={() => S.detailVisible = false}>关闭</Button>,
          canEdit && info.status !== 'retired' && (
            <Button key="edit" type="primary" onClick={() => {
              S.detailVisible = false;
              S.showForm(info);
            }}>编辑</Button>
          ),
        ]}
        onCancel={() => S.detailVisible = false}
      >
        <Descriptions bordered column={2}>
          <Descriptions.Item label="规章名称" span={2}>{info.title || '-'}</Descriptions.Item>
          <Descriptions.Item label="规章编号">{info.rule_no || '-'}</Descriptions.Item>
          <Descriptions.Item label="所属分类">{info.category_name || '-'}</Descriptions.Item>
          <Descriptions.Item label="发文单位">{info.issuing_authority || '-'}</Descriptions.Item>
          <Descriptions.Item label="业务类型">{info.biz_type || '-'}</Descriptions.Item>
          <Descriptions.Item label="状态"><Tag color={statusTag.color}>{statusTag.text}</Tag></Descriptions.Item>
          <Descriptions.Item label="发布日期">{info.publish_date || '-'}</Descriptions.Item>
          <Descriptions.Item label="生效日期" span={2}>{info.effective_date || '-'}</Descriptions.Item>
        </Descriptions>

        <Divider orientation="left">附件</Divider>
        {info.id && (
          <AttachmentManager
            module="regulation"
            objectType="regulation"
            recordId={info.id}
            listUrl={`/api/regulation/${info.id}/attachments/`}
            uploadUrl={`/api/regulation/${info.id}/attachments/upload/`}
            deleteRequest={attachment => (
              http.delete(`/api/regulation/${info.id}/attachments/${attachment.id}/`)
            )}
            downloadRequest={downloadRegulationAttachment}
            previewRequest={attachment => (
              http.get(`/api/regulation/${info.id}/attachments/${attachment.id}/preview-url/`)
            )}
            readOnly={false}
            uploadPerm="document.regulation.upload"
            deletePerm="document.regulation.upload"
            downloadPerm="document.regulation.download"
            previewPerm="document.regulation.view"
            maxFileSize={MAX_FILE_SIZE_MB}
            accept={ALLOWED_ACCEPT}
            uploadMode="dragger"
            multiple
            maxFilesPerBatch={20}
            hiddenColumns={['file_size', 'uploaded_by_name', 'created_at']}
          />
        )}
      </Modal>
    );
  }

  // ==================== 新建/编辑模式 ====================
  return (
    <Modal
      visible
      width={760}
      maskClosable={false}
      title={info.id ? '编辑规章' : '新建规章'}
      onCancel={() => S.formVisible = false}
      confirmLoading={loading}
      onOk={info.id ? handleUpdate : handleSubmit}
    >
      <Form form={form} labelCol={{ span: 6 }} wrapperCol={{ span: 16 }}>
        <Form.Item name="title" label="规章名称" rules={[{ required: true, message: '请输入规章名称' }]}>
          <Input placeholder="如：空中交通管理" />
        </Form.Item>
        <Form.Item name="rule_no" label="规章编号" rules={[{ required: true, message: '请输入规章编号' }]}>
          <Input placeholder="如：Doc.4444" />
        </Form.Item>
        <Form.Item name="category_id" label="所属分类">
          <Select allowClear placeholder="请选择分类" notFoundContent="无可用分类">
            {renderCategoryOptions(S.categories)}
          </Select>
        </Form.Item>
        <Form.Item name="issuing_authority" label="发文单位">
          <Input placeholder="如：国际民航组织" />
        </Form.Item>
        <Form.Item name="biz_type" label="业务类型">
          <Input placeholder="如：空管" />
        </Form.Item>
        <Form.Item name="status" label="状态" rules={[{ required: true }]}>
          <Select placeholder="请选择状态">
            {S.statusOptions.map(item => (
              <Select.Option value={item.value} key={item.value}>{item.label}</Select.Option>
            ))}
          </Select>
        </Form.Item>
        <Form.Item name="publish_date" label="发布日期">
          <DatePicker style={{ width: '100%' }} />
        </Form.Item>
        <Form.Item name="effective_date" label="生效日期">
          <DatePicker style={{ width: '100%' }} />
        </Form.Item>
      </Form>
    </Modal>
  );
});

const STATUS_TAG_MAP = {
  active: { color: 'green', text: '现行' },
  retired: { color: 'red', text: '已废止' },
};

// 递归渲染分类选项（扁平化树）
function renderCategoryOptions(categories, prefix = '') {
  const options = [];
  for (const cat of categories) {
    const label = prefix + cat.name;
    if (cat.is_leaf) {
      options.push(
        <Select.Option value={cat.id} key={cat.id}>{label}</Select.Option>
      );
    }
    if (cat.children && cat.children.length > 0) {
      options.push(...renderCategoryOptions(cat.children, label + ' / '));
    }
  }
  return options;
}
