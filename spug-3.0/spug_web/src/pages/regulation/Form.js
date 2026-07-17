/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React, { useState, useCallback } from 'react';
import { observer } from 'mobx-react';
import {
  Modal, Form, Input, Select, DatePicker, Button, message,
  Descriptions, Tag, Divider, Space, Table, Upload, Popconfirm,
} from 'antd';
import {
  UploadOutlined, DownloadOutlined, DeleteOutlined, EyeOutlined,
} from '@ant-design/icons';
import { http, hasPermission } from 'libs';
import moment from 'moment';
import S from './store';

const ALLOWED_ACCEPT = '.pdf,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.txt,.md,.png,.jpg,.jpeg,.gif,.bmp,.webp';
const MAX_FILE_SIZE_MB = 200;

export default observer(function () {
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(false);
  const [attachments, setAttachments] = useState([]);
  const [uploading, setUploading] = useState(false);
  const [previewVisible, setPreviewVisible] = useState(false);
  const [previewUrl, setPreviewUrl] = useState('');
  const [previewFileName, setPreviewFileName] = useState('');
  const [previewType, setPreviewType] = useState('kkfileview');
  const viewMode = !!S.detailVisible;
  const info = S.record || {};
  const canEdit = hasPermission('document.regulation.edit');
  const canUpload = hasPermission('document.regulation.upload');
  const canDownload = hasPermission('document.regulation.download');
  const canView = hasPermission('document.regulation.view');

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
    if (info.id) {
      http.get(`/api/regulation/${info.id}/attachments/`)
        .then(data => setAttachments(data || []));
    } else {
      setAttachments([]);
    }
  }, []);

  function fetchAttachments() {
    if (info.id) {
      http.get(`/api/regulation/${info.id}/attachments/`)
        .then(data => setAttachments(data || []));
    }
  }

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

  function handleUpload(options) {
    const { file, onSuccess, onError } = options;
    if (file.size > MAX_FILE_SIZE_MB * 1024 * 1024) {
      message.error(`文件大小不能超过 ${MAX_FILE_SIZE_MB}MB`);
      if (onError) onError(new Error('文件过大'));
      return;
    }
    setUploading(true);
    const formData = new FormData();
    formData.append('file', file);
    http.post(`/api/regulation/${info.id}/attachments/upload/`, formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 600000,
    })
      .then(data => {
        message.success('上传成功');
        fetchAttachments();
        if (onSuccess) onSuccess(data, file);
      })
      .catch(e => {
        message.error(e?.message || '上传失败');
        if (onError) onError(e);
      })
      .finally(() => setUploading(false));
  }

  function handleDownload(record) {
    http.get(`/api/regulation/${info.id}/attachments/${record.id}/download/`, {
      responseType: 'blob',
    }).then(response => {
      const blob = new Blob([response.data], {
        type: response.headers['content-type'] || 'application/octet-stream',
      });
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = record.file_name || 'attachment';
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      window.URL.revokeObjectURL(url);
    }).catch(e => message.error(e?.message || e || '下载失败'));
  }

  function handleDeleteAttachment(record) {
    http.delete(`/api/regulation/${info.id}/attachments/${record.id}/`)
      .then(() => {
        message.success('删除成功');
        fetchAttachments();
      })
      .catch(e => message.error(e?.message || '删除失败'));
  }

  const handlePreview = useCallback((record) => {
    http.get(`/api/regulation/${info.id}/attachments/${record.id}/preview-url/`)
      .then(data => {
        setPreviewUrl(data.preview_url);
        setPreviewFileName(data.file_name || record.file_name);
        setPreviewType(data.preview_type || 'kkfileview');
        setPreviewVisible(true);
      })
      .catch(e => message.error(e?.message || '获取预览地址失败'));
  }, [info.id]);

  function closePreview() {
    setPreviewVisible(false);
    setPreviewUrl('');
    setPreviewType('kkfileview');
  }

  // ==================== 详情模式 ====================
  if (viewMode) {
    const statusTag = STATUS_TAG_MAP[info.status] || STATUS_TAG_MAP.active;
    return (
      <React.Fragment>
        <Form form={form} component={false} />
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
            <Table
              size="small"
              rowKey="id"
              dataSource={attachments}
              pagination={false}
              columns={[
                {
                  title: '文件名', dataIndex: 'file_name', ellipsis: true,
                  render: (text) => <span>{text}</span>,
                },
                {
                  title: '操作', width: 180,
                  render: (_, record) => (
                    <Space>
                      {canView && record.previewable && (
                        <Button type="link" size="small" icon={<EyeOutlined />}
                          onClick={() => handlePreview(record)}>
                          预览
                        </Button>
                      )}
                      {canDownload && (
                        <Button type="link" size="small" icon={<DownloadOutlined />}
                          onClick={() => handleDownload(record)}>
                          下载
                        </Button>
                      )}
                      {canUpload && (
                        <Popconfirm title="确定删除此附件？" onConfirm={() => handleDeleteAttachment(record)}>
                          <Button type="link" size="small" danger icon={<DeleteOutlined />}>
                            删除
                          </Button>
                        </Popconfirm>
                      )}
                    </Space>
                  ),
                },
              ]}
            />
          )}
          {canUpload && info.id && (
            <div style={{ marginTop: 12 }}>
              <Upload customRequest={handleUpload} showUploadList={false} accept={ALLOWED_ACCEPT}>
                <Button type="primary" icon={<UploadOutlined />} loading={uploading}>
                  上传附件
                </Button>
              </Upload>
              <span style={{ color: '#999', fontSize: 12, marginLeft: 12 }}>
                支持 PDF/Word/Excel/PPT/图片/文本，单文件最大 {MAX_FILE_SIZE_MB}MB
              </span>
            </div>
          )}

        </Modal>
        <Modal
          visible={previewVisible}
          width="90vw"
          title={`${previewFileName || '附件预览'}${previewType === 'kkfileview' ? ' - kkFileView' : ''}`}
          footer={null}
          destroyOnClose
          onCancel={closePreview}
          bodyStyle={{ padding: 0, height: '80vh' }}
        >
          {previewUrl && (
            <iframe
              title={previewFileName || '附件预览'}
              src={previewUrl}
              style={{ width: '100%', height: '100%', border: 0 }}
            />
          )}
        </Modal>
      </React.Fragment>
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
