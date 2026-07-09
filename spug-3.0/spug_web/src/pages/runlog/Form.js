/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React, { useState, useEffect, useMemo } from 'react';
import { observer } from 'mobx-react';
import { Modal, Form, Input, Select, DatePicker, Button, message, Descriptions, Tabs, Image, Card } from 'antd';
import { PlusOutlined, CloseOutlined, EditOutlined } from '@ant-design/icons';
import { http, hasPermission } from 'libs';
import moment from 'moment';
import S from './store';

const { Option } = Select;
const { TabPane } = Tabs;

export default observer(function () {
  const [form] = Form.useForm();
  const [updateForm] = Form.useForm();  // 首次动态表单
  const [editUpdateForm] = Form.useForm();
  const [loading, setLoading] = useState(false);
  const [viewMode, setViewMode] = useState(false);
  const [updatesList, setUpdatesList] = useState([]);
  const [addUpdateVisible, setAddUpdateVisible] = useState(false);
  const [editUpdateVisible, setEditUpdateVisible] = useState(false);
  const [editingUpdate, setEditingUpdate] = useState(null);
  const notifyRunLogListChanged = () => {
    window.dispatchEvent(new CustomEvent('runlog:changed'));
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

    const formData = {
      runlog_id: S.record.id,
      update_date: updateData.update_date.format('YYYY-MM-DD'),
      recorder: sessionStorage.getItem('nickname') || '',
      detail_content: updateData.detail_content,
      duty_person: updateData.duty_person || '',
    };

    http.post('/api/runlog/update/', formData)
      .then(res => {
        message.success('动态添加成功');
        updateForm.resetFields();
        setAddUpdateVisible(false);
        notifyRunLogListChanged();
        return fetchUpdates().then(() => S.fetchRecords());
      })
      .catch(err => {
        console.error('[handleAddUpdate] 添加失败:', err);
      });
  }

  function handleEditUpdate(update) {
    // 打开编辑弹窗，填充现有数据
    setAddUpdateVisible(false);
    updateForm.resetFields();
    setEditingUpdate(update);
    editUpdateForm.setFieldsValue({
      update_date: moment(update.update_date),
      recorder: update.recorder,
      detail_content: update.detail_content,
      duty_person: update.duty_person || '',
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
            notifyRunLogListChanged();
            fetchUpdates();
            S.fetchRecords();
            S.fetchStatistics();
          })
      }
    })
  }

  function handleUpdateUpdate() {
    const updateData = editUpdateForm.getFieldsValue();

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
      duty_person: updateData.duty_person || '',
    };

    http.put('/api/runlog/update/', formData)
      .then(() => {
        message.success('动态更新成功');
        editUpdateForm.resetFields();
        setEditUpdateVisible(false);
        setEditingUpdate(null);
        notifyRunLogListChanged();
        return fetchUpdates().then(() => S.fetchRecords());
      });
  }

  function fetchUpdates() {
    if (S.record.id) {
      return http.get('/api/runlog/detail/', {params: {id: S.record.id, _t: Date.now()}})
        .then(res => {
          // json_response 返回结构是 {data: {...}, error: ""}，需要访问 res.data
          const data = res.data || res;
          setUpdatesList(data.updates || []);
          // 始终同步当前详情，避免局部刷新后仍引用旧的 record 快照
          if (data.id) {
            Object.assign(S.record, data);
          }
        })
        .catch(err => {
          console.error('[fetchUpdates] 请求失败:', err);
        });
    } else {
      return Promise.resolve();
    }
  }

  useEffect(() => {
    // 加载事件类型列表
    S.fetchEventTypes();
    if (S.record.id) {
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
        title="跨日事项跟踪详情"
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
                  <div>
                    <strong>{update.update_date} [{update.sequence}] {update.recorder}</strong>
                    {update.duty_person && (
                      <span style={{ marginLeft: 8, color: '#666' }}>值班人：{update.duty_person}</span>
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
                            // 非图片文件点击下载
                            return (
                              <a
                                key={idx}
                                href={url}
                                target="_blank"
                                rel="noopener noreferrer"
                                download
                                title="点击下载"
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
      title={S.record.id ? '编辑跨日事项' : '新建跨日事项'}
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
                <Form.Item name="duty_person" label="值班人">
                  <Input placeholder="请输入值班人（选填）"/>
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
                  setEditUpdateVisible(false);
                  setEditingUpdate(null);
                  editUpdateForm.resetFields();
                  updateForm.resetFields();
                  updateForm.setFieldsValue({
                    update_date: moment(),
                    recorder: sessionStorage.getItem('nickname') || ''
                  });
                  setAddUpdateVisible(true);
                }}>
                  添加动态
                </Button>
              )}
            </div>

            {/* 内联添加动态表单 */}
            {addUpdateVisible && (
              <Card size="small" title="添加动态" style={{ marginBottom: 16 }} extra={
                <Button type="link" icon={<CloseOutlined/>} onClick={() => { setAddUpdateVisible(false); updateForm.resetFields(); }}/>
              }>
                <Form form={updateForm} initialValues={{ update_date: moment(), recorder: sessionStorage.getItem('nickname') || '' }} labelCol={{span: 4}} wrapperCol={{span: 20}}>
                  <Form.Item required name="update_date" label="动态日期">
                    <DatePicker style={{width: '100%'}} placeholder="请选择日期"/>
                  </Form.Item>
                  <Form.Item required name="recorder" label="记录人">
                    <Input disabled placeholder="自动填充当前用户"/>
                  </Form.Item>
                  <Form.Item name="duty_person" label="值班人">
                    <Input placeholder="请输入值班人（选填）"/>
                  </Form.Item>
                  <Form.Item required name="detail_content" label="详细记录">
                    <Input.TextArea rows={4} placeholder="请输入详细记录"/>
                  </Form.Item>
                  <Form.Item wrapperCol={{offset: 4, span: 20}}>
                    <Button type="primary" onClick={handleAddUpdate}>提交</Button>
                    <Button style={{ marginLeft: 8 }} onClick={() => { setAddUpdateVisible(false); updateForm.resetFields(); }}>取消</Button>
                  </Form.Item>
                </Form>
              </Card>
            )}

            {/* 内联编辑动态表单 */}
            {editUpdateVisible && (
              <Card size="small" title="编辑动态" style={{ marginBottom: 16 }} extra={
                <Button type="link" icon={<CloseOutlined/>} onClick={() => { setEditUpdateVisible(false); setEditingUpdate(null); editUpdateForm.resetFields(); }}/>
              }>
                <Form form={editUpdateForm} initialValues={{ recorder: sessionStorage.getItem('nickname') || '' }} labelCol={{span: 4}} wrapperCol={{span: 20}}>
                  <Form.Item required name="update_date" label="动态日期">
                    <DatePicker style={{width: '100%'}} placeholder="请选择日期"/>
                  </Form.Item>
                  <Form.Item required name="recorder" label="记录人">
                    <Input disabled placeholder="自动填充当前用户"/>
                  </Form.Item>
                  <Form.Item name="duty_person" label="值班人">
                    <Input placeholder="请输入值班人（选填）"/>
                  </Form.Item>
                  <Form.Item required name="detail_content" label="详细记录">
                    <Input.TextArea rows={4} placeholder="请输入详细记录"/>
                  </Form.Item>
                  <Form.Item wrapperCol={{offset: 4, span: 20}}>
                    <Button type="primary" onClick={handleUpdateUpdate}>保存</Button>
                    <Button style={{ marginLeft: 8 }} onClick={() => { setEditUpdateVisible(false); setEditingUpdate(null); editUpdateForm.resetFields(); }}>取消</Button>
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
                  {update.duty_person && (
                    <span style={{ marginLeft: 8, color: '#666' }}>值班人：{update.duty_person}</span>
                  )}
                  {update.can_edit && hasPermission('runlog.runlog.update_edit') && (
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
                          // 非图片文件点击下载
                          return (
                            <a
                              key={idx}
                              href={url}
                              target="_blank"
                              rel="noopener noreferrer"
                              download
                              title="点击下载"
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
    </Modal>
  )
})
