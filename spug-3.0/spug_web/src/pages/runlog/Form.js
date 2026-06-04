/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React, { useState, useEffect, useMemo } from 'react';
import { observer } from 'mobx-react';
import { Modal, Form, Input, Select, DatePicker, Button, message, Descriptions, Tabs, Upload, Image, Card, Spin } from 'antd';
import { PlusOutlined, PlusCircleOutlined, CloseOutlined, EditOutlined } from '@ant-design/icons';
import { http, hasPermission } from 'libs';
import { X_TOKEN } from 'libs/functools';
import moment from 'moment';
import S from './store';

const { Option } = Select;
const { TabPane } = Tabs;

export default observer(function () {
  const [form] = Form.useForm();
  const [updateForm] = Form.useForm();  // 首次动态表单
  const [loading, setLoading] = useState(false);
  const [viewMode, setViewMode] = useState(false);
  const [updatesList, setUpdatesList] = useState([]);
  const [addUpdateVisible, setAddUpdateVisible] = useState(false);
  const [editUpdateVisible, setEditUpdateVisible] = useState(false);
  const [editingUpdate, setEditingUpdate] = useState(null);
  const [attachmentList, setAttachmentList] = useState([]);  // 附件列表
  const [uploading, setUploading] = useState(false);  // 上传状态
  // 附件预览状态
  const [previewVisible, setPreviewVisible] = useState(false);
  const [previewUrl, setPreviewUrl] = useState('');
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState('');
  const [previewFileName, setPreviewFileName] = useState('');

  // 获取附件预览URL
  const fetchPreviewUrl = (attachmentPath) => {
    const fileName = attachmentPath.split('/').pop() || '附件';
    setPreviewFileName(fileName);
    setPreviewLoading(true);
    setPreviewError('');

    http.get('/api/runlog/attachment/preview_url/', { params: { path: attachmentPath } })
      .then(data => {
        setPreviewUrl(data.preview_url);
        setPreviewVisible(true);
      })
      .catch(err => {
        const errorMsg = err?.error || err?.message || '获取预览失败，请下载后查看';
        setPreviewError(errorMsg);
        message.error(errorMsg);
      })
      .finally(() => {
        setPreviewLoading(false);
      });
  };

  // 关闭预览弹窗
  const handleClosePreview = () => {
    setPreviewVisible(false);
    setPreviewUrl('');
    setPreviewError('');
  };

  function handleSubmit() {
    setLoading(true);
    const formData = form.getFieldsValue();
    
    // 编辑时需要添加 id
    if (S.record.id) {
      formData['id'] = S.record.id;
    } else {
      // 新建时需要首次动态
      const updateData = updateForm.getFieldsValue();
      formData['first_update'] = updateData;

      if (updateData['update_date']) {
        updateData['update_date'] = updateData['update_date'].format('YYYY-MM-DD');
      }
    }

    const apiUrl = S.record.id ? '/api/runlog/' : '/api/runlog/';
    const httpMethod = S.record.id ? 'put' : 'post';

    http[httpMethod](apiUrl, formData)
      .then(() => {
        message.success('操作成功');
        S.formVisible = false;
        S.fetchRecords()
        S.fetchStatistics()
      }, () => setLoading(false))
  }

  function handleAddUpdate() {
    const updateData = updateForm.getFieldsValue();

    if (!updateData.update_date || !updateData.detail_content) {
      message.warning('请填写完整的动态信息');
      return;
    }

    console.log('[handleAddUpdate] 当前 attachmentList:', attachmentList);
    console.log('[handleAddUpdate] attachmentList 是否为数组:', Array.isArray(attachmentList));

    const formData = {
      runlog_id: S.record.id,
      update_date: updateData.update_date.format('YYYY-MM-DD'),
      recorder: sessionStorage.getItem('nickname') || '',
      detail_content: updateData.detail_content,
      attachments: attachmentList,  // 添加附件
    };

    console.log('[handleAddUpdate] 发送的 formData:', JSON.stringify(formData));
    console.log('[handleAddUpdate] 发送的 formData.attachments:', JSON.stringify(formData.attachments));

    http.post('/api/runlog/update/', formData)
      .then(res => {
        console.log('[handleAddUpdate] 添加成功, 响应:', res);
        message.success('动态添加成功');
        updateForm.resetFields();
        setAttachmentList([]);  // 清空附件列表
        setAddUpdateVisible(false);
        fetchUpdates();
        S.fetchRecords();
      })
      .catch(err => {
        console.error('[handleAddUpdate] 添加失败:', err);
      });
  }

  function handleEditUpdate(update) {
    // 打开编辑弹窗，填充现有数据
    setEditingUpdate(update);
    setAttachmentList(update.attachments || []);
    updateForm.setFieldsValue({
      update_date: moment(update.update_date),
      recorder: update.recorder,
      detail_content: update.detail_content,
    });
    setEditUpdateVisible(true);
  }

  function handleDeleteUpdate(update) {
    Modal.confirm({
      title: '删除确认',
      content: `确定要删除【${update.update_date}】的动态记录?`,
      onOk: () => {
        return http.delete('/api/runlog/update/', {params: {id: update.id}})
          .then(() => {
            message.success('删除成功');
            fetchUpdates();
            S.fetchRecords();
            S.fetchStatistics();
          })
      }
    })
  }

  function handleUpdateUpdate() {
    const updateData = updateForm.getFieldsValue();

    if (!updateData.update_date || !updateData.detail_content) {
      message.warning('请填写完整的动态信息');
      return;
    }

    const formData = {
      id: editingUpdate.id,
      runlog_id: S.record.id,
      update_date: updateData.update_date.format('YYYY-MM-DD'),
      recorder: sessionStorage.getItem('nickname') || '',
      detail_content: updateData.detail_content,
      attachments: attachmentList,
    };

    http.put('/api/runlog/update/', formData)
      .then(() => {
        message.success('动态更新成功');
        updateForm.resetFields();
        setAttachmentList([]);
        setEditUpdateVisible(false);
        setEditingUpdate(null);
        fetchUpdates();
        S.fetchRecords();
      });
  }

  // 附件上传处理
  const uploadProps = {
    name: 'file',
    action: '/api/runlog/upload/',
    accept: 'image/*,.pdf,.doc,.docx,.xls,.xlsx,.ppt,.pptx',
    listType: 'picture-card',
    headers: {
      'X-Token': X_TOKEN,
    },
    onChange: (info) => {
      console.log('Upload onChange:', info.file.status, info.fileList.length);

      // 只处理上传完成的文件
      if (info.file.status === 'done') {
        // 兼容两种响应格式：1) json_response格式 {data: {url:...}}  2) 直接格式 {url:...}
        const newUrl = info.file.response?.data?.url || info.file.response?.url;
        console.log('Upload response:', info.file.response, 'Extracted URL:', newUrl);
        if (newUrl) {
          // 避免重复添加
          if (!attachmentList.includes(newUrl)) {
            setAttachmentList(prev => [...prev, newUrl]);
          }
          message.success('附件上传成功');
        } else {
          console.error('附件上传失败：未获取到文件URL', info.file.response);
          message.error('附件上传失败：未获取到文件URL');
        }
      } else if (info.file.status === 'error') {
        console.log('Upload error:', info.file.response);
        const errorMsg = info.file.response?.error || info.file.response?.data?.error || '未知错误';
        message.error(`附件上传失败: ${errorMsg}`);
      }
    },
    beforeUpload: (file) => {
      console.log('Before upload:', file.name, file.type, file.size);
      // 允许的图片和Office文件类型
      const allowedTypes = [
        'image/jpeg', 'image/jpg', 'image/png', 'image/gif', 'image/webp',
        'application/pdf',
        'application/msword',
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        'application/vnd.ms-excel',
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        'application/vnd.ms-powerpoint',
        'application/vnd.openxmlformats-officedocument.presentationml.presentation',
      ];
      const isAllowed = allowedTypes.includes(file.type);
      if (!isAllowed) {
        message.error('只支持上传图片（ JPG、PNG、GIF、WebP）或Office文件（Word、Excel、PowerPoint、PDF）');
        return false;
      }
      const isLt50M = file.size / 1024 / 1024 < 50;
      if (!isLt50M) {
        message.error('文件大小不能超过50MB');
        return false;
      }
      return true;
    },
    onRemove: (file) => {
      console.log('onRemove:', file.url);
      // 移除时从 attachmentList 中删除
      const urlToRemove = file.url;
      if (urlToRemove) {
        setAttachmentList(prev => prev.filter(url => url !== urlToRemove));
      }
      return true;
    },
  };

  function fetchUpdates() {
    if (S.record.id) {
      console.log('[fetchUpdates] 开始获取动态, record.id:', S.record.id);
      http.get('/api/runlog/detail/', {params: {id: S.record.id}})
        .then(res => {
          console.log('[fetchUpdates] 原始响应 keys:', Object.keys(res));
          console.log('[fetchUpdates] 原始响应:', JSON.stringify(res).substring(0, 500));
          // json_response 返回结构是 {data: {...}, error: ""}，需要访问 res.data
          const data = res.data || res;
          console.log('[fetchUpdates] 解析后数据 keys:', Object.keys(data));
          console.log('[fetchUpdates] data.updates:', data.updates, 'length:', data.updates?.length);
          if (data.updates && data.updates.length > 0) {
            console.log('[fetchUpdates] 第一个 update 的 attachments:', data.updates[0].attachments);
          }
          setUpdatesList(data.updates || []);
          console.log('[fetchUpdates] 设置 updatesList 完成, 长度:', (data.updates || []).length);
          // 如果 S.record 没有完整数据，更新它
          if (data.id && (!S.record.event_title || !S.record.updates)) {
            Object.assign(S.record, data);
            console.log('[fetchUpdates] 更新 S.record 完成');
          }
        })
        .catch(err => {
          console.error('[fetchUpdates] 请求失败:', err);
        });
    } else {
      console.log('[fetchUpdates] record.id 不存在，不获取动态');
    }
  }

  useEffect(() => {
    // 加载事件类型列表
    S.fetchEventTypes();
    console.log('[useEffect] 触发, S.record.id:', S.record.id, 'isViewMode:', S.record.isViewMode);
    if (S.record.id) {
      console.log('[useEffect] 调用 fetchUpdates');
      fetchUpdates();  // 编辑模式下也需要加载动态列表
      if (S.record.isViewMode || !hasPermission('runlog.runlog.edit')) {
        setViewMode(true);
      } else {
        setViewMode(false);
      }
      // 如果是添加动态模式，直接打开添加动态弹窗
      if (S.record.isAddUpdateMode) {
        setAddUpdateVisible(true);
      }
    }
  }, [S.record.id]);

  const info = S.record;

  // 查看模式
  if (viewMode) {
    return (
      <Modal
        visible
        width={900}
        title="运行日志详情"
        footer={[
          <Button key="close" onClick={() => S.formVisible = false}>关闭</Button>
        ]}
        onCancel={() => S.formVisible = false}>
        <Descriptions bordered column={1}>
          <Descriptions.Item label="事件标题">{info.event_title}</Descriptions.Item>
          <Descriptions.Item label="事件类型">{info.event_type}</Descriptions.Item>
          <Descriptions.Item label="事件级别">{info.severity}</Descriptions.Item>
          <Descriptions.Item label="状态">{info.status_text}</Descriptions.Item>
          <Descriptions.Item label="系统名称">{info.system_name}</Descriptions.Item>
          <Descriptions.Item label="责任人">{info.responsible_user_name || '-'}</Descriptions.Item>
          <Descriptions.Item label="处理措施">
            <div style={{ whiteSpace: 'pre-wrap' }}>
              {info.resolution || '-'}
            </div>
          </Descriptions.Item>
          <Descriptions.Item label="动态记录">
            {updatesList.length === 0 ? (
              <div style={{textAlign: 'center', color: '#999'}}>
                暂无动态记录 (updatesList.length={updatesList.length}, info.updates={info.updates?.length})
              </div>
            ) : (
              updatesList.map(update => (
                <div key={update.id} style={{
                  marginBottom: 12,
                  padding: 8,
                  border: '1px solid #e8e8e8',
                  borderRadius: 4
                }}>
                  <div><strong>{update.update_date} [{update.sequence}] {update.recorder}</strong></div>
                  <div>{update.detail_content}</div>
                  {/* 显示附件列表 */}
                  {update.attachments && update.attachments.length > 0 && (
                    <div style={{ marginTop: 8 }}>
                      <div style={{ fontSize: 12, color: '#999', marginBottom: 4 }}>附件：</div>
                      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
                        {update.attachments.map((url, idx) => {
                          const fileName = url.split('/').pop() || `附件${idx + 1}`;
                          const isImage = /\.(jpg|jpeg|png|gif|webp)$/i.test(fileName);
                          if (isImage) {
                            return (
                              <Image
                                key={idx}
                                src={url}
                                width={100}
                                height={100}
                                style={{ objectFit: 'cover' }}
                              />
                            );
                          } else {
                            // 非图片文件点击使用kkfileview预览
                            return (
                              <a
                                key={idx}
                                onClick={(e) => {
                                  e.preventDefault();
                                  fetchPreviewUrl(url);
                                }}
                                href={url}
                                target="_blank"
                                rel="noopener noreferrer"
                                title="点击预览"
                                style={{
                                  display: 'inline-flex',
                                  alignItems: 'center',
                                  justifyContent: 'center',
                                  width: 100,
                                  height: 100,
                                  border: '1px solid #d9d9d9',
                                  borderRadius: 4,
                                  textAlign: 'center',
                                  fontSize: 12,
                                  color: '#1890ff',
                                  textDecoration: 'none',
                                  padding: 8,
                                  overflow: 'hidden',
                                  cursor: 'pointer',
                                }}
                              >
                                {fileName}
                              </a>
                            );
                          }
                        })}
                      </div>
                    </div>
                  )}
                </div>
              ))
            )}
          </Descriptions.Item>
        </Descriptions>
      </Modal>
    )
  }

  // 编辑/新建模式
  const initialValues = {...info};
  if (initialValues.deadline) {
    initialValues.deadline = moment(initialValues.deadline);
  }
  
  const updateInitialValues = {};
  if (!S.record.id) {
    // 新建时初始化首次动态
    updateInitialValues.update_date = moment();
    updateInitialValues.recorder = sessionStorage.getItem('nickname') || '';
  }

  return (
    <Modal
      visible
      width={900}
      maskClosable={false}
      title={S.record.id ? '编辑运行日志' : '新建运行日志'}
      onCancel={() => S.formVisible = false}
      confirmLoading={loading}
      onOk={handleSubmit}>
      <Tabs defaultActiveKey={S.record.isAddUpdateMode ? "updates" : "event"}>
        <TabPane tab="事件信息" key="event">
          <Form form={form} initialValues={initialValues} labelCol={{span: 5}} wrapperCol={{span: 14}}>
            <Form.Item required name="event_title" label="事件标题">
              <Input placeholder="请输入事件标题"/>
            </Form.Item>
            <Form.Item required name="event_type" label="事件类型">
              <Select placeholder="请选择事件类型">
                {S.eventTypes.map(type => (
                  <Option key={type.id} value={type.name}>{type.name}</Option>
                ))}
              </Select>
            </Form.Item>
            <Form.Item required name="system_name" label="系统名称">
              <Input placeholder="请输入系统名称"/>
            </Form.Item>
            <Form.Item required name="severity" label="事件级别">
              <Select placeholder="请选择事件级别">
                <Option value="P0">P0-紧急</Option>
                <Option value="P1">P1-重要</Option>
                <Option value="P2">P2-一般</Option>
              </Select>
            </Form.Item>
            <Form.Item name="responsible_user_name" label="责任人">
              <Input placeholder="请输入责任人（选填）"/>
            </Form.Item>
            {S.record.id && (
              <>
                <Form.Item name="status" label="处理状态">
                  <Select placeholder="请选择状态">
                    <Option value="in_progress">处理中</Option>
                    <Option value="resolved">已解决</Option>
                  </Select>
                </Form.Item>
                <Form.Item name="resolution" label="处理措施">
                  <Input.TextArea rows={4} placeholder="事件解决后的最终方案总结，与动态记录不同，此处填写结案报告"/>
                </Form.Item>
              </>
            )}
          </Form>
          
          {!S.record.id && (
            <div style={{ marginTop: 16, padding: 16, backgroundColor: '#f5f5f5', borderRadius: 4 }}>
              <h4>首次动态（必填）</h4>
              <Form form={updateForm} initialValues={updateInitialValues} labelCol={{span: 5}} wrapperCol={{span: 14}}>
                <Form.Item required name="update_date" label="动态日期">
                  <DatePicker style={{width: '100%'}} placeholder="请选择日期"/>
                </Form.Item>
                <Form.Item required name="recorder" label="记录人">
                  <Input disabled placeholder="自动填充当前用户"/>
                </Form.Item>
                <Form.Item required name="detail_content" label="详细记录">
                  <Input.TextArea rows={6} placeholder="请输入详细记录"/>
                </Form.Item>
              </Form>
            </div>
          )}
        </TabPane>
        
        {S.record.id && (
          <TabPane tab="动态记录" key="updates">
            <div style={{ marginBottom: 16 }}>
              {!addUpdateVisible && !editUpdateVisible && (
                <Button type="primary" icon={<PlusOutlined/>}                 onClick={() => {
                  updateForm.resetFields();
                  updateForm.setFieldsValue({
                    update_date: moment(),
                    recorder: sessionStorage.getItem('nickname') || ''
                  });
                  setAttachmentList([]);
                  setAddUpdateVisible(true);
                }}>
                  添加动态
                </Button>
              )}
            </div>

            {/* 内联添加动态表单 */}
            {addUpdateVisible && (
              <Card size="small" title="添加动态" style={{ marginBottom: 16 }} extra={
                <Button type="link" icon={<CloseOutlined/>} onClick={() => { setAddUpdateVisible(false); setAttachmentList([]); }}/>
              }>
                <Form form={updateForm} initialValues={{ update_date: moment(), recorder: sessionStorage.getItem('nickname') || '' }} labelCol={{span: 4}} wrapperCol={{span: 20}}>
                  <Form.Item required name="update_date" label="动态日期">
                    <DatePicker style={{width: '100%'}} placeholder="请选择日期"/>
                  </Form.Item>
                  <Form.Item required name="recorder" label="记录人">
                    <Input disabled placeholder="自动填充当前用户"/>
                  </Form.Item>
                  <Form.Item required name="detail_content" label="详细记录">
                    <Input.TextArea rows={4} placeholder="请输入详细记录"/>
                  </Form.Item>
                  <Form.Item label="附件上传">
                    <Upload {...uploadProps}>
                      <div>
                        <PlusCircleOutlined />
                        <div style={{ marginTop: 8 }}>上传附件</div>
                      </div>
                    </Upload>
                    <div style={{ fontSize: 12, color: '#999', marginTop: 4 }}>
                      支持图片（ JPG、PNG、GIF、WebP）和Office文件（Word、Excel、PowerPoint、PDF），单个文件最大50MB
                    </div>
                  </Form.Item>
                  <Form.Item wrapperCol={{offset: 4, span: 20}}>
                    <Button type="primary" onClick={handleAddUpdate}>提交</Button>
                    <Button style={{ marginLeft: 8 }} onClick={() => { setAddUpdateVisible(false); setAttachmentList([]); }}>取消</Button>
                  </Form.Item>
                </Form>
              </Card>
            )}

            {/* 内联编辑动态表单 */}
            {editUpdateVisible && (
              <Card size="small" title="编辑动态" style={{ marginBottom: 16 }} extra={
                <Button type="link" icon={<CloseOutlined/>} onClick={() => { setEditUpdateVisible(false); setAttachmentList([]); setEditingUpdate(null); }}/>
              }>
                <Form form={updateForm} initialValues={{ recorder: sessionStorage.getItem('nickname') || '' }} labelCol={{span: 4}} wrapperCol={{span: 20}}>
                  <Form.Item required name="update_date" label="动态日期">
                    <DatePicker style={{width: '100%'}} placeholder="请选择日期"/>
                  </Form.Item>
                  <Form.Item required name="recorder" label="记录人">
                    <Input disabled placeholder="自动填充当前用户"/>
                  </Form.Item>
                  <Form.Item required name="detail_content" label="详细记录">
                    <Input.TextArea rows={4} placeholder="请输入详细记录"/>
                  </Form.Item>
                  <Form.Item label="附件上传">
                    <Upload {...uploadProps}>
                      <div>
                        <PlusCircleOutlined />
                        <div style={{ marginTop: 8 }}>上传附件</div>
                      </div>
                    </Upload>
                    <div style={{ fontSize: 12, color: '#999', marginTop: 4 }}>
                      支持图片（ JPG、PNG、GIF、WebP）和Office文件（Word、Excel、PowerPoint、PDF），单个文件最大50MB
                    </div>
                  </Form.Item>
                  <Form.Item wrapperCol={{offset: 4, span: 20}}>
                    <Button type="primary" onClick={handleUpdateUpdate}>保存</Button>
                    <Button style={{ marginLeft: 8 }} onClick={() => { setEditUpdateVisible(false); setAttachmentList([]); setEditingUpdate(null); }}>取消</Button>
                  </Form.Item>
                </Form>
              </Card>
            )}

            {updatesList.map(update => (
              <div key={update.id} style={{
                marginBottom: 12,
                padding: 12,
                border: '1px solid #e8e8e8',
                borderRadius: 4
              }}>
                <div>
                  <strong>{update.update_date} [序号{update.sequence}] {update.recorder}</strong>
                  {update.can_edit && (
                    <span
                      style={{ marginLeft: 8, color: '#1890ff', cursor: 'pointer' }}
                      onClick={() => handleEditUpdate(update)}
                    >
                      [可编辑]
                    </span>
                  )}
                  {hasPermission('runlog.runlog.update_del') && (
                    <span
                      style={{ marginLeft: 8, color: '#ff4d4f', cursor: 'pointer' }}
                      onClick={() => handleDeleteUpdate(update)}
                    >
                      [删除]
                    </span>
                  )}
                </div>
                <div>{update.detail_content}</div>
                {/* 显示附件列表 */}
                {update.attachments && update.attachments.length > 0 && (
                  <div style={{ marginTop: 8 }}>
                    <div style={{ fontSize: 12, color: '#999', marginBottom: 4 }}>附件：</div>
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
                      {update.attachments.map((url, idx) => {
                        const fileName = url.split('/').pop() || `附件${idx + 1}`;
                        const isImage = /\.(jpg|jpeg|png|gif|webp)$/i.test(fileName);
                        if (isImage) {
                          return (
                            <Image
                              key={idx}
                              src={url}
                              width={100}
                              height={100}
                              style={{ objectFit: 'cover' }}
                            />
                          );
                        } else {
                          // 非图片文件点击使用kkfileview预览
                          return (
                            <a
                              key={idx}
                              onClick={(e) => {
                                e.preventDefault();
                                fetchPreviewUrl(url);
                              }}
                              href={url}
                              target="_blank"
                              rel="noopener noreferrer"
                              title="点击预览"
                              style={{
                                display: 'inline-flex',
                                alignItems: 'center',
                                justifyContent: 'center',
                                width: 100,
                                height: 100,
                                border: '1px solid #d9d9d9',
                                borderRadius: 4,
                                textAlign: 'center',
                                fontSize: 12,
                                color: '#1890ff',
                                textDecoration: 'none',
                                padding: 8,
                                overflow: 'hidden',
                                cursor: 'pointer',
                              }}
                            >
                              {fileName}
                            </a>
                          );
                        }
                      })}
                    </div>
                  </div>
                )}
              </div>
            ))}
            {updatesList.length === 0 && <div style={{ textAlign: 'center', color: '#999' }}>暂无动态记录</div>}
          </TabPane>
        )}
      </Tabs>

      {/* 附件预览弹窗 */}
      <Modal
        title={previewFileName || '文件预览'}
        visible={previewVisible}
        onCancel={handleClosePreview}
        footer={null}
        width="90%"
        style={{ top: 20 }}
        bodyStyle={{ padding: 0, height: 'calc(100vh - 150px)' }}
        destroyOnClose
      >
        {previewLoading ? (
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%' }}>
            <Spin tip="正在加载预览..." />
          </div>
        ) : previewError ? (
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: '100%' }}>
            <div style={{ color: '#ff4d4f', marginBottom: 16 }}>{previewError}</div>
            <Button type="primary" onClick={() => window.open(previewUrl, '_blank')}>
              下载文件
            </Button>
          </div>
        ) : (
          <iframe
            src={previewUrl}
            style={{ width: '100%', height: '100%', border: 'none' }}
            title={`Preview: ${previewFileName}`}
          />
        )}
      </Modal>
    </Modal>
  )
})
